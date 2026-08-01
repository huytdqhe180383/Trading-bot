"""Polling scanner for analyst-only alerts."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable

from config import (
    ANALYST_SIGNIFICANT_CONFIDENCE,
    ANALYST_STRONG_ANALYSIS_CADENCE,
    ANALYST_WEAK_SCREEN_INTERVAL_SECS,
    SYMBOLS,
)

from .market import fetch_public_snapshot, fetch_screening_snapshot
from .discord_bot import DiscordNotifier, load_discord_config_from_env
from .service import AnalystService, create_default_analyst_service


@dataclass
class AnalystScanner:
    service: AnalystService
    symbols: Iterable[str] = field(default_factory=lambda: tuple(SYMBOLS))
    scan_interval_secs: int = ANALYST_WEAK_SCREEN_INTERVAL_SECS
    background_analysis_cadence: str = ANALYST_STRONG_ANALYSIS_CADENCE
    notifier: DiscordNotifier | None = None
    _last_analysis_key: str = ""
    last_screening_completed_at: str = ""
    last_screening_results: list[dict] = field(default_factory=list)
    screening_stage_by_symbol: dict[str, str] = field(default_factory=dict)
    last_scheduled_completed_at: str = ""
    last_scheduled_results: list[dict] = field(default_factory=list)

    def run_once(self) -> list[dict]:
        events = self.run_screening_once()
        analysis_key = _cadence_key(datetime.now(timezone.utc), self.background_analysis_cadence)
        run_scheduled_analysis = analysis_key != self._last_analysis_key
        if run_scheduled_analysis:
            events.extend(self.run_scheduled_once())
            self._last_analysis_key = analysis_key
        return events

    def run_screening_once(self) -> list[dict]:
        results = self._run_parallel(self._screen_symbol)
        self.last_screening_results = results
        self.last_screening_completed_at = datetime.now(timezone.utc).isoformat()
        return results

    def run_scheduled_once(self) -> list[dict]:
        results = self._run_parallel(self._analyze_symbol)
        self.last_scheduled_results = results
        self.last_scheduled_completed_at = datetime.now(timezone.utc).isoformat()
        return results

    def _run_parallel(self, worker: Callable[[str], dict]) -> list[dict]:
        symbols = tuple(self.symbols)
        if not symbols:
            return []
        with ThreadPoolExecutor(max_workers=len(symbols), thread_name_prefix="analyst") as executor:
            return list(executor.map(worker, symbols))

    def _screen_symbol(self, symbol: str) -> dict:
        try:
            self.screening_stage_by_symbol[symbol] = "fetching_market"
            snapshot = fetch_screening_snapshot(symbol)
            risk_event = _risk_trigger(snapshot)
            self.screening_stage_by_symbol[symbol] = "calling_weak_llm"
            event = self.service.run_update(
                symbol=symbol,
                market_snapshot={**snapshot, "trigger": risk_event} if risk_event else snapshot,
                scope="screening",
                analysis_mode="screening",
            )
            if risk_event:
                self._notify_if_significant(event, trigger=risk_event)
            self.screening_stage_by_symbol[symbol] = "completed"
            return event.to_public_dict()
        except Exception as exc:
            self.screening_stage_by_symbol[symbol] = f"error:{type(exc).__name__}"
            return {"status": "error", "symbol": symbol, "stage": "screening", "error": str(exc)}

    def _analyze_symbol(self, symbol: str) -> dict:
        try:
            snapshot = fetch_public_snapshot(symbol)
            event = self.service.run_update(
                symbol=symbol,
                market_snapshot=snapshot,
                scope="scheduled",
                analysis_mode="scheduled",
            )
            self._notify_if_significant(event)
            return event.to_public_dict()
        except Exception as exc:
            return {"status": "error", "symbol": symbol, "stage": "scheduled", "error": str(exc)}

    def run_forever(self, *, max_cycles: int = 0) -> None:
        cycle = 0
        while True:
            cycle += 1
            self.run_once()
            if max_cycles and cycle >= max_cycles:
                return
            time.sleep(max(1, int(self.scan_interval_secs)))

    def _notify_if_significant(self, event: object, *, trigger: str = "") -> None:
        if self.notifier is None or not _is_significant(event, trigger=trigger):
            return
        try:
            self.notifier.send_event(event)
        except Exception:
            return


def create_default_scanner(*, service: AnalystService | None = None) -> AnalystScanner:
    notifier = DiscordNotifier(config=load_discord_config_from_env())
    return AnalystScanner(
        service=service or create_default_analyst_service(),
        notifier=notifier if notifier.enabled() else None,
    )


def _risk_trigger(snapshot: dict) -> str:
    fifteen = snapshot.get("fifteen_minute", {})
    one_hour = snapshot.get("one_hour", {})
    if float(fifteen.get("window_return_pct", 0.0)) <= -2.0:
        return "15m_drop"
    if float(one_hour.get("window_return_pct", 0.0)) <= -3.0:
        return "1h_drop"
    return ""


def _is_significant(event: object, *, trigger: str = "") -> bool:
    if trigger:
        return True
    recommendation = str(getattr(event, "recommendation", "")).upper()
    confidence = getattr(event, "confidence", None)
    try:
        return recommendation in {"BUY", "SELL", "REDUCE"} and float(confidence) >= ANALYST_SIGNIFICANT_CONFIDENCE
    except (TypeError, ValueError):
        return False


def _cadence_key(now: datetime, cadence: str) -> str:
    value = str(cadence or "5m").strip().lower()
    try:
        if value.endswith("m"):
            minutes = max(1, int(value[:-1]))
            total_minutes = now.hour * 60 + now.minute
            bucket = (total_minutes // minutes) * minutes
            return f"{now:%Y-%m-%d}T{bucket // 60:02d}:{bucket % 60:02d}"
        if value.endswith("h"):
            hours = max(1, int(value[:-1]))
            bucket_hour = (now.hour // hours) * hours
            return f"{now:%Y-%m-%d}T{bucket_hour:02d}"
        if value.endswith("d"):
            return now.strftime("%Y-%m-%d")
    except ValueError:
        pass
    return now.strftime("%Y-%m-%dT%H:%M")
