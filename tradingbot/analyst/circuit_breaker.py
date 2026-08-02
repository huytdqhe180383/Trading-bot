"""Thread-safe failure cooldowns for analyst LLM lanes."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from threading import Lock
from typing import Callable


class LLMCircuitOpen(RuntimeError):
    """Raised when a model lane is cooling down after repeated failures."""

    def __init__(self, *, scope: str, retry_after_secs: int) -> None:
        self.scope = scope
        self.retry_after_secs = max(1, int(retry_after_secs))
        super().__init__(
            f"{scope} LLM calls are paused after repeated failures; retry in "
            f"{self.retry_after_secs} seconds."
        )


@dataclass
class _CircuitState:
    consecutive_failures: int = 0
    opened_until: float = 0.0
    last_error_code: str = ""
    probe_in_flight: bool = False


class LLMCircuitBreaker:
    """Open an independent cooldown circuit for each LLM request scope."""

    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        cooldown_secs: float = 300.0,
        now_func: Callable[[], float] | None = None,
    ) -> None:
        self.failure_threshold = max(1, int(failure_threshold))
        self.cooldown_secs = max(1.0, float(cooldown_secs))
        self._now = now_func or time.monotonic
        self._states: dict[str, _CircuitState] = {}
        self._lock = Lock()

    def check(self, scope: str) -> None:
        """Allow a call or raise with the remaining cooldown."""
        normalized = _normalize_scope(scope)
        with self._lock:
            state = self._states.setdefault(normalized, _CircuitState())
            remaining = state.opened_until - self._now()
            if remaining > 0:
                raise LLMCircuitOpen(scope=normalized, retry_after_secs=math.ceil(remaining))
            if state.opened_until > 0:
                # Permit exactly one half-open probe after the cooldown. This
                # matters because BTC and ETH screening execute concurrently.
                state.opened_until = 0.0
                state.probe_in_flight = True
                return
            if state.probe_in_flight:
                raise LLMCircuitOpen(scope=normalized, retry_after_secs=1)

    def record_failure(self, scope: str, error: Exception) -> None:
        normalized = _normalize_scope(scope)
        with self._lock:
            state = self._states.setdefault(normalized, _CircuitState())
            state.consecutive_failures += 1
            state.last_error_code = type(error).__name__
            state.probe_in_flight = False
            if state.consecutive_failures >= self.failure_threshold:
                state.opened_until = self._now() + self.cooldown_secs

    def record_success(self, scope: str) -> None:
        normalized = _normalize_scope(scope)
        with self._lock:
            self._states[normalized] = _CircuitState()

    def snapshot(self) -> dict[str, dict[str, int | str]]:
        now = self._now()
        with self._lock:
            return {
                scope: {
                    "state": "open" if state.opened_until > now else "half_open" if state.probe_in_flight else "closed",
                    "consecutive_failures": state.consecutive_failures,
                    "retry_after_secs": max(0, math.ceil(state.opened_until - now)),
                    "last_error_code": state.last_error_code,
                }
                for scope, state in sorted(self._states.items())
            }


def _normalize_scope(scope: str) -> str:
    normalized = str(scope or "interactive").strip().lower()
    if normalized == "background":
        return "screening"
    return normalized
