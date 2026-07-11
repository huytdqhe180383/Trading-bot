"""Daily LLM call budgeting for analyst-only workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo


class LLMBudgetExhausted(RuntimeError):
    """Raised when an LLM call would exceed the configured budget."""


@dataclass
class LLMBudget:
    background_daily_limit: int
    interactive_daily_limit: int
    tz_name: str = "UTC"
    now_func: Callable[[], datetime] | None = None
    _used_by_day: dict[str, dict[str, int]] = field(default_factory=dict)

    def reserve(self, scope: str) -> None:
        normalized = _normalize_scope(scope)
        day = self._today_key()
        used = self._used_by_day.setdefault(day, {"background": 0, "interactive": 0})
        limit = self._limit_for(normalized)
        if used[normalized] >= limit:
            raise LLMBudgetExhausted(f"{normalized} LLM budget exhausted for {day}.")
        used[normalized] += 1

    def snapshot(self) -> dict[str, int | str]:
        day = self._today_key()
        used = self._used_by_day.setdefault(day, {"background": 0, "interactive": 0})
        return {
            "day": day,
            "background_used": int(used["background"]),
            "background_limit": int(self.background_daily_limit),
            "interactive_used": int(used["interactive"]),
            "interactive_limit": int(self.interactive_daily_limit),
        }

    def _limit_for(self, scope: str) -> int:
        if scope == "background":
            return max(0, int(self.background_daily_limit))
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
    if normalized not in {"background", "interactive"}:
        raise ValueError("scope must be background or interactive.")
    return normalized
