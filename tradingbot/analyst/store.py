"""Canonical analyst event storage."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import AnalystEvent


class AnalystEventStore:
    def __init__(self, *, results_dir: Path, reports_dir: Path, tz_name: str = "UTC") -> None:
        self.results_dir = Path(results_dir)
        self.reports_dir = Path(reports_dir)
        self.tz_name = tz_name

    def append(self, event: AnalystEvent) -> AnalystEvent:
        path = self._events_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event.to_dict(), ensure_ascii=True, sort_keys=True) + "\n")
        if event.status in {"error", "invalid_response", "budget_exhausted"}:
            self._append_error_report(event)
        return event

    def load_events(self, *, limit: int = 200) -> list[dict]:
        daily_root = self.results_dir / "daily"
        if not daily_root.exists():
            return []
        paths = sorted(daily_root.glob("*/analyst_events.jsonl"))
        events: list[dict] = []
        for path in paths:
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue
            for line in lines:
                try:
                    events.append(json.loads(line))
                except Exception:
                    continue
        events.sort(key=lambda row: str(row.get("created_at_utc", "")))
        return events[-max(1, int(limit)) :]

    def load_signals(self, *, limit: int = 200) -> list[dict]:
        return [
            event for event in self.load_events(limit=limit)
            if event.get("recommendation") and event.get("status") == "ok"
        ]

    def _events_path(self) -> Path:
        day = datetime.now(ZoneInfo(self.tz_name)).strftime("%Y-%m-%d")
        return self.results_dir / "daily" / day / "analyst_events.jsonl"

    def _append_error_report(self, event: AnalystEvent) -> None:
        day = datetime.now(ZoneInfo(self.tz_name)).strftime("%Y-%m-%d")
        path = self.reports_dir / "daily" / day / f"analyst_errors_{day}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        line = (
            f"- `{event.created_at_utc}` `{event.status}` `{event.error_code}` "
            f"{event.title}: {event.message}\n"
        )
        if not path.exists():
            path.write_text(f"# Analyst LLM Errors - {day}\n\n", encoding="utf-8")
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
