"""Transactional state for Discord-confirmed order suggestions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.storage import OperationalDatabase, default_database_path


class OrderSuggestionStore:
    """Own suggestion lifecycle changes, including atomic confirmation claims."""

    def __init__(
        self,
        *,
        results_dir: Path,
        tz_name: str = "UTC",
        database_path: Path | None = None,
    ) -> None:
        self.results_dir = Path(results_dir)
        self.tz_name = tz_name
        self.database = OperationalDatabase(database_path or default_database_path(self.results_dir))

    def create(self, record: dict[str, Any]) -> dict[str, Any]:
        return self._save(record)

    def get(self, suggestion_id: str) -> dict[str, Any] | None:
        self._import_legacy_suggestions()
        with self.database.read() as connection:
            row = connection.execute(
                "SELECT record_json FROM order_suggestions WHERE id = ?",
                (str(suggestion_id),),
            ).fetchone()
        return json.loads(row["record_json"]) if row else None

    def update(self, suggestion_id: str, **changes: Any) -> dict[str, Any] | None:
        current = self.get(suggestion_id)
        if current is None:
            return None
        current.update(changes)
        current["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        return self._save(current)

    def claim_for_confirmation(self, suggestion_id: str, requested_by: str) -> dict[str, Any] | None:
        """Atomically change a pending suggestion to submitting.

        Returning ``None`` means another callback already claimed or closed it.
        """
        return self._transition_pending(
            suggestion_id=suggestion_id,
            requested_by=requested_by,
            next_status="submitting",
        )

    def reject(self, suggestion_id: str, requested_by: str) -> dict[str, Any] | None:
        """Reject a pending suggestion if no other callback has claimed it."""
        return self._transition_pending(
            suggestion_id=suggestion_id,
            requested_by=requested_by,
            next_status="rejected",
        )

    def expire(self, suggestion_id: str) -> dict[str, Any] | None:
        """Expire a pending suggestion without reopening a closed record."""
        return self._transition_pending(
            suggestion_id=suggestion_id,
            requested_by=None,
            next_status="expired",
        )

    def _transition_pending(
        self,
        *,
        suggestion_id: str,
        requested_by: str | None,
        next_status: str,
    ) -> dict[str, Any] | None:
        self._import_legacy_suggestions()
        now = datetime.now(timezone.utc).isoformat()
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT record_json FROM order_suggestions WHERE id = ?",
                (str(suggestion_id),),
            ).fetchone()
            if row is None:
                return None
            record = json.loads(row["record_json"])
            if record.get("status") != "pending":
                return None
            if requested_by is not None and str(record.get("requested_by", "")) != str(requested_by):
                return None
            record.update(status=next_status, updated_at_utc=now)
            encoded = json.dumps(record, ensure_ascii=True, sort_keys=True)
            if requested_by is None:
                changed = connection.execute(
                    """
                    UPDATE order_suggestions
                    SET status = ?, updated_at_utc = ?, record_json = ?
                    WHERE id = ? AND status = 'pending'
                    """,
                    (next_status, now, encoded, str(suggestion_id)),
                ).rowcount
            else:
                changed = connection.execute(
                    """
                    UPDATE order_suggestions
                    SET status = ?, updated_at_utc = ?, record_json = ?
                    WHERE id = ? AND status = 'pending' AND requested_by = ?
                    """,
                    (next_status, now, encoded, str(suggestion_id), str(requested_by)),
                ).rowcount
            return record if changed == 1 else None

    def _save(self, record: dict[str, Any]) -> dict[str, Any]:
        saved = dict(record)
        now = datetime.now(timezone.utc).isoformat()
        saved.setdefault("created_at_utc", now)
        saved.setdefault("updated_at_utc", saved["created_at_utc"])
        saved.setdefault("expires_at_utc", saved["created_at_utc"])
        encoded = json.dumps(saved, ensure_ascii=True, sort_keys=True)
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO order_suggestions (
                    id, requested_by, status, created_at_utc,
                    updated_at_utc, expires_at_utc, record_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    requested_by = excluded.requested_by,
                    status = excluded.status,
                    updated_at_utc = excluded.updated_at_utc,
                    expires_at_utc = excluded.expires_at_utc,
                    record_json = excluded.record_json
                """,
                (
                    str(saved["id"]),
                    str(saved.get("requested_by", "")),
                    str(saved.get("status", "")),
                    str(saved["created_at_utc"]),
                    str(saved["updated_at_utc"]),
                    str(saved["expires_at_utc"]),
                    encoded,
                ),
            )
        return saved

    def _import_legacy_suggestions(self) -> None:
        root = self.results_dir / "daily"
        if not root.exists():
            return
        for path in sorted(root.glob("*/order_suggestions.jsonl")):
            if not self.database.artifact_needs_import(path):
                continue
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
                    self._save(row)
            self.database.mark_artifact_imported(path)
