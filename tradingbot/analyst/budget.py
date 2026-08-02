"""Daily LLM call budgeting for analyst-only workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
from typing import Callable, Mapping
from zoneinfo import ZoneInfo


class LLMBudgetExhausted(RuntimeError):
    """Raised when an LLM call would exceed the configured budget."""


@dataclass
class LLMBudget:
    background_daily_limit: int
    interactive_daily_limit: int
    scheduled_daily_limit: int | None = None
    scope_limits: Mapping[str, int] | None = None
    tz_name: str = "UTC"
    now_func: Callable[[], datetime] | None = None
    _used_by_day: dict[str, dict[str, int]] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def reserve(self, scope: str) -> None:
        normalized = _normalize_scope(scope)
        day = self._today_key()
        with self._lock:
            used = self._used_by_day.setdefault(day, {})
            used.setdefault(normalized, 0)
            limit = self._limit_for(normalized)
            if used[normalized] >= limit:
                raise LLMBudgetExhausted(f"{normalized} LLM budget exhausted for {day}.")
            used[normalized] += 1

    def snapshot(self) -> dict[str, int | str]:
        day = self._today_key()
        with self._lock:
            used = self._used_by_day.setdefault(day, {})
            for scope in ("screening", "scheduled", "interactive"):
                used.setdefault(scope, 0)
            screening_limit = int(self.background_daily_limit)
            scheduled_limit = int(self.scheduled_daily_limit if self.scheduled_daily_limit is not None else self.interactive_daily_limit)
            return {
                "day": day,
                "screening_used": int(used["screening"]),
                "screening_limit": screening_limit,
                "scheduled_used": int(used["scheduled"]),
                "scheduled_limit": scheduled_limit,
                "interactive_used": int(used["interactive"]),
                "interactive_limit": int(self.interactive_daily_limit),
                # Compatibility aliases for older clients.
                "background_used": int(used["screening"]),
                "background_limit": screening_limit,
                "timeframes": {
                    scope: {"used": int(used.get(scope, 0)), "limit": self._limit_for(scope)}
                    for scope in sorted((self.scope_limits or {}).keys())
                },
            }

    def _limit_for(self, scope: str) -> int:
        if self.scope_limits and scope in self.scope_limits:
            return max(0, int(self.scope_limits[scope]))
        if scope == "screening":
            return max(0, int(self.background_daily_limit))
        if scope == "scheduled":
            limit = self.scheduled_daily_limit if self.scheduled_daily_limit is not None else self.interactive_daily_limit
            return max(0, int(limit))
        return max(0, int(self.interactive_daily_limit))

    def _today_key(self) -> str:
        if self.now_func is not None:
            now = self.now_func()
        else:
            now = datetime.now(ZoneInfo(self.tz_name))
        if now.tzinfo is None:
            now = now.replace(tzinfo=ZoneInfo(self.tz_name))
        return now.astimezone(ZoneInfo(self.tz_name)).strftime("%Y-%m-%d")


def _normalize_scope(scope: str) -> str:
    normalized = str(scope or "interactive").strip().lower()
    if normalized == "background":
        return "screening"
    if normalized.startswith("timeframe_"):
        return normalized
    if normalized not in {"screening", "scheduled", "interactive", "manual"}:
        raise ValueError("scope must be screening, scheduled, interactive, manual, or timeframe_<interval>.")
    return normalized
