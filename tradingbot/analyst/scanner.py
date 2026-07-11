"""Polling scanner for analyst-only alerts."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from config import ANALYST_SCAN_INTERVAL_SECS, SYMBOLS

from .market import fetch_public_snapshot
from .discord_bot import DiscordNotifier, load_discord_config_from_env
from .service import AnalystService, create_default_analyst_service


@dataclass
class AnalystScanner:
    service: AnalystService
    symbols: Iterable[str] = field(default_factory=lambda: tuple(SYMBOLS))
    scan_interval_secs: int = ANALYST_SCAN_INTERVAL_SECS
    notifier: DiscordNotifier | None = None
    _last_hour_key: str = ""

    def run_once(self) -> list[dict]:
        events = []
        hour_key = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
        run_hourly_analysis = hour_key != self._last_hour_key
        for symbol in self.symbols:
            snapshot = fetch_public_snapshot(symbol)
            risk_event = _risk_trigger(snapshot)
            if risk_event:
                event = self.service.run_update(
                    symbol=symbol,
                    market_snapshot={**snapshot, "trigger": risk_event},
                    scope="background",
                )
                self._notify(event)
                events.append(event.to_public_dict())
            elif run_hourly_analysis:
                event = self.service.run_update(
                    symbol=symbol,
                    market_snapshot=snapshot,
                    scope="background",
                )
                self._notify(event)
                events.append(event.to_public_dict())
        if run_hourly_analysis:
            self._last_hour_key = hour_key
        return events

    def run_forever(self, *, max_cycles: int = 0) -> None:
        cycle = 0
        while True:
            cycle += 1
            self.run_once()
            if max_cycles and cycle >= max_cycles:
                return
            time.sleep(max(1, int(self.scan_interval_secs)))

    def _notify(self, event: object) -> None:
        if self.notifier is None:
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
