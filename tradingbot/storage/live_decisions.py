"""Queryable index for live decisions preserved as daily CSV artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .database import OperationalDatabase, default_database_path


class LiveDecisionStore:
    """Index live-decision artifacts without replacing those artifacts."""

    def __init__(self, *, results_dir: Path, database_path: Path | None = None) -> None:
        self.results_dir = Path(results_dir)
        self.database = OperationalDatabase(database_path or default_database_path(self.results_dir))

    def record(self, *, session_csv_path: Path, decision: dict[str, Any]) -> None:
        csv_path = Path(session_csv_path)
        session_dir = csv_path.parent
        timestamp = str(decision.get("timestamp_utc", ""))
        cycle = int(decision.get("cycle", 0) or 0)
        encoded = json.dumps(decision, default=str, ensure_ascii=True, sort_keys=True)
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO live_decisions (
                    session_dir, source_csv, timestamp_utc, cycle, status, row_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_dir, timestamp_utc, cycle) DO UPDATE SET
                    source_csv = excluded.source_csv,
                    status = excluded.status,
                    row_json = excluded.row_json
                """,
                (
                    str(session_dir),
                    str(csv_path),
                    timestamp,
                    cycle,
                    str(decision.get("status", "")),
                    encoded,
                ),
            )

    def load(self) -> list[dict[str, Any]]:
        self.import_csv_artifacts()
        with self.database.read() as connection:
            rows = connection.execute(
                """
                SELECT session_dir, source_csv, row_json
                FROM live_decisions
                ORDER BY timestamp_utc, id
                """
            ).fetchall()
        decisions: list[dict[str, Any]] = []
        for row in rows:
            decision = json.loads(row["row_json"])
            decision["session_dir"] = row["session_dir"]
            decision["source_csv"] = row["source_csv"]
            decisions.append(decision)
        return decisions

    def import_csv_artifacts(self) -> None:
        """Incrementally import legacy and externally produced live CSV files."""
        daily_root = self.results_dir / "daily"
        if not daily_root.exists():
            return
        for csv_path in sorted(daily_root.glob("*/*/live_trade_decisions_*.csv")):
            if not self.database.artifact_needs_import(csv_path):
                continue
            try:
                frame = pd.read_csv(csv_path)
            except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError):
                continue
            if frame.empty or "timestamp_utc" not in frame.columns:
                continue
            for decision in frame.to_dict(orient="records"):
                self.record(session_csv_path=csv_path, decision=decision)
            self.database.mark_artifact_imported(csv_path)
