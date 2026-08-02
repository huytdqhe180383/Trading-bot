"""Compatibility facade for the candle-bound timeframe orchestrator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from config import ANALYST_TIMEFRAME_POLL_SECS, ANALYST_STRONG_ANALYSIS_CADENCE, SYMBOLS

from .discord_bot import DiscordNotifier, load_discord_config_from_env
from .service import AnalystService, create_default_analyst_service
from .timeframes import TimeframeAnalysisOrchestrator
from .market import fetch_public_snapshot, fetch_screening_snapshot


def _is_significant(event: object, *, trigger: str = "") -> bool:
    if str(getattr(event, "status", "")).lower() != "ok":
        return False
    if trigger:
        return True
    try:
        return str(getattr(event, "recommendation", "")).upper() in {"BUY", "SELL", "REDUCE"} and float(
            getattr(event, "confidence", 0)
        ) >= 0.65
    except (TypeError, ValueError):
        return False


def _cadence_key(now, cadence: str) -> str:
    """Legacy helper retained for callers; scheduling no longer uses it."""
    value = str(cadence or "15m").strip().lower()
    if value.endswith("m"):
        minutes = max(1, int(value[:-1]))
        bucket = (now.hour * 60 + now.minute) // minutes * minutes
        return f"{now:%Y-%m-%d}T{bucket // 60:02d}:{bucket % 60:02d}"
    if value.endswith("h"):
        hours = max(1, int(value[:-1]))
        return f"{now:%Y-%m-%d}T{now.hour // hours * hours:02d}"
    return now.strftime("%Y-%m-%d")


@dataclass
class AnalystScanner:
    """One poller, four candle-aligned lanes; old methods remain aliases."""

    service: AnalystService
    symbols: Iterable[str] = field(default_factory=lambda: tuple(SYMBOLS))
    scan_interval_secs: int = ANALYST_TIMEFRAME_POLL_SECS
    background_analysis_cadence: str = ANALYST_STRONG_ANALYSIS_CADENCE
    notifier: DiscordNotifier | None = None
    _orchestrator: TimeframeAnalysisOrchestrator = field(init=False)
    _last_analysis_key: str = field(default="", init=False)

    def __post_init__(self) -> None:
        self._orchestrator = TimeframeAnalysisOrchestrator(
            service=self.service, symbols=self.symbols, notifier=self.notifier
        )

    @property
    def last_screening_completed_at(self) -> str:
        return self._orchestrator.last_completed_at

    @property
    def last_screening_results(self) -> list[dict]:
        return self._orchestrator.last_results

    @property
    def screening_stage_by_symbol(self) -> dict[str, str]:
        return self._orchestrator.stage_by_symbol

    def run_once(self) -> list[dict]:
        if not hasattr(self.service, "run_timeframe_update"):
            return self._run_legacy_once()
        return self._orchestrator.run_due_once()

    def run_screening_once(self) -> list[dict]:
        return self.run_once()

    def run_scheduled_once(self) -> list[dict]:
        return self.run_once()

    def _run_legacy_once(self) -> list[dict]:
        results: list[dict] = []
        for symbol in tuple(self.symbols):
            event = self.service.run_update(symbol=symbol, market_snapshot=fetch_screening_snapshot(symbol), scope="screening", analysis_mode="screening")
            results.append(event.to_public_dict())
        from datetime import datetime, timezone
        key = _cadence_key(datetime.now(timezone.utc), self.background_analysis_cadence)
        if key != self._last_analysis_key:
            for symbol in tuple(self.symbols):
                event = self.service.run_update(symbol=symbol, market_snapshot=fetch_public_snapshot(symbol), scope="scheduled", analysis_mode="scheduled")
                results.append(event.to_public_dict())
            self._last_analysis_key = key
        return results


def create_default_scanner(*, service: AnalystService | None = None) -> AnalystScanner:
    notifier = DiscordNotifier(config=load_discord_config_from_env())
    return AnalystScanner(service=service or create_default_analyst_service(), notifier=notifier)
