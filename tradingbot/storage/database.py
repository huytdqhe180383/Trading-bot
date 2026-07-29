"""SQLite ownership, schema migrations, and transaction handling.

This module deliberately contains no trading decisions. It gives domain stores
one reliable way to open the operational database and apply schema changes.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def default_database_path(results_dir: Path) -> Path:
    """Return the local database path associated with a results directory."""
    return Path(results_dir) / "runtime" / "tradingbot.sqlite3"


_MIGRATIONS: tuple[tuple[int, str], ...] = (
    (
        1,
        """
        CREATE TABLE analyst_events (
            id TEXT PRIMARY KEY,
            created_at_utc TEXT NOT NULL,
            event_type TEXT NOT NULL,
            status TEXT NOT NULL,
            symbol TEXT NOT NULL,
            role TEXT NOT NULL,
            recommendation TEXT,
            confidence REAL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            rationale TEXT NOT NULL,
            risk_notes TEXT NOT NULL,
            invalidation TEXT NOT NULL,
            error_code TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX analyst_events_created_idx
            ON analyst_events(created_at_utc, id);
        CREATE INDEX analyst_events_signal_idx
            ON analyst_events(status, recommendation, created_at_utc);

        CREATE TABLE order_suggestions (
            id TEXT PRIMARY KEY,
            requested_by TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL,
            expires_at_utc TEXT NOT NULL,
            record_json TEXT NOT NULL
        );
        CREATE INDEX order_suggestions_status_idx
            ON order_suggestions(status, expires_at_utc);

        CREATE TABLE live_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_dir TEXT NOT NULL,
            source_csv TEXT NOT NULL,
            timestamp_utc TEXT NOT NULL,
            cycle INTEGER NOT NULL,
            status TEXT NOT NULL,
            row_json TEXT NOT NULL,
            UNIQUE(session_dir, timestamp_utc, cycle)
        );
        CREATE INDEX live_decisions_timestamp_idx
            ON live_decisions(timestamp_utc, id);
        CREATE INDEX live_decisions_session_idx
            ON live_decisions(session_dir, cycle);

        CREATE TABLE artifact_imports (
            path TEXT PRIMARY KEY,
            size_bytes INTEGER NOT NULL,
            modified_ns INTEGER NOT NULL,
            imported_at_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """,
    ),
)


class OperationalDatabase:
    """Own the operational SQLite file and its schema lifecycle."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """Open a read connection and close it deterministically."""
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        """Run a transaction and always close its connection."""
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def artifact_needs_import(self, path: Path) -> bool:
        """Return whether a file is new or changed since its last import."""
        artifact = Path(path)
        try:
            stat = artifact.stat()
        except OSError:
            return False
        with self.read() as connection:
            row = connection.execute(
                "SELECT size_bytes, modified_ns FROM artifact_imports WHERE path = ?",
                (str(artifact.resolve()),),
            ).fetchone()
        return row is None or int(row["size_bytes"]) != stat.st_size or int(row["modified_ns"]) != stat.st_mtime_ns

    def mark_artifact_imported(self, path: Path) -> None:
        """Record the current file fingerprint after a successful import."""
        artifact = Path(path)
        stat = artifact.stat()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO artifact_imports(path, size_bytes, modified_ns)
                VALUES (?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    size_bytes = excluded.size_bytes,
                    modified_ns = excluded.modified_ns,
                    imported_at_utc = CURRENT_TIMESTAMP
                """,
                (str(artifact.resolve()), stat.st_size, stat.st_mtime_ns),
            )

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            applied = {
                int(row["version"])
                for row in connection.execute("SELECT version FROM schema_migrations")
            }
            for version, sql in _MIGRATIONS:
                if version in applied:
                    continue
                for statement in _sql_statements(sql):
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations(version) VALUES (?)",
                    (version,),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def _sql_statements(script: str) -> Iterator[str]:
    """Yield complete SQLite statements without losing transaction ownership."""
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                yield statement
            buffer = ""
    if buffer.strip():
        raise ValueError("Incomplete SQLite migration statement.")
