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

    return {
        "recommendation": recommendation,
        "confidence": confidence,
        "rationale": str(raw.get("rationale", "")).strip(),
        "risk_notes": str(raw.get("risk_notes", "")).strip(),
        "invalidation": str(raw.get("invalidation", "")).strip(),
    }


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
