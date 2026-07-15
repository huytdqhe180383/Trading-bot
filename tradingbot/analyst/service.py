"""Analyst-only orchestration.

The service produces events and reports. It deliberately does not import or call
live execution modules, order gateways, or allocation fusion code.
"""

from __future__ import annotations

from typing import Any

from config import (
    ANALYST_ENABLED,
    ANALYST_EVENT_LIMIT,
    LIVE_SESSION_TIMEZONE,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_BACKGROUND_MODEL,
    LLM_DAILY_CALL_BUDGET,
    LLM_INTERACTIVE_MODEL,
    LLM_INTERACTIVE_CALL_BUDGET,
    LLM_TIMEOUT_SECS,
    LLM_USE_RESPONSE_FORMAT,
    REPORTS_DIR,
    RESULTS_DIR,
    SYMBOLS,
)

from .budget import LLMBudget, LLMBudgetExhausted
from .llm import LLMInvalidResponseError, LLMProviderError, OpenAICompatibleLLMClient
from .market import fetch_public_snapshot
from .models import AnalystEvent, AnalystStatus, AnalystValidationError, validate_analyst_payload
from .news import build_news_snapshot, format_news_message
from .store import AnalystEventStore


class AnalystService:
    def __init__(
        self,
        *,
        llm_client: OpenAICompatibleLLMClient | None = None,
        interactive_llm_client: OpenAICompatibleLLMClient | None = None,
        background_llm_client: OpenAICompatibleLLMClient | None = None,
        budget: LLMBudget,
        store: AnalystEventStore,
        enabled: bool = False,
        event_limit: int = 200,
    ) -> None:
        base_client = llm_client or interactive_llm_client or background_llm_client
        if base_client is None:
            raise ValueError("AnalystService requires at least one LLM client.")
        self.interactive_llm_client = interactive_llm_client or base_client
        self.background_llm_client = background_llm_client or base_client
        self.budget = budget
        self.store = store
        self.enabled = bool(enabled)
        self.event_limit = max(1, int(event_limit))

    def status(self) -> AnalystStatus:
        events = self.store.load_events(limit=self.event_limit)
        return AnalystStatus(
            enabled=self.enabled,
            events_count=len(events),
            budgets=self.budget.snapshot(),
            latest_event=events[-1] if events else None,
        )

    def events(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        return [
            _public_event(row)
            for row in self.store.load_events(limit=limit or self.event_limit)
        ]

    def signals(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        return [
            _public_event(row)
            for row in self.store.load_signals(limit=limit or self.event_limit)
        ]

    def run_update(
        self,
        *,
        symbol: str = "ALL",
        market_snapshot: dict[str, Any] | None = None,
        scope: str = "interactive",
    ) -> AnalystEvent:
        normalized_symbol = _normalize_symbol(symbol)
        news_snapshot = build_news_snapshot(symbol=normalized_symbol)
        prompt_payload = {
            "symbol": normalized_symbol,
            "market_snapshot": market_snapshot or {"status": "snapshot_unavailable"},
            "news_snapshot": news_snapshot,
            "task": (
                "Return strict JSON with recommendation, confidence, rationale, risk_notes, invalidation. "
                "Use only BUY, SELL, REDUCE, HOLD, or AVOID. Do not include quantities, leverage, "
                "orders, exchange commands, or target allocations."
            ),
        }
        return self._call_role(
            role="main_analyst",
            event_type="analysis",
            title=f"{normalized_symbol} analyst update",
            prompt_payload=prompt_payload,
            scope=scope,
        )

    def ask(
        self,
        *,
        question: str,
        symbol: str = "ALL",
        scope: str = "interactive",
    ) -> AnalystEvent:
        normalized_symbol = _normalize_symbol(symbol)
        news_snapshot = build_news_snapshot(symbol=normalized_symbol)
        market_snapshot = _safe_public_snapshot(normalized_symbol)
        prompt_payload = {
            "symbol": normalized_symbol,
            "question": str(question or "").strip(),
            "market_snapshot": market_snapshot,
            "news_snapshot": news_snapshot,
            "task": (
                "Answer as an analyst. Return strict JSON with recommendation, confidence, rationale, "
                "risk_notes, invalidation. If the user explicitly asks for position advice, give a "
                "directional advisory view using BUY, SELL, REDUCE, HOLD, or AVOID based on the supplied "
                "public market snapshot and news. Do not default to HOLD merely because the answer is "
                "advisory; use HOLD only when the evidence is genuinely balanced or insufficient. If the "
                "question is not about market direction, recommendation may be HOLD while the rationale "
                "answers the question. Do not include quantities, leverage, orders, exchange commands, "
                "or target allocations."
            ),
        }
        return self._call_role(
            role="main_analyst",
            event_type="chat_reply",
            title=f"{normalized_symbol} analyst answer",
            prompt_payload=prompt_payload,
            scope=scope,
        )

    def validate(
        self,
        *,
        alert_id: str = "",
        symbol: str = "ALL",
        scope: str = "interactive",
    ) -> AnalystEvent:
        normalized_symbol = _normalize_symbol(symbol)
        related = next((event for event in self.events() if event.get("id") == alert_id), None)
        if related and normalized_symbol == "ALL":
            normalized_symbol = _normalize_symbol(str(related.get("symbol", "ALL")))
        news_snapshot = build_news_snapshot(symbol=normalized_symbol)
        prompt_payload = {
            "symbol": normalized_symbol,
            "alert_id": alert_id,
            "related_alert": related or {},
            "news_snapshot": news_snapshot,
            "task": (
                "Act as risk validator. Return strict JSON with recommendation, confidence, rationale, "
                "risk_notes, invalidation. Do not include quantities, leverage, orders, exchange commands, "
                "or target allocations."
            ),
        }
        return self._call_role(
            role="risk_validator",
            event_type="validation",
            title=f"{normalized_symbol} risk validation",
            prompt_payload=prompt_payload,
            scope=scope,
        )

    def explain(self, *, alert_id: str) -> AnalystEvent:
        related = next((event for event in self.events() if event.get("id") == alert_id), None)
        if not related:
            event = AnalystEvent(
                event_type="explain",
                status="error",
                title="Alert not found",
                message=f"No analyst alert found for id={alert_id}.",
                error_code="not_found",
                payload={"alert_id": alert_id},
            )
            return self.store.append(event)
        prompt_payload = {
            "symbol": _normalize_symbol(str(related.get("symbol", "ALL"))),
            "alert_id": alert_id,
            "related_alert": related,
            "news_snapshot": build_news_snapshot(symbol=_normalize_symbol(str(related.get("symbol", "ALL")))),
            "task": (
                "Explain this existing alert in fresh, plainer language for a human analyst. "
                "Return strict JSON with recommendation, confidence, rationale, risk_notes, invalidation. "
                "Do not copy the original rationale verbatim. Do not include quantities, leverage, orders, "
                "exchange commands, or target allocations."
            ),
        }
        return self._call_role(
            role="main_analyst",
            event_type="explain",
            title=f"Explanation for {alert_id}",
            prompt_payload=prompt_payload,
            scope="interactive",
        )

    def latest_news(self, *, symbol: str = "ALL", alert_id: str = "") -> AnalystEvent:
        normalized_symbol = _normalize_symbol(symbol)
        related = next((event for event in self.events() if event.get("id") == alert_id), None)
        if related and normalized_symbol == "ALL":
            normalized_symbol = _normalize_symbol(str(related.get("symbol", "ALL")))
        snapshot = build_news_snapshot(symbol=normalized_symbol, limit=8)
        if snapshot.get("status") == "ok":
            event = AnalystEvent(
                event_type="news",
                status="ok",
                title=f"{normalized_symbol} public crypto news",
                message=format_news_message(snapshot, symbol=normalized_symbol),
                symbol=normalized_symbol,
                role="system",
                payload={"alert_id": alert_id, **snapshot},
            )
        else:
            event = AnalystEvent(
                event_type="news",
                status="error",
                title=f"{normalized_symbol} public crypto news unavailable",
                message=f"Public crypto news unavailable: {snapshot.get('error', 'unknown error')}",
                symbol=normalized_symbol,
                role="system",
                error_code="news_unavailable",
                payload={"alert_id": alert_id, **snapshot},
            )
        return self.store.append(event)

    def _call_role(
        self,
        *,
        role: str,
        event_type: str,
        title: str,
        prompt_payload: dict[str, Any],
        scope: str,
    ) -> AnalystEvent:
        normalized_scope = _normalize_llm_scope(scope)
        llm_client = self._llm_client_for_scope(normalized_scope)
        prompt_payload = {
            **prompt_payload,
            "scope": normalized_scope,
            "llm_model": getattr(llm_client, "model", ""),
        }
        try:
            self.budget.reserve(normalized_scope)
            if role == "main_analyst" and normalized_scope == "interactive" and event_type in {"analysis", "chat_reply"}:
                prompt_payload["auxiliary_views"] = self._build_auxiliary_views(prompt_payload)
            raw = llm_client.chat_json(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a senior discretionary crypto market analyst. "
                            "You are not an autonomous trading system. "
                            "Synthesize price action, levels, volume, news, uncertainty, and auxiliary analyst views. "
                            "Be decisive when evidence is directional and humble when it is mixed. "
                            "Output only strict JSON with natural, human-readable rationale."
                        ),
                    },
                    {"role": "user", "content": _json_prompt(prompt_payload)},
                ],
            )
            parsed = validate_analyst_payload(raw)
        except LLMBudgetExhausted as exc:
            return self._record_failure(
                event_type=event_type,
                title=title,
                role=role,
                status="budget_exhausted",
                error_code="budget_exhausted",
                message=str(exc),
                prompt_payload=prompt_payload,
            )
        except (LLMProviderError, LLMInvalidResponseError) as exc:
            status = "invalid_response" if isinstance(exc, LLMInvalidResponseError) else "error"
            return self._record_failure(
                event_type=event_type,
                title=title,
                role=role,
                status=status,
                error_code=type(exc).__name__,
                message=str(exc),
                prompt_payload=prompt_payload,
            )
        except AnalystValidationError as exc:
            return self._record_failure(
                event_type=event_type,
                title=title,
                role=role,
                status="invalid_response",
                error_code="AnalystValidationError",
                message=str(exc),
                prompt_payload=prompt_payload,
            )

        event = AnalystEvent(
            event_type=event_type,
            status="ok",
            title=title,
            message=parsed["rationale"] or "Analyst response received.",
            symbol=str(prompt_payload.get("symbol", "ALL")),
            role=role,
            recommendation=parsed["recommendation"],
            confidence=parsed["confidence"],
            rationale=parsed["rationale"],
            risk_notes=parsed["risk_notes"],
            invalidation=parsed["invalidation"],
            payload={
                "scope": normalized_scope,
                "alert_id": prompt_payload.get("alert_id", ""),
                "market_snapshot": prompt_payload.get("market_snapshot", {}),
                "news_snapshot": prompt_payload.get("news_snapshot", {}),
                "auxiliary_views": prompt_payload.get("auxiliary_views", []),
                "llm_scope": normalized_scope,
                "llm_model": getattr(llm_client, "model", ""),
            },
        )
        return self.store.append(event)

    def _build_auxiliary_views(self, prompt_payload: dict[str, Any]) -> list[dict[str, Any]]:
        views = []
        for role, task in (
            (
                "technical_analyst",
                "Focus only on public market structure, trend, momentum, support/resistance, volatility, and volume. "
                "Return strict JSON with recommendation, confidence, rationale, risk_notes, invalidation. "
                "No quantities, leverage, orders, exchange commands, or target allocations.",
            ),
            (
                "news_analyst",
                "Focus only on the supplied public news snapshot and event risk. "
                "Return strict JSON with recommendation, confidence, rationale, risk_notes, invalidation. "
                "No quantities, leverage, orders, exchange commands, or target allocations.",
            ),
        ):
            try:
                self.budget.reserve("background")
                raw = self.background_llm_client.chat_json(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                f"You are the {role.replace('_', ' ')} in an analyst-only crypto research team. "
                                "You are advisory only. Output only strict JSON."
                            ),
                        },
                        {"role": "user", "content": _json_prompt({**prompt_payload, "task": task, "auxiliary_role": role})},
                    ],
                )
                parsed = validate_analyst_payload(raw)
                views.append(
                    {
                        "role": role,
                        "status": "ok",
                        "recommendation": parsed["recommendation"],
                        "confidence": parsed["confidence"],
                        "rationale": parsed["rationale"],
                        "risk_notes": parsed["risk_notes"],
                        "invalidation": parsed["invalidation"],
                        "llm_model": getattr(self.background_llm_client, "model", ""),
                    }
                )
            except (LLMBudgetExhausted, LLMProviderError, LLMInvalidResponseError, AnalystValidationError) as exc:
                views.append(
                    {
                        "role": role,
                        "status": "unavailable",
                        "error_code": type(exc).__name__,
                        "message": str(exc),
                        "llm_model": getattr(self.background_llm_client, "model", ""),
                    }
                )
        return views

    def _record_failure(
        self,
        *,
        event_type: str,
        title: str,
        role: str,
        status: str,
        error_code: str,
        message: str,
        prompt_payload: dict[str, Any],
    ) -> AnalystEvent:
        event = AnalystEvent(
            event_type=event_type,
            status=status,
            title=title,
            message=f"LLM unavailable: {message}",
            symbol=str(prompt_payload.get("symbol", "ALL")),
            role=role,
            error_code=error_code,
            payload={
                "scope": _normalize_llm_scope(str(prompt_payload.get("scope", ""))),
                "symbol": prompt_payload.get("symbol", "ALL"),
                "llm_model": prompt_payload.get("llm_model", ""),
            },
        )
        return self.store.append(event)

    def _llm_client_for_scope(self, scope: str) -> OpenAICompatibleLLMClient:
        if _normalize_llm_scope(scope) == "background":
            return self.background_llm_client
        return self.interactive_llm_client


def create_default_analyst_service() -> AnalystService:
    return AnalystService(
        interactive_llm_client=OpenAICompatibleLLMClient(
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY,
            model=LLM_INTERACTIVE_MODEL,
            model_config_name="LLM_INTERACTIVE_MODEL",
            timeout_secs=LLM_TIMEOUT_SECS,
            use_response_format=LLM_USE_RESPONSE_FORMAT,
        ),
        background_llm_client=OpenAICompatibleLLMClient(
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY,
            model=LLM_BACKGROUND_MODEL,
            model_config_name="LLM_BACKGROUND_MODEL",
            timeout_secs=LLM_TIMEOUT_SECS,
            use_response_format=LLM_USE_RESPONSE_FORMAT,
        ),
        budget=LLMBudget(
            background_daily_limit=LLM_DAILY_CALL_BUDGET,
            interactive_daily_limit=LLM_INTERACTIVE_CALL_BUDGET,
            tz_name=LIVE_SESSION_TIMEZONE,
        ),
        store=AnalystEventStore(
            results_dir=RESULTS_DIR,
            reports_dir=REPORTS_DIR,
            tz_name=LIVE_SESSION_TIMEZONE,
        ),
        enabled=ANALYST_ENABLED,
        event_limit=ANALYST_EVENT_LIMIT,
    )


def _normalize_symbol(symbol: str) -> str:
    value = str(symbol or "ALL").strip().upper()
    if value in {"ALL", "BTC", "ETH"}:
        return value
    if value in SYMBOLS:
        return value
    return "ALL"


def _json_prompt(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def _safe_public_snapshot(symbol: str) -> dict[str, Any]:
    if symbol == "ALL":
        return {"status": "snapshot_unavailable", "reason": "symbol_all"}
    try:
        snapshot = fetch_public_snapshot(symbol)
        snapshot["status"] = "ok"
        return snapshot
    except Exception as exc:
        return {"status": "snapshot_unavailable", "error": str(exc)}


def _normalize_llm_scope(scope: str) -> str:
    return "background" if str(scope or "").strip().lower() == "background" else "interactive"


def _public_event(row: dict[str, Any]) -> dict[str, Any]:
    blocked = {"api_key", "secret", "token", "authorization", "private_balances", "exchange_credentials"}
    payload = row.get("payload", {})
    if isinstance(payload, dict):
        row = dict(row)
        row["payload"] = {key: value for key, value in payload.items() if str(key).lower() not in blocked}
    return row
