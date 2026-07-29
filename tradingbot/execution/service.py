"""Multi-agent order planning and explicitly confirmed OKX demo execution."""

from __future__ import annotations

import json
import math
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from config import (
    OKX_EXECUTION_ENABLED,
    OPERATIONAL_DATABASE_PATH,
    ORDER_SUGGESTION_TTL_SECS,
    LIVE_SESSION_TIMEZONE,
    RESULTS_DIR,
)
from tradingbot.analyst.budget import LLMBudgetExhausted
from tradingbot.analyst.llm import LLMInvalidResponseError, LLMProviderError
from tradingbot.analyst.models import AnalystEvent, AnalystValidationError
from tradingbot.analyst.news import build_news_snapshot
from tradingbot.analyst.service import AnalystService
from tradingbot.analyst.store import AnalystEventStore

from .okx_client import OKXClientError, OKXDemoClient, normalize_inst_id
from .suggestions import OrderSuggestionStore


class OrderSuggestionValidationError(ValueError):
    """Raised when the order-planning LLM does not return a safe order plan."""


class TradingExecutionService:
    """Plan orders with multiple LLM views, then execute only after confirmation."""

    def __init__(
        self,
        *,
        analyst_service: AnalystService,
        okx_client: OKXDemoClient,
        suggestion_store: OrderSuggestionStore,
        event_store: AnalystEventStore,
        execution_enabled: bool = OKX_EXECUTION_ENABLED,
        suggestion_ttl_secs: int = ORDER_SUGGESTION_TTL_SECS,
    ) -> None:
        self.analyst_service = analyst_service
        self.okx = okx_client
        self.suggestion_store = suggestion_store
        self.event_store = event_store
        self.execution_enabled = bool(execution_enabled)
        self.suggestion_ttl_secs = max(60, int(suggestion_ttl_secs))

    def account_context(self, *, symbol: str = "") -> dict[str, Any]:
        """Return private account context for an authenticated operator/LLM call."""
        return self.okx.fetch_account_context(inst_id=normalize_inst_id(symbol) if symbol else None)

    def suggest_order(self, *, symbol: str, instruction: str, requested_by: str) -> AnalystEvent:
        try:
            normalized = normalize_inst_id(symbol)
        except ValueError as exc:
            return self._event(
                event_type="order_suggestion",
                status="error",
                title="Unsupported order instrument",
                message=str(exc),
                symbol="ALL",
                error_code="unsupported_instrument",
            )
        if not str(requested_by).strip():
            return self._event(
                event_type="order_suggestion",
                status="error",
                title=f"{normalized} order suggestion unavailable",
                message="A Discord requester identity is required.",
                symbol=normalized.replace("-", ""),
                error_code="missing_requester",
            )
        instruction = str(instruction or "").strip()
        if not instruction:
            return self._event(
                event_type="order_suggestion",
                status="error",
                title=f"{normalized} order suggestion unavailable",
                message="An order instruction is required.",
                symbol=normalized.replace("-", ""),
                error_code="missing_instruction",
            )
        try:
            account = self.okx.fetch_account_context(inst_id=normalized)
            market = self.okx.fetch_market_context(normalized)
            news = build_news_snapshot(symbol=normalized.replace("-", ""))
            prompt_payload = {
                "symbol": normalized.replace("-", ""),
                "instrument": market.get("instrument", {}),
                "market_context": market,
                "account_context": account,
                "news_snapshot": news,
                "instruction": instruction,
                "auxiliary_views": self.analyst_service.build_multi_agent_views(
                    {
                        "symbol": normalized.replace("-", ""),
                        "market_snapshot": market,
                        "account_context": account,
                        "news_snapshot": news,
                        "task": (
                            "Provide a directional risk view for an execution planner. "
                            "Do not propose an order, quantity, leverage, or exchange command."
                        ),
                    }
                ),
                "risk_limits": {
                    "max_order_notional_usdt": self.okx.max_order_notional_usdt,
                    "max_slippage_pct": self.okx.max_slippage_pct,
                },
            }
            self.analyst_service.budget.reserve("interactive")
            raw = self.analyst_service.interactive_llm_client.chat_json(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are the execution-planning agent in a multi-agent crypto system. "
                            "The account context is private and may be stale. This response is only a "
                            "suggestion; never claim that an order was submitted. Return only strict JSON. "
                            "Use spot BTC-USDT or ETH-USDT. Choose NO_TRADE when the evidence or account "
                            "state is insufficient. For PLACE, use side BUY/SELL, order_type MARKET/LIMIT, "
                            "size, size_unit base/quote, optional price, slippage_pct as a decimal fraction, "
                            "rationale, risk_notes, and confidence. Market BUY uses quote-sized USDT and "
                            "market SELL uses base-sized asset units. Limit orders use base size. "
                            "Never include leverage, withdrawal, credentials, or an exchange command. "
                            "A market order must explicitly include slippage_pct within the supplied maximum."
                        ),
                    },
                    {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=True, sort_keys=True)},
                ]
            )
            plan = validate_order_plan(raw, max_slippage_pct=self.okx.max_slippage_pct)
            if plan["action"] == "NO_TRADE":
                return self._event(
                    event_type="order_suggestion",
                    status="no_trade",
                    title=f"{normalized} no-trade suggestion",
                    message=plan["rationale"] or "The execution planner recommends no trade.",
                    symbol=normalized.replace("-", ""),
                    role="execution_planner",
                    confidence=plan.get("confidence"),
                    rationale=plan["rationale"],
                    risk_notes=plan["risk_notes"],
                    payload={"account_context_received": True, "auxiliary_views": prompt_payload["auxiliary_views"]},
                )
            order = self.okx.normalize_order(
                {**plan, "inst_id": normalized},
                instrument=market["instrument"],
                market=market,
            )
            self.okx.check_limit_price_slippage(order, market=market)
            suggestion_id = uuid.uuid4().hex
            now = datetime.now(timezone.utc)
            expires = now.timestamp() + self.suggestion_ttl_secs
            record = {
                "id": suggestion_id,
                "event_id": suggestion_id,
                "requested_by": str(requested_by),
                "created_at_utc": now.isoformat(),
                "expires_at_utc": datetime.fromtimestamp(expires, timezone.utc).isoformat(),
                "status": "pending",
                "order": order,
                "rationale": plan["rationale"],
                "risk_notes": plan["risk_notes"],
                "confidence": plan.get("confidence"),
                "account_context_received": True,
                "open_orders_seen": len(account.get("open_orders", [])),
                "positions_seen": len(account.get("positions", [])),
            }
            self.suggestion_store.create(record)
            return self._event(
                event_type="order_suggestion",
                status="pending",
                title=f"{normalized} order suggestion awaiting confirmation",
                message=plan["rationale"] or "Order suggestion created.",
                symbol=normalized.replace("-", ""),
                role="execution_planner",
                recommendation="BUY" if order["side"] == "buy" else "SELL",
                confidence=plan.get("confidence"),
                rationale=plan["rationale"],
                risk_notes=plan["risk_notes"],
                payload={
                    "suggestion_id": suggestion_id,
                    "order": order,
                    "expires_at_utc": record["expires_at_utc"],
                    "account_context_received": True,
                    "open_orders_seen": record["open_orders_seen"],
                    "positions_seen": record["positions_seen"],
                    "llm_model": getattr(self.analyst_service.interactive_llm_client, "model", ""),
                },
            )
        except (OKXClientError, OrderSuggestionValidationError, AnalystValidationError, ValueError) as exc:
            return self._event(
                event_type="order_suggestion",
                status="error",
                title=f"{normalized} order suggestion failed",
                message=str(exc),
                symbol=normalized.replace("-", ""),
                role="execution_planner",
                error_code=type(exc).__name__,
            )
        except LLMBudgetExhausted as exc:
            return self._event(
                event_type="order_suggestion",
                status="budget_exhausted",
                title=f"{normalized} order suggestion blocked",
                message=str(exc),
                symbol=normalized.replace("-", ""),
                role="execution_planner",
                error_code="budget_exhausted",
            )
        except (LLMProviderError, LLMInvalidResponseError) as exc:
            return self._event(
                event_type="order_suggestion",
                status="error" if isinstance(exc, LLMProviderError) else "invalid_response",
                title=f"{normalized} order suggestion unavailable",
                message=str(exc),
                symbol=normalized.replace("-", ""),
                role="execution_planner",
                error_code=type(exc).__name__,
            )

    def confirm_order(self, *, suggestion_id: str, requested_by: str) -> AnalystEvent:
        record = self.suggestion_store.get(suggestion_id)
        if record is None:
            return self._event(
                event_type="order_confirmation",
                status="error",
                title="Order suggestion not found",
                message="The order suggestion no longer exists.",
                error_code="not_found",
                payload={"suggestion_id": suggestion_id},
            )
        if str(record.get("requested_by", "")) != str(requested_by):
            return self._event(
                event_type="order_confirmation",
                status="error",
                title="Order confirmation denied",
                message="Only the Discord user who requested this suggestion may confirm it.",
                error_code="requester_mismatch",
                payload={"suggestion_id": suggestion_id},
            )
        if record.get("status") != "pending":
            return self._event(
                event_type="order_confirmation",
                status="error",
                title="Order confirmation unavailable",
                message=f"This suggestion is already {record.get('status', 'closed')}.",
                error_code="not_pending",
                payload={"suggestion_id": suggestion_id, "status": record.get("status")},
            )
        if _parse_timestamp(record.get("expires_at_utc")) <= time.time():
            self.suggestion_store.expire(suggestion_id)
            return self._event(
                event_type="order_confirmation",
                status="expired",
                title="Order suggestion expired",
                message="Create a fresh suggestion so price, liquidity, and account state can be rechecked.",
                error_code="expired",
                payload={"suggestion_id": suggestion_id},
            )
        if not self.execution_enabled:
            return self._event(
                event_type="order_confirmation",
                status="blocked",
                title="Order submission disabled",
                message="OKX_EXECUTION_ENABLED is false.",
                error_code="execution_disabled",
                payload={"suggestion_id": suggestion_id},
            )
        claimed = self.suggestion_store.claim_for_confirmation(suggestion_id, requested_by)
        if claimed is None:
            latest = self.suggestion_store.get(suggestion_id) or {}
            return self._event(
                event_type="order_confirmation",
                status="error",
                title="Order confirmation unavailable",
                message=f"This suggestion is already {latest.get('status', 'closed')}.",
                error_code="not_pending",
                payload={"suggestion_id": suggestion_id, "status": latest.get("status", "closed")},
            )
        record = claimed
        try:
            order = dict(record["order"])
            instrument = self.okx.fetch_instrument(order["inst_id"])
            market = self.okx.fetch_market_context(order["inst_id"])
            account = self.okx.fetch_account_context(inst_id=order["inst_id"])
            order = self.okx.normalize_order(order, instrument=instrument, market=market)
            self.okx.check_capacity(order, account=account, market=market)
            self.okx.check_limit_price_slippage(order, market=market)
            slippage = self.okx.estimate_market_slippage(order, market=market)
            if slippage.get("applicable") and float(slippage.get("estimated_slippage_pct", 0.0)) > self.okx.max_slippage_pct:
                raise OKXClientError(
                    "Visible order-book slippage exceeds the configured maximum; create a fresh, smaller suggestion."
                )
            client_order_id = f"codex{uuid.uuid4().hex[:20]}"
            result = self.okx.place_order(
                order,
                client_order_id=client_order_id,
                exp_time_ms=int(time.time() * 1000) + 10_000,
            )
            self.suggestion_store.update(
                suggestion_id,
                status="submitted",
                order_id=result.get("ord_id", ""),
                client_order_id=result.get("cl_ord_id", client_order_id),
                execution_summary={
                    "ord_id": result.get("ord_id", ""),
                    "cl_ord_id": result.get("cl_ord_id", client_order_id),
                    "estimated_slippage_pct": slippage.get("estimated_slippage_pct", 0.0),
                },
            )
            return self._event(
                event_type="order_confirmation",
                status="submitted",
                title=f"{order['inst_id']} order submitted to OKX demo",
                message="The confirmed order was accepted by the OKX demo-trading API.",
                symbol=order["inst_id"].replace("-", ""),
                role="execution_gateway",
                recommendation="BUY" if order["side"] == "buy" else "SELL",
                payload={
                    "suggestion_id": suggestion_id,
                    "order": order,
                    "order_id": result.get("ord_id", ""),
                    "client_order_id": result.get("cl_ord_id", client_order_id),
                    "estimated_slippage_pct": slippage.get("estimated_slippage_pct", 0.0),
                    "demo_trading": True,
                },
            )
        except OKXClientError as exc:
            self.suggestion_store.update(suggestion_id, status="failed", failure=str(exc))
            return self._event(
                event_type="order_confirmation",
                status="failed",
                title="OKX demo order was not submitted",
                message=str(exc),
                symbol=str(record.get("order", {}).get("inst_id", "")).replace("-", ""),
                role="execution_gateway",
                error_code=type(exc).__name__,
                payload={"suggestion_id": suggestion_id},
            )

    def reject_order(self, *, suggestion_id: str, requested_by: str) -> AnalystEvent:
        record = self.suggestion_store.get(suggestion_id)
        if record is None:
            return self._event(
                event_type="order_rejection",
                status="error",
                title="Order suggestion not found",
                message="The order suggestion no longer exists.",
                error_code="not_found",
            )
        if str(record.get("requested_by", "")) != str(requested_by):
            return self._event(
                event_type="order_rejection",
                status="error",
                title="Order rejection denied",
                message="Only the Discord user who requested this suggestion may reject it.",
                error_code="requester_mismatch",
            )
        if record.get("status") != "pending":
            return self._event(
                event_type="order_rejection",
                status="error",
                title="Order suggestion already closed",
                message=f"This suggestion is already {record.get('status', 'closed')}.",
                error_code="not_pending",
            )
        rejected = self.suggestion_store.reject(suggestion_id, requested_by)
        if rejected is None:
            latest = self.suggestion_store.get(suggestion_id) or {}
            return self._event(
                event_type="order_rejection",
                status="error",
                title="Order rejection unavailable",
                message=f"This suggestion is already {latest.get('status', 'closed')}.",
                error_code="not_pending",
                payload={"suggestion_id": suggestion_id, "status": latest.get("status", "closed")},
            )
        return self._event(
            event_type="order_rejection",
            status="rejected",
            title="Order suggestion rejected",
            message="No order was sent to OKX.",
            error_code="user_rejected",
            payload={"suggestion_id": suggestion_id},
        )

    def _event(self, *, event_type: str, status: str, title: str, message: str, **kwargs: Any) -> AnalystEvent:
        return self.event_store.append(
            AnalystEvent(
                event_type=event_type,
                status=status,
                title=title,
                message=message,
                **kwargs,
            )
        )


def validate_order_plan(raw: Any, *, max_slippage_pct: float) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise OrderSuggestionValidationError("Execution planner response must be a JSON object.")
    forbidden = {"api_key", "secret", "passphrase", "leverage", "withdrawal", "exchange_command", "credentials"}
    if any(str(key).strip().lower() in forbidden for key in raw):
        raise OrderSuggestionValidationError("Execution planner returned a forbidden field.")
    action = str(raw.get("action", "")).strip().upper()
    if action not in {"PLACE", "NO_TRADE"}:
        raise OrderSuggestionValidationError("action must be PLACE or NO_TRADE.")
    rationale = str(raw.get("rationale", "")).strip()
    risk_notes = str(raw.get("risk_notes", "")).strip()
    confidence = raw.get("confidence")
    if confidence is not None:
        try:
            confidence = float(confidence)
        except (TypeError, ValueError) as exc:
            raise OrderSuggestionValidationError("confidence must be numeric.") from exc
        if confidence > 1:
            confidence /= 100
        if not math.isfinite(confidence) or confidence < 0 or confidence > 1:
            raise OrderSuggestionValidationError("confidence must be between 0 and 1.")
    if action == "NO_TRADE":
        return {"action": action, "rationale": rationale, "risk_notes": risk_notes, "confidence": confidence}
    side = str(raw.get("side", "")).strip().upper()
    order_type = str(raw.get("order_type", raw.get("ord_type", ""))).strip().upper()
    size_unit = str(raw.get("size_unit", "")).strip().lower()
    if side not in {"BUY", "SELL"} or order_type not in {"MARKET", "LIMIT"}:
        raise OrderSuggestionValidationError("PLACE requires side BUY/SELL and order_type MARKET/LIMIT.")
    if not rationale:
        raise OrderSuggestionValidationError("PLACE requires a rationale.")
    size = raw.get("size")
    try:
        numeric_size = float(size)
    except (TypeError, ValueError) as exc:
        raise OrderSuggestionValidationError("PLACE requires numeric size.") from exc
    if not math.isfinite(numeric_size) or numeric_size <= 0:
        raise OrderSuggestionValidationError("size must be greater than zero.")
    if size_unit not in {"base", "quote"}:
        raise OrderSuggestionValidationError("size_unit must be base or quote.")
    if order_type == "MARKET" and side == "BUY" and size_unit != "quote":
        raise OrderSuggestionValidationError("Market BUY must use quote-sized USDT input.")
    if order_type == "MARKET" and side == "SELL" and size_unit != "base":
        raise OrderSuggestionValidationError("Market SELL must use base-sized asset input.")
    if order_type == "LIMIT" and size_unit != "base":
        raise OrderSuggestionValidationError("Limit orders must use base size.")
    slippage = raw.get("slippage_pct")
    if order_type == "MARKET" and slippage is None:
        raise OrderSuggestionValidationError("Market orders must include slippage_pct.")
    if order_type == "LIMIT" and slippage is None:
        slippage = max_slippage_pct
    try:
        slippage_value = float(slippage if slippage is not None else 0.0)
    except (TypeError, ValueError) as exc:
        raise OrderSuggestionValidationError("slippage_pct must be numeric.") from exc
    if not math.isfinite(slippage_value) or slippage_value < 0 or slippage_value > float(max_slippage_pct):
        raise OrderSuggestionValidationError(f"slippage_pct exceeds the configured maximum of {max_slippage_pct:g}.")
    price = raw.get("price")
    if order_type == "LIMIT":
        try:
            if not math.isfinite(float(price)) or float(price) <= 0:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise OrderSuggestionValidationError("Limit orders require a positive price.") from exc
    return {
        "action": action,
        "side": side,
        "ord_type": order_type,
        "size": str(size),
        "size_unit": size_unit,
        "price": str(price) if price is not None else None,
        "slippage_pct": str(slippage_value),
        "rationale": rationale,
        "risk_notes": risk_notes,
        "confidence": confidence,
    }


def create_default_execution_service(*, analyst_service: AnalystService) -> TradingExecutionService:
    return TradingExecutionService(
        analyst_service=analyst_service,
        okx_client=OKXDemoClient(),
        suggestion_store=OrderSuggestionStore(
            results_dir=RESULTS_DIR,
            tz_name=LIVE_SESSION_TIMEZONE,
            database_path=OPERATIONAL_DATABASE_PATH,
        ),
        event_store=analyst_service.store,
        execution_enabled=OKX_EXECUTION_ENABLED,
        suggestion_ttl_secs=ORDER_SUGGESTION_TTL_SECS,
    )


def _parse_timestamp(value: Any) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0.0
