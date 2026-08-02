"""Candle-bound, priority-aware analyst timeframe orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Event, Lock
from typing import Any, Iterable

from config import ANALYST_TIMEFRAME_CONTEXT_TTL_SECS, SYMBOLS

from .discord_bot import DiscordNotifier
from .market import fetch_timeframe_snapshot
from .service import AnalystService


@dataclass(frozen=True)
class TimeframeLane:
    name: str
    rank: int
    parents: tuple[str, ...]


LANES = (
    TimeframeLane("1m", 1, ()),
    TimeframeLane("15m", 2, ("1m",)),
    TimeframeLane("1h", 3, ("1m", "15m")),
    TimeframeLane("4h", 4, ("1m", "15m", "1h")),
)


@dataclass
class TimeframeAnalysisOrchestrator:
    service: AnalystService
    symbols: Iterable[str] = field(default_factory=lambda: tuple(SYMBOLS))
    notifier: DiscordNotifier | None = None
    context_ttl_secs: int = ANALYST_TIMEFRAME_CONTEXT_TTL_SECS
    _processed: set[str] = field(default_factory=set, init=False)
    _cancellations: dict[tuple[str, str], Event] = field(default_factory=dict, init=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)
    last_completed_at: str = ""
    last_results: list[dict[str, Any]] = field(default_factory=list)
    stage_by_symbol: dict[str, str] = field(default_factory=dict)

    def run_due_once(self) -> list[dict[str, Any]]:
        """Run all due lanes in priority order for confirmed candles.

        A higher lane cancels any lower lane for the same symbol at the next
        safe boundary.  Python cannot kill an in-flight HTTP request safely, so
        its late result is discarded rather than recorded or alerted.
        """
        results: list[dict[str, Any]] = []
        for symbol in tuple(self.symbols):
            due: list[tuple[TimeframeLane, dict[str, Any]]] = []
            for lane in LANES:
                try:
                    snapshot = fetch_timeframe_snapshot(symbol, interval=lane.name)
                    close = int(snapshot.get("last_closed_ms", 0))
                    key = self._event_key(symbol, lane.name, close)
                    if snapshot.get("status") == "ok" and close and not self._already_processed(key):
                        due.append((lane, snapshot))
                except Exception as exc:
                    results.append({"status": "error", "symbol": symbol, "stage": "fetch", "error": str(exc)})
            for lane, snapshot in sorted(due, key=lambda pair: pair[0].rank, reverse=True):
                results.append(self._run_lane(symbol, lane, snapshot))
        self.last_results = results
        self.last_completed_at = datetime.now(timezone.utc).isoformat()
        return results

    def _run_lane(self, symbol: str, lane: TimeframeLane, snapshot: dict[str, Any]) -> dict[str, Any]:
        close = int(snapshot["last_closed_ms"])
        key = self._event_key(symbol, lane.name, close)
        self._cancel_lower(symbol, lane.rank)
        token = Event()
        with self._lock:
            self._cancellations[(symbol, lane.name)] = token
        self.stage_by_symbol[symbol] = f"{lane.name}:building_context"
        if token.is_set():
            return self._cancelled(symbol, lane.name, close)
        lower = self._lower_context(symbol, lane)
        self.stage_by_symbol[symbol] = f"{lane.name}:calling_model"
        event = self.service.run_timeframe_update(
            symbol=symbol, timeframe=lane.name, candle_close_ms=close,
            market_snapshot=snapshot, lower_timeframe_context=lower,
        )
        if token.is_set():
            return self._cancelled(symbol, lane.name, close)
        with self._lock:
            self._processed.add(key)
        self.stage_by_symbol[symbol] = f"{lane.name}:completed"
        if self.notifier is not None and event.status == "ok":
            try:
                if lane.name == "4h":
                    self.notifier.send_analyst_event(event)
                elif lane.name in {"15m", "1h"} and _is_significant(event):
                    self.notifier.send_event(event)
            except Exception:
                pass
        return event.to_public_dict()

    def _lower_context(self, symbol: str, lane: TimeframeLane) -> list[dict[str, Any]]:
        all_context = self.service.fresh_timeframe_context(symbol=symbol, max_age_secs=self.context_ttl_secs)
        return [item for item in all_context if item.get("timeframe") in lane.parents][-8:]

    def _cancel_lower(self, symbol: str, rank: int) -> None:
        with self._lock:
            for lane in LANES:
                if lane.rank < rank:
                    token = self._cancellations.get((symbol, lane.name))
                    if token is not None:
                        token.set()

    def _already_processed(self, key: str) -> bool:
        if key in self._processed:
            return True
        return any(event.get("id") == key for event in self.service.store.load_events(limit=500))

    @staticmethod
    def _event_key(symbol: str, lane: str, close: int) -> str:
        return f"timeframe-{symbol.upper()}-{lane}-{close}"

    @staticmethod
    def _cancelled(symbol: str, lane: str, close: int) -> dict[str, Any]:
        return {"status": "cancelled", "symbol": symbol, "timeframe": lane, "last_closed_ms": close}


def _is_significant(event: object) -> bool:
    if str(getattr(event, "status", "")).lower() != "ok":
        return False
    try:
        return str(getattr(event, "recommendation", "")).upper() in {"BUY", "SELL", "REDUCE"} and float(
            getattr(event, "confidence", 0)
        ) >= 0.65
    except (TypeError, ValueError):
        return False
