"""Polling scanner for analyst-only alerts."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from config import (
    ANALYST_BACKGROUND_ANALYSIS_CADENCE,
    ANALYST_SCAN_INTERVAL_SECS,
    ANALYST_SIGNIFICANT_CONFIDENCE,
    SYMBOLS,
)

from .market import fetch_public_snapshot
from .discord_bot import DiscordNotifier, load_discord_config_from_env
from .service import AnalystService, create_default_analyst_service


@dataclass
class AnalystScanner:
    service: AnalystService
    symbols: Iterable[str] = field(default_factory=lambda: tuple(SYMBOLS))
    scan_interval_secs: int = ANALYST_SCAN_INTERVAL_SECS
    background_analysis_cadence: str = ANALYST_BACKGROUND_ANALYSIS_CADENCE
    notifier: DiscordNotifier | None = None
    _last_analysis_key: str = ""

    def run_once(self) -> list[dict]:
        events = []
        analysis_key = _cadence_key(datetime.now(timezone.utc), self.background_analysis_cadence)
        run_scheduled_analysis = analysis_key != self._last_analysis_key
        for symbol in self.symbols:
            snapshot = fetch_public_snapshot(symbol)
            risk_event = _risk_trigger(snapshot)
            if risk_event:
                event = self.service.run_update(
                    symbol=symbol,
                    market_snapshot={**snapshot, "trigger": risk_event},
                    scope="background",
                )
                self._notify_if_significant(event, trigger=risk_event)
                events.append(event.to_public_dict())
            elif run_scheduled_analysis:
                event = self.service.run_update(
                    symbol=symbol,
                    market_snapshot=snapshot,
                    scope="interactive",
                )
                self._notify_if_significant(event)
                events.append(event.to_public_dict())
        if run_scheduled_analysis:
            self._last_analysis_key = analysis_key
        return events

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


def create_default_scanner() -> AnalystScanner:
    notifier = DiscordNotifier(config=load_discord_config_from_env())
    return AnalystScanner(service=create_default_analyst_service(), notifier=notifier if notifier.enabled() else None)


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
        return recommendation in {"BUY", "SELL", "REDUCE", "AVOID"} and float(confidence) >= ANALYST_SIGNIFICANT_CONFIDENCE
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
