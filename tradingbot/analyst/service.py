"""Analyst-only orchestration.

The service produces events and reports. It deliberately does not import or call
live execution modules, order gateways, or allocation fusion code.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from config import (
    ANALYST_ENABLED,
    ANALYST_EVENT_LIMIT,
    ANALYST_TIMEFRAME_CONTEXT_TTL_SECS,
    ANALYST_RL_EVIDENCE_MAX_AGE_SECS,
    ANALYST_RL_EVIDENCE_PATH,
    LIVE_SESSION_TIMEZONE,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_LOWER_API_KEY,
    LLM_LOWER_BASE_URL,
    LLM_LOWER_FALLBACK_API_KEY,
    LLM_1_HOUR_MODEL,
    LLM_1_MIN_MODEL,
    LLM_15_MIN_MODEL,
    LLM_4_HOUR_MODEL,
    MANUAL_ANALYSIS_CACHE_SECS,
    MANUAL_MODEL,
    LLM_BACKGROUND_MODEL,
    LLM_FAILURE_COOLDOWN_SECS,
    LLM_FAILURE_THRESHOLD,
    LLM_INTERACTIVE_MODEL,
    LLM_INTERACTIVE_CALL_BUDGET,
    LLM_1_HOUR_CALL_BUDGET,
    LLM_1_MIN_CALL_BUDGET,
    LLM_15_MIN_CALL_BUDGET,
    LLM_4_HOUR_CALL_BUDGET,
    LLM_MANUAL_CALL_BUDGET,
    LLM_SCHEDULED_CALL_BUDGET,
    LLM_SCREENING_CALL_BUDGET,
    LLM_STRONG_TIMEOUT_SECS,
    LLM_TIMEOUT_SECS,
    LLM_USE_RESPONSE_FORMAT,
    LLM_WEAK_TIMEOUT_SECS,
    OPERATIONAL_DATABASE_PATH,
    REPORTS_DIR,
    RESULTS_DIR,
    SYMBOLS,
)
from tradingbot.prompts import ANALYST_PROMPT_VERSION, analyst_system_prompt

from .budget import LLMBudget, LLMBudgetExhausted
from .circuit_breaker import LLMCircuitBreaker, LLMCircuitOpen
from .llm import FallbackLLMClient, LLMInvalidResponseError, LLMProviderError, OpenAICompatibleLLMClient
from .market import fetch_public_snapshot
from .models import AnalystEvent, AnalystStatus, AnalystValidationError, validate_analyst_payload
from .news import build_news_snapshot
from .rl_evidence import abstain_envelope, load_rl_evidence
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
        rl_evidence_provider: Callable[[], dict[str, Any]] | None = None,
        circuit_breaker: LLMCircuitBreaker | None = None,
        timeframe_llm_clients: Mapping[str, OpenAICompatibleLLMClient] | None = None,
        manual_cache_secs: int = MANUAL_ANALYSIS_CACHE_SECS,
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
        self.rl_evidence_provider = rl_evidence_provider
        self.circuit_breaker = circuit_breaker or LLMCircuitBreaker()
        self.timeframe_llm_clients = dict(timeframe_llm_clients or {})
        self.manual_cache_secs = max(0, int(manual_cache_secs))

    def status(self) -> AnalystStatus:
        events = self.store.load_events(limit=self.event_limit)
        return AnalystStatus(
            enabled=self.enabled,
            events_count=len(events),
            budgets=self.budget.snapshot(),
            latest_event=events[-1] if events else None,
            circuits=self.circuit_breaker.snapshot(),
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

    def build_multi_agent_views(self, prompt_payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Run the existing background analyst roles for another planner.

        The execution planner owns the executable schema and confirmation gate;
        these roles remain directional/contextual and cannot emit an order.
        """
        return self._build_auxiliary_views(
            {key: value for key, value in prompt_payload.items() if key != "news_snapshot"}
        )

    def run_update(
        self,
        *,
        symbol: str = "ALL",
        market_snapshot: dict[str, Any] | None = None,
        scope: str = "interactive",
        analysis_mode: str | None = None,
    ) -> AnalystEvent:
        normalized_symbol = _normalize_symbol(symbol)
        normalized_scope = _normalize_llm_scope(scope)
        mode = str(analysis_mode or _default_analysis_mode(normalized_scope)).strip().lower()
        resolved_snapshot = market_snapshot if market_snapshot is not None else _safe_public_snapshot(normalized_symbol)
        prompt_payload = {
            "symbol": normalized_symbol,
            "analysis_mode": mode,
            "market_snapshot": resolved_snapshot,
            "task": (
                "Return the exact analyst JSON contract. Use only supplied evidence. "
                "Use BUY, SELL, REDUCE, HOLD, or AVOID and do not include quantities, leverage, "
                "order types, exchange commands, or target allocations."
            ),
        }
        return self._call_role(
            role="main_analyst",
            event_type="screening" if mode == "screening" else "scheduled_analysis" if mode == "scheduled" else "analysis",
            title=(
                f"{normalized_symbol} weak screening"
                if mode == "screening"
                else f"{normalized_symbol} scheduled analysis"
                if mode == "scheduled"
                else f"{normalized_symbol} analyst update"
            ),
            prompt_payload=prompt_payload,
            scope=normalized_scope,
            event_id=f"screening-{normalized_symbol}" if mode == "screening" else None,
        )

    def run_timeframe_update(
        self,
        *,
        symbol: str,
        timeframe: str,
        candle_close_ms: int,
        market_snapshot: dict[str, Any],
        lower_timeframe_context: list[dict[str, Any]],
    ) -> AnalystEvent:
        """Analyze one confirmed candle with only compact lower-timeframe evidence."""
        lane = _normalize_timeframe(timeframe)
        scope = f"timeframe_{lane}"
        normalized_symbol = _normalize_symbol(symbol)
        return self._call_role(
            role="main_analyst",
            event_type=f"timeframe_{lane}",
            title=f"{normalized_symbol} {lane} closed-candle analysis",
            prompt_payload={
                "symbol": normalized_symbol,
                "analysis_mode": scope,
                "timeframe": lane,
                "candle_close_ms": int(candle_close_ms),
                "market_snapshot": market_snapshot,
                "lower_timeframe_context": lower_timeframe_context,
                "task": (
                    "Analyze this confirmed candle only. Use compact lower-timeframe evidence as context, "
                    "call out stale or missing context, and return the exact analyst JSON contract. "
                    "This is advisory evidence, never an executable order."
                ),
            },
            scope=scope,
            event_id=f"timeframe-{normalized_symbol}-{lane}-{int(candle_close_ms)}",
        )

    def ask(
        self,
        *,
        question: str,
        symbol: str = "ALL",
        scope: str = "interactive",
    ) -> AnalystEvent:
        normalized_symbol = _normalize_symbol(symbol)
        compact_context = self.fresh_timeframe_context(symbol=normalized_symbol)
        legacy_mode = not self.timeframe_llm_clients
        cached = self._cached_manual_answer(symbol=normalized_symbol, question=question, context=compact_context)
        if cached is not None:
            return cached
        prompt_payload = {
            "symbol": normalized_symbol,
            "analysis_mode": "manual",
            "question": str(question or "").strip(),
            "market_snapshot": _safe_public_snapshot(normalized_symbol) if legacy_mode else {},
            "timeframe_context": compact_context,
            "manual_context_fingerprint": _manual_context_fingerprint(question, compact_context),
            "task": (
                "Answer as a thorough decision-support analyst using the exact JSON contract. If the user "
                "explicitly asks for position advice, give a "
                "directional advisory view using BUY, SELL, REDUCE, HOLD, or AVOID based on the supplied "
                "fresh compact timeframe evidence. Do not default to HOLD merely because the answer is "
                "advisory; use HOLD only when the evidence is genuinely balanced or insufficient. If the "
                "question is not about market direction, recommendation may be HOLD while the rationale "
                "answers the question. Explain momentum, trend, both intraday and swing objectives, and "
                "two-way conditional scenarios. Include entry/TP/SL only as non-executable scenario levels "
                "traceable to supplied evidence. Do not include quantities, leverage, order types, exchange "
                "commands, or target allocations."
            ),
        }
        return self._call_role(
            role="main_analyst",
            event_type="chat_reply",
            title=f"{normalized_symbol} analyst answer",
            prompt_payload=prompt_payload,
            scope="interactive" if legacy_mode else "manual",
        )

    def fresh_timeframe_context(self, *, symbol: str, max_age_secs: int | None = None) -> list[dict[str, Any]]:
        """Return a small, expiry-bounded evidence fan-in for higher/manual lanes."""
        max_age = int(max_age_secs if max_age_secs is not None else ANALYST_TIMEFRAME_CONTEXT_TTL_SECS)
        now = datetime.now(timezone.utc)
        compact: list[dict[str, Any]] = []
        for event in reversed(self.store.load_events(limit=self.event_limit)):
            event_type = str(event.get("event_type", ""))
            if not event_type.startswith("timeframe_") or event.get("status") != "ok":
                continue
            if _normalize_symbol(str(event.get("symbol", "ALL"))) != symbol:
                continue
            created = _parse_event_time(event.get("created_at_utc"))
            if created is None or (now - created).total_seconds() > max_age:
                continue
            payload = event.get("payload", {}) if isinstance(event.get("payload"), dict) else {}
            compact.append({
                "id": event.get("id"), "timeframe": event_type.removeprefix("timeframe_"),
                "created_at_utc": event.get("created_at_utc"), "recommendation": event.get("recommendation"),
                "confidence": event.get("confidence"), "rationale": event.get("rationale", ""),
                "risk_notes": event.get("risk_notes", ""), "invalidation": event.get("invalidation", ""),
                "horizon_outlook": payload.get("horizon_outlook", []), "scenarios": payload.get("scenarios", []),
            })
        return compact[-12:]

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
        prompt_payload = {
            "symbol": normalized_symbol,
            "alert_id": alert_id,
            "related_alert": related or {},
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
        if snapshot.get("status") != "ok":
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
        market_snapshot = _safe_public_snapshot(normalized_symbol)
        return self._call_role(
            role="main_analyst",
            event_type="news_analysis",
            title=f"{normalized_symbol} news and market analysis",
            prompt_payload={
                "symbol": normalized_symbol,
                "alert_id": alert_id,
                "analysis_mode": "news",
                "market_snapshot": market_snapshot,
                "news_snapshot": snapshot,
                "task": (
                    "Analyze the supplied public headlines with the current market evidence using the exact "
                    "analyst JSON contract. Attribute claims, identify what needs primary-source verification, "
                    "explain likely intraday and swing implications, and state whether to wait before or reassess "
                    "after a catalyst. Do not treat a headline as confirmed fact."
                ),
            },
            scope="interactive",
        )

    def _call_role(
        self,
        *,
        role: str,
        event_type: str,
        title: str,
        prompt_payload: dict[str, Any],
        scope: str,
        event_id: str | None = None,
    ) -> AnalystEvent:
        normalized_scope = _normalize_llm_scope(scope)
        llm_client = self._llm_client_for_scope(normalized_scope)
        prompt_payload = {
            **prompt_payload,
            "scope": normalized_scope,
            "llm_model": getattr(llm_client, "model", ""),
            "rl_evidence": prompt_payload.get("rl_evidence", self._safe_rl_evidence()),
        }
        try:
            self.circuit_breaker.check(normalized_scope)
        except LLMCircuitOpen as exc:
            return self._cooldown_event(
                event_type=event_type,
                title=title,
                role=role,
                message=str(exc),
                prompt_payload=prompt_payload,
                event_id=event_id,
            )
        try:
            self.budget.reserve(normalized_scope)
            if role == "main_analyst" and normalized_scope == "interactive" and event_type in {"analysis", "chat_reply"}:
                prompt_payload["auxiliary_views"] = self._build_auxiliary_views(prompt_payload)
            raw = llm_client.chat_json(
                messages=[
                    {
                        "role": "system",
                        "content": analyst_system_prompt(role),
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
                event_id=event_id,
            )
        except (LLMProviderError, LLMInvalidResponseError) as exc:
            self.circuit_breaker.record_failure(normalized_scope, exc)
            status = "invalid_response" if isinstance(exc, LLMInvalidResponseError) else "error"
            return self._record_failure(
                event_type=event_type,
                title=title,
                role=role,
                status=status,
                error_code=type(exc).__name__,
                message=str(exc),
                prompt_payload=prompt_payload,
                event_id=event_id,
            )
        except AnalystValidationError as exc:
            self.circuit_breaker.record_failure(normalized_scope, exc)
            return self._record_failure(
                event_type=event_type,
                title=title,
                role=role,
                status="invalid_response",
                error_code="AnalystValidationError",
                message=str(exc),
                prompt_payload=prompt_payload,
                event_id=event_id,
            )

        self.circuit_breaker.record_success(normalized_scope)

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
                "rl_evidence": prompt_payload.get("rl_evidence", {}),
                "auxiliary_views": prompt_payload.get("auxiliary_views", []),
                "llm_scope": normalized_scope,
                "llm_model": getattr(llm_client, "model", ""),
                "prompt_version": ANALYST_PROMPT_VERSION,
                "chart_annotations": parsed["chart_annotations"],
                "horizon_outlook": parsed["horizon_outlook"],
                "scenarios": parsed["scenarios"],
                "catalyst_watch": parsed["catalyst_watch"],
                "timeframe": prompt_payload.get("timeframe", ""),
                "candle_close_ms": prompt_payload.get("candle_close_ms"),
                "lower_timeframe_context": prompt_payload.get("lower_timeframe_context", []),
                "timeframe_context": prompt_payload.get("timeframe_context", []),
                "manual_context_fingerprint": prompt_payload.get("manual_context_fingerprint", ""),
                **({"news_snapshot": prompt_payload["news_snapshot"]} if "news_snapshot" in prompt_payload else {}),
            },
            **({"id": event_id} if event_id else {}),
        )
        return self.store.append(event)

    def _build_auxiliary_views(self, prompt_payload: dict[str, Any]) -> list[dict[str, Any]]:
        views = []
        for role, task in (
            (
                "technical_analyst",
                "Assess only supplied OHLCV-derived market facts and identify technical bias, "
                "counter-evidence, invalidation, and data gaps without proposing an order.",
            ),
        ):
            try:
                self.circuit_breaker.check("screening")
                self.budget.reserve("screening")
                raw = self.background_llm_client.chat_json(
                    messages=[
                        {
                            "role": "system",
                            "content": analyst_system_prompt(role),
                        },
                        {"role": "user", "content": _json_prompt({**prompt_payload, "task": task, "auxiliary_role": role})},
                    ],
                )
                parsed = validate_analyst_payload(raw)
                self.circuit_breaker.record_success("screening")
                views.append(
                    {
                        "role": role,
                        "status": "ok",
                        "recommendation": parsed["recommendation"],
                        "confidence": parsed["confidence"],
                        "rationale": parsed["rationale"],
                        "risk_notes": parsed["risk_notes"],
                        "invalidation": parsed["invalidation"],
                        "chart_annotations": parsed["chart_annotations"],
                        "llm_model": getattr(self.background_llm_client, "model", ""),
                        "prompt_version": ANALYST_PROMPT_VERSION,
                    }
                )
            except LLMCircuitOpen as exc:
                views.append(
                    {
                        "role": role,
                        "status": "cooldown",
                        "error_code": type(exc).__name__,
                        "message": str(exc),
                        "llm_model": getattr(self.background_llm_client, "model", ""),
                    }
                )
            except LLMBudgetExhausted as exc:
                views.append(
                    {
                        "role": role,
                        "status": "unavailable",
                        "error_code": type(exc).__name__,
                        "message": str(exc),
                        "llm_model": getattr(self.background_llm_client, "model", ""),
                    }
                )
            except (LLMProviderError, LLMInvalidResponseError, AnalystValidationError) as exc:
                self.circuit_breaker.record_failure("screening", exc)
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
        event_id: str | None = None,
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
                "rl_evidence": prompt_payload.get("rl_evidence", {}),
            },
            **({"id": event_id} if event_id else {}),
        )
        return self.store.append(event)

    def _cooldown_event(
        self,
        *,
        event_type: str,
        title: str,
        role: str,
        message: str,
        prompt_payload: dict[str, Any],
        event_id: str | None = None,
    ) -> AnalystEvent:
        """Return cooldown state without writing another event or error report."""
        return AnalystEvent(
            event_type=event_type,
            status="cooldown",
            title=title,
            message=message,
            symbol=str(prompt_payload.get("symbol", "ALL")),
            role=role,
            error_code="LLMCircuitOpen",
            payload={
                "scope": _normalize_llm_scope(str(prompt_payload.get("scope", ""))),
                "symbol": prompt_payload.get("symbol", "ALL"),
                "llm_model": prompt_payload.get("llm_model", ""),
            },
            **({"id": event_id} if event_id else {}),
        )

    def _llm_client_for_scope(self, scope: str) -> OpenAICompatibleLLMClient:
        normalized = _normalize_llm_scope(scope)
        if normalized in self.timeframe_llm_clients:
            return self.timeframe_llm_clients[normalized]
        if normalized == "screening":
            return self.background_llm_client
        return self.interactive_llm_client

    def _cached_manual_answer(self, *, symbol: str, question: str, context: list[dict[str, Any]]) -> AnalystEvent | None:
        if self.manual_cache_secs <= 0 or not str(question).strip():
            return None
        fingerprint = _manual_context_fingerprint(question, context)
        now = datetime.now(timezone.utc)
        for event in reversed(self.store.load_events(limit=self.event_limit)):
            if event.get("event_type") != "chat_reply" or event.get("status") != "ok":
                continue
            if _normalize_symbol(str(event.get("symbol", "ALL"))) != symbol:
                continue
            payload = event.get("payload", {}) if isinstance(event.get("payload"), dict) else {}
            if payload.get("manual_context_fingerprint") != fingerprint:
                continue
            created = _parse_event_time(event.get("created_at_utc"))
            if created and (now - created).total_seconds() <= self.manual_cache_secs:
                return AnalystEvent(**{key: event.get(key) for key in AnalystEvent.__dataclass_fields__})
        return None

    def _safe_rl_evidence(self) -> dict[str, Any]:
        try:
            if self.rl_evidence_provider is not None:
                return self.rl_evidence_provider()
            return load_rl_evidence(
                ANALYST_RL_EVIDENCE_PATH,
                max_age_secs=ANALYST_RL_EVIDENCE_MAX_AGE_SECS,
            )
        except Exception as exc:
            return abstain_envelope(["evidence_provider_error", type(exc).__name__]).to_dict()


def create_default_analyst_service() -> AnalystService:
    lower_base = LLM_LOWER_BASE_URL
    lower_key = LLM_LOWER_API_KEY
    lower_clients = {
        f"timeframe_{lane}": FallbackLLMClient(
            OpenAICompatibleLLMClient(
            base_url=lower_base,
            api_key=lower_key,
            model=model,
            model_config_name=f"LLM_{label}_MODEL",
            base_url_config_name="LLM_LOWER_BASE_URL",
            api_key_config_name="LLM_LOWER_API_KEY",
            timeout_secs=LLM_WEAK_TIMEOUT_SECS or LLM_TIMEOUT_SECS,
            use_response_format=LLM_USE_RESPONSE_FORMAT,
            ),
            OpenAICompatibleLLMClient(
                base_url=lower_base, api_key=LLM_LOWER_FALLBACK_API_KEY, model=model,
                model_config_name=f"LLM_{label}_MODEL fallback", base_url_config_name="LLM_LOWER_BASE_URL",
                api_key_config_name="LLM_LOWER_FALLBACK_API_KEY", timeout_secs=LLM_WEAK_TIMEOUT_SECS or LLM_TIMEOUT_SECS,
                use_response_format=LLM_USE_RESPONSE_FORMAT,
            ) if LLM_LOWER_FALLBACK_API_KEY else None,
        )
        for lane, label, model in (("1m", "1_MIN", LLM_1_MIN_MODEL), ("15m", "15_MIN", LLM_15_MIN_MODEL), ("1h", "1_HOUR", LLM_1_HOUR_MODEL))
    }
    lower_clients["timeframe_4h"] = OpenAICompatibleLLMClient(
        base_url=LLM_BASE_URL, api_key=LLM_API_KEY, model=LLM_4_HOUR_MODEL,
        model_config_name="LLM_4_HOUR_MODEL", timeout_secs=LLM_STRONG_TIMEOUT_SECS or LLM_TIMEOUT_SECS,
        use_response_format=LLM_USE_RESPONSE_FORMAT,
    )
    lower_clients["manual"] = OpenAICompatibleLLMClient(
        base_url=LLM_BASE_URL, api_key=LLM_API_KEY, model=MANUAL_MODEL,
        model_config_name="MANUAL_MODEL", timeout_secs=LLM_STRONG_TIMEOUT_SECS or LLM_TIMEOUT_SECS,
        use_response_format=LLM_USE_RESPONSE_FORMAT,
    )
    return AnalystService(
        interactive_llm_client=OpenAICompatibleLLMClient(
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY,
            model=LLM_INTERACTIVE_MODEL,
            model_config_name="LLM_STRONG_MODEL or LLM_INTERACTIVE_MODEL",
            timeout_secs=LLM_STRONG_TIMEOUT_SECS or LLM_TIMEOUT_SECS,
            use_response_format=LLM_USE_RESPONSE_FORMAT,
        ),
        background_llm_client=OpenAICompatibleLLMClient(
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY,
            model=LLM_BACKGROUND_MODEL,
            model_config_name="LLM_WEAK_MODEL or LLM_BACKGROUND_MODEL",
            timeout_secs=LLM_WEAK_TIMEOUT_SECS or LLM_TIMEOUT_SECS,
            use_response_format=LLM_USE_RESPONSE_FORMAT,
        ),
        budget=LLMBudget(
            background_daily_limit=LLM_SCREENING_CALL_BUDGET,
            scheduled_daily_limit=LLM_SCHEDULED_CALL_BUDGET,
            interactive_daily_limit=LLM_INTERACTIVE_CALL_BUDGET,
            tz_name=LIVE_SESSION_TIMEZONE,
            scope_limits={
                "timeframe_1m": LLM_1_MIN_CALL_BUDGET,
                "timeframe_15m": LLM_15_MIN_CALL_BUDGET,
                "timeframe_1h": LLM_1_HOUR_CALL_BUDGET,
                "timeframe_4h": LLM_4_HOUR_CALL_BUDGET,
                "manual": LLM_MANUAL_CALL_BUDGET,
            },
        ),
        store=AnalystEventStore(
            results_dir=RESULTS_DIR,
            reports_dir=REPORTS_DIR,
            tz_name=LIVE_SESSION_TIMEZONE,
            database_path=OPERATIONAL_DATABASE_PATH,
        ),
        enabled=ANALYST_ENABLED,
        event_limit=ANALYST_EVENT_LIMIT,
        circuit_breaker=LLMCircuitBreaker(
            failure_threshold=LLM_FAILURE_THRESHOLD,
            cooldown_secs=LLM_FAILURE_COOLDOWN_SECS,
        ),
        timeframe_llm_clients=lower_clients,
    )


def _normalize_symbol(symbol: str) -> str:
    value = str(symbol or "ALL").strip().upper()
    if value in {"ALL", "BTC", "ETH"}:
        return value
    if value in SYMBOLS:
        return value
    return "ALL"


def _normalize_timeframe(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in {"1m", "15m", "1h", "4h"}:
        raise ValueError("timeframe must be 1m, 15m, 1h, or 4h.")
    return normalized


def _parse_event_time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _manual_context_fingerprint(question: str, context: list[dict[str, Any]]) -> str:
    import hashlib
    import json

    source = {"question": str(question).strip().lower(), "evidence": [item.get("id") for item in context]}
    return hashlib.sha256(json.dumps(source, sort_keys=True).encode("utf-8")).hexdigest()[:24]


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
    normalized = str(scope or "").strip().lower()
    if normalized in {"background", "screening"}:
        return "screening"
    if normalized == "scheduled":
        return "scheduled"
    if normalized == "manual":
        return "manual"
    if normalized.startswith("timeframe_"):
        return normalized
    return "interactive"


def _default_analysis_mode(scope: str) -> str:
    if scope == "screening":
        return "screening"
    if scope == "scheduled":
        return "scheduled"
    return "manual"


def _public_event(row: dict[str, Any]) -> dict[str, Any]:
    blocked = {"api_key", "secret", "token", "authorization", "private_balances", "exchange_credentials"}
    payload = row.get("payload", {})
    if isinstance(payload, dict):
        row = dict(row)
        row["payload"] = {key: value for key, value in payload.items() if str(key).lower() not in blocked}
    return row
