"""Persistent, non-secret state for Discord-confirmed order suggestions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


class OrderSuggestionStore:
    def __init__(self, *, results_dir: Path, tz_name: str = "UTC") -> None:
        self.results_dir = Path(results_dir)
        self.tz_name = tz_name

    def create(self, record: dict[str, Any]) -> dict[str, Any]:
        return self._append(record)

    def get(self, suggestion_id: str) -> dict[str, Any] | None:
        latest = self._latest()
        record = latest.get(str(suggestion_id))
        return dict(record) if record else None

    def update(self, suggestion_id: str, **changes: Any) -> dict[str, Any] | None:
        current = self.get(suggestion_id)
        if current is None:
            return None
        current.update(changes)
        current["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        return self._append(current)

    def _append(self, record: dict[str, Any]) -> dict[str, Any]:
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")
        return dict(record)

    def _latest(self) -> dict[str, dict[str, Any]]:
        root = self.results_dir / "daily"
        if not root.exists():
            return {}
        latest: dict[str, dict[str, Any]] = {}
        for path in sorted(root.glob("*/order_suggestions.jsonl")):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict) and row.get("id"):
                    latest[str(row["id"])] = row
        return latest

    def _path(self) -> Path:
        day = datetime.now(timezone.utc).astimezone(ZoneInfo(self.tz_name)).strftime("%Y-%m-%d")
        return self.results_dir / "daily" / day / "order_suggestions.jsonl"
