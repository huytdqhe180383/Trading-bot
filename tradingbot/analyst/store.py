"""Transactional analyst event storage with legacy JSONL import."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tradingbot.storage import OperationalDatabase, default_database_path

from .models import AnalystEvent


class AnalystEventStore:
    """Persist analyst events and expose the small query surface callers need."""

    def __init__(
        self,
        *,
        results_dir: Path,
        reports_dir: Path,
        tz_name: str = "UTC",
        database_path: Path | None = None,
    ) -> None:
        self.results_dir = Path(results_dir)
        self.reports_dir = Path(reports_dir)
        self.tz_name = tz_name
        self.database = OperationalDatabase(database_path or default_database_path(self.results_dir))

    def append(self, event: AnalystEvent) -> AnalystEvent:
        self._save(event.to_dict())
        if event.status in {"error", "invalid_response", "budget_exhausted"}:
            self._append_error_report(event)
        return event

    def load_events(self, *, limit: int = 200) -> list[dict]:
        self._import_legacy_events()
        with self.database.read() as connection:
            rows = connection.execute(
                """
                SELECT * FROM analyst_events
                ORDER BY created_at_utc DESC, id DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [self._row_to_event(row) for row in reversed(rows)]

    def load_signals(self, *, limit: int = 200) -> list[dict]:
        return [
            event for event in self.load_events(limit=limit)
            if event.get("recommendation") and event.get("status") == "ok"
        ]

    def _save(self, event: dict) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO analyst_events (
                    id, created_at_utc, event_type, status, symbol, role,
                    recommendation, confidence, title, message, rationale,
                    risk_notes, invalidation, error_code, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    created_at_utc = excluded.created_at_utc,
                    event_type = excluded.event_type,
                    status = excluded.status,
                    symbol = excluded.symbol,
                    role = excluded.role,
                    recommendation = excluded.recommendation,
                    confidence = excluded.confidence,
                    title = excluded.title,
                    message = excluded.message,
                    rationale = excluded.rationale,
                    risk_notes = excluded.risk_notes,
                    invalidation = excluded.invalidation,
                    error_code = excluded.error_code,
                    payload_json = excluded.payload_json
                """,
                (
                    str(event.get("id", "")),
                    str(event.get("created_at_utc", "")),
                    str(event.get("event_type", "")),
                    str(event.get("status", "")),
                    str(event.get("symbol", "ALL")),
                    str(event.get("role", "system")),
                    event.get("recommendation"),
                    event.get("confidence"),
                    str(event.get("title", "")),
                    str(event.get("message", "")),
                    str(event.get("rationale", "")),
                    str(event.get("risk_notes", "")),
                    str(event.get("invalidation", "")),
                    str(event.get("error_code", "")),
                    json.dumps(event.get("payload", {}), ensure_ascii=True, sort_keys=True),
                ),
            )

    def _import_legacy_events(self) -> None:
        daily_root = self.results_dir / "daily"
        if not daily_root.exists():
            return
        for path in sorted(daily_root.glob("*/analyst_events.jsonl")):
            if not self.database.artifact_needs_import(path):
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and event.get("id"):
                    self._save(event)
            self.database.mark_artifact_imported(path)

    @staticmethod
    def _row_to_event(row: object) -> dict:
        event = dict(row)
        event["payload"] = json.loads(event.pop("payload_json") or "{}")
        return event

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
