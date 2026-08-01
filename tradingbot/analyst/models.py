"""Shared analyst-only schemas and validation."""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

ALLOWED_RECOMMENDATIONS = {"BUY", "SELL", "REDUCE", "HOLD", "AVOID"}
FORBIDDEN_OUTPUT_KEYS = {
    "allocation",
    "amount",
    "exchange_command",
    "leverage",
    "order",
    "order_id",
    "position_size",
    "quantity",
    "qty",
    "size",
    "target_allocation",
    "target_weight",
    "target_weights",
    "weights",
}
FORBIDDEN_TEXT_PATTERNS = (
    re.compile(r"\b\d+(\.\d+)?\s*x\s+leverage\b", re.IGNORECASE),
    re.compile(r"\bmarket\s+order\b", re.IGNORECASE),
    re.compile(r"\blimit\s+order\b", re.IGNORECASE),
    re.compile(r"\bquantity\s*[:=]", re.IGNORECASE),
)


class AnalystValidationError(ValueError):
    """Raised when an LLM response is not safe analyst-only output."""


@dataclass
class AnalystEvent:
    event_type: str
    status: str
    title: str
    message: str
    symbol: str = "ALL"
    role: str = "system"
    recommendation: str | None = None
    confidence: float | None = None
    rationale: str = ""
    risk_notes: str = ""
    invalidation: str = ""
    error_code: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_public_dict(self) -> dict[str, Any]:
        data = self.to_dict()
        data["payload"] = _sanitize_public_payload(data.get("payload", {}))
        return data


@dataclass
class AnalystStatus:
    enabled: bool
    events_count: int
    budgets: dict[str, Any]
    latest_event: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_analyst_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate strict analyst output without inventing a replacement decision."""
    if not isinstance(raw, dict):
        raise AnalystValidationError("LLM response must be a JSON object.")

    forbidden_key = _find_forbidden_key(raw)
    if forbidden_key:
        raise AnalystValidationError(f"Forbidden executable field: {forbidden_key}")

    recommendation = str(raw.get("recommendation", "")).strip().upper()
    if recommendation not in ALLOWED_RECOMMENDATIONS:
        raise AnalystValidationError("Missing or unsupported recommendation.")

    for key in ("rationale", "risk_notes", "invalidation"):
        value = str(raw.get(key, ""))
        if _contains_forbidden_text(value):
            raise AnalystValidationError(f"Executable trading language in {key}.")

    confidence = raw.get("confidence", None)
    if confidence is not None:
        try:
            confidence = float(confidence)
        except Exception as exc:
            raise AnalystValidationError("confidence must be numeric.") from exc
        if confidence > 1.0:
            confidence = confidence / 100.0
        if confidence < 0.0 or confidence > 1.0:
            raise AnalystValidationError("confidence must be between 0 and 1.")
    chart_annotations = _validate_chart_annotations(raw.get("chart_annotations", []))
    horizon_outlook = _validate_horizon_outlook(raw.get("horizon_outlook", []))
    scenarios = _validate_scenarios(raw.get("scenarios", []))
    catalyst_watch = _validate_catalyst_watch(raw.get("catalyst_watch", []))

    return {
        "recommendation": recommendation,
        "confidence": confidence,
        "rationale": str(raw.get("rationale", "")).strip(),
        "risk_notes": str(raw.get("risk_notes", "")).strip(),
        "invalidation": str(raw.get("invalidation", "")).strip(),
        "chart_annotations": chart_annotations,
        "horizon_outlook": horizon_outlook,
        "scenarios": scenarios,
        "catalyst_watch": catalyst_watch,
    }


def _validate_horizon_outlook(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 2:
        raise AnalystValidationError("horizon_outlook must contain at most intraday and swing views.")
    validated = []
    for item in raw:
        if not isinstance(item, dict):
            raise AnalystValidationError("Each horizon outlook must be an object.")
        horizon = str(item.get("horizon", "")).strip().upper()
        bias = str(item.get("bias", "")).strip().upper()
        momentum = str(item.get("momentum", "")).strip().upper()
        if horizon not in {"INTRADAY", "SWING"}:
            raise AnalystValidationError("horizon_outlook horizon must be INTRADAY or SWING.")
        if bias not in {"BULLISH", "BEARISH", "NEUTRAL", "MIXED", "UNKNOWN"}:
            raise AnalystValidationError("Unsupported horizon_outlook bias.")
        if momentum not in {"ACCELERATING", "STEADY", "WEAKENING", "REVERSING", "MIXED", "UNKNOWN"}:
            raise AnalystValidationError("Unsupported horizon_outlook momentum.")
        timeframes = item.get("timeframes", [])
        if not isinstance(timeframes, list) or len(timeframes) > 5:
            raise AnalystValidationError("horizon_outlook timeframes must be a list of at most five items.")
        watch_for = item.get("watch_for", [])
        if not isinstance(watch_for, list) or len(watch_for) > 5:
            raise AnalystValidationError("horizon_outlook watch_for must be a list of at most five items.")
        validated.append(
            {
                "horizon": horizon,
                "timeframes": [str(value).strip() for value in timeframes if str(value).strip()],
                "bias": bias,
                "momentum": momentum,
                "objective": str(item.get("objective", "")).strip(),
                "watch_for": [str(value).strip() for value in watch_for if str(value).strip()],
            }
        )
    return validated


def _validate_scenarios(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 3:
        raise AnalystValidationError("scenarios must be a list of at most three items.")
    validated = []
    for item in raw:
        if not isinstance(item, dict):
            raise AnalystValidationError("Each scenario must be an object.")
        direction = str(item.get("direction", "")).strip().upper()
        if direction not in {"BULLISH", "BEARISH", "NEUTRAL"}:
            raise AnalystValidationError("Unsupported scenario direction.")
        take_profit = item.get("take_profit", [])
        if not isinstance(take_profit, list) or len(take_profit) > 3:
            raise AnalystValidationError("scenario take_profit must be a list of at most three prices.")
        entry_zone_low = _optional_positive_number(item.get("entry_zone_low"), field="entry_zone_low")
        entry_zone_high = _optional_positive_number(item.get("entry_zone_high"), field="entry_zone_high")
        if entry_zone_low is not None and entry_zone_high is not None and entry_zone_low > entry_zone_high:
            raise AnalystValidationError("scenario entry_zone_low cannot exceed entry_zone_high.")
        validated.append(
            {
                "name": str(item.get("name", "")).strip()[:80],
                "direction": direction,
                "condition": str(item.get("condition", "")).strip(),
                "confirmation_timeframe": str(item.get("confirmation_timeframe", "")).strip() or None,
                "entry_zone_low": entry_zone_low,
                "entry_zone_high": entry_zone_high,
                "take_profit": [_positive_finite_number(value, field="take_profit") for value in take_profit],
                "stop_loss": _optional_positive_number(item.get("stop_loss"), field="stop_loss"),
                "plan": str(item.get("plan", "")).strip(),
            }
        )
    return validated


def _validate_catalyst_watch(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 5:
        raise AnalystValidationError("catalyst_watch must be a list of at most five items.")
    validated = []
    for item in raw:
        if not isinstance(item, dict):
            raise AnalystValidationError("Each catalyst watch item must be an object.")
        action = str(item.get("action", "")).strip().upper()
        if action not in {"WAIT_BEFORE", "MONITOR_AFTER", "NONE"}:
            raise AnalystValidationError("Unsupported catalyst watch action.")
        validated.append(
            {
                "event": str(item.get("event", "")).strip(),
                "timing": str(item.get("timing", "")).strip(),
                "action": action,
                "condition": str(item.get("condition", "")).strip(),
            }
        )
    return validated


def _validate_chart_annotations(raw: Any) -> list[dict[str, Any]]:
    """Accept a small non-executable annotation set for the public chart."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 6:
        raise AnalystValidationError("chart_annotations must be a list with at most six entries.")
    validated: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise AnalystValidationError("Each chart annotation must be an object.")
        kind = str(item.get("kind", "")).strip().lower()
        label = str(item.get("label", "")).strip()[:80]
        if kind not in {"support", "resistance", "trend"} or not label:
            raise AnalystValidationError("Chart annotations need a supported kind and label.")
        if kind in {"support", "resistance"}:
            price = _positive_finite_number(item.get("price"), field="chart annotation price")
            validated.append({"kind": kind, "price": price, "label": label})
            continue
        start_price = _positive_finite_number(item.get("start_price"), field="trend start_price")
        end_price = _positive_finite_number(item.get("end_price"), field="trend end_price")
        start_time = str(item.get("start_time", "")).strip()
        end_time = str(item.get("end_time", "")).strip()
        if not start_time or not end_time:
            raise AnalystValidationError("Trend annotations require start_time and end_time.")
        validated.append(
            {
                "kind": kind,
                "label": label,
                "start_price": start_price,
                "end_price": end_price,
                "start_time": start_time,
                "end_time": end_time,
            }
        )
    return validated


def _positive_finite_number(value: Any, *, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise AnalystValidationError(f"{field} must be numeric.") from exc
    if number <= 0.0 or number == float("inf") or number != number:
        raise AnalystValidationError(f"{field} must be a positive finite number.")
    return number


def _optional_positive_number(value: Any, *, field: str) -> float | None:
    if value is None or value == "":
        return None
    return _positive_finite_number(value, field=field)


def _find_forbidden_key(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in FORBIDDEN_OUTPUT_KEYS:
                return normalized
            found = _find_forbidden_key(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_forbidden_key(child)
            if found:
                return found
    return None


def _contains_forbidden_text(value: str) -> bool:
    return any(pattern.search(value) for pattern in FORBIDDEN_TEXT_PATTERNS)


def _sanitize_public_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    blocked = {"api_key", "secret", "token", "authorization", "private_balances", "exchange_credentials"}
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        if str(key).strip().lower() in blocked:
            continue
        if isinstance(value, dict):
            sanitized[key] = _sanitize_public_payload(value)
        elif isinstance(value, list):
            sanitized[key] = [
                _sanitize_public_payload(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            sanitized[key] = value
    return sanitized
