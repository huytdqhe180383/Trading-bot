import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from tradingbot.analyst.models import AnalystEvent
from tradingbot.analyst.store import AnalystEventStore
from tradingbot.execution.suggestions import OrderSuggestionStore
from tradingbot.storage import LiveDecisionStore, OperationalDatabase


class OperationalDatabaseTest(unittest.TestCase):
    def test_initialization_applies_versioned_schema(self):
        with TemporaryDirectory() as tmp:
            database = OperationalDatabase(Path(tmp) / "state.sqlite3")

            with database.read() as connection:
                tables = {
                    row["name"]
                    for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
                }
                versions = [row["version"] for row in connection.execute("SELECT version FROM schema_migrations")]

            self.assertIn("analyst_events", tables)
            self.assertIn("order_suggestions", tables)
            self.assertIn("live_decisions", tables)
            self.assertEqual(versions, [1])

            reopened = OperationalDatabase(Path(tmp) / "state.sqlite3")
            with reopened.read() as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM schema_migrations").fetchone()[0], 1)

    def test_analyst_store_imports_legacy_jsonl_once(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            legacy = base / "results" / "daily" / "2026-07-29" / "analyst_events.jsonl"
            legacy.parent.mkdir(parents=True)
            event = AnalystEvent(event_type="analysis", status="ok", title="Test", message="Stored")
            legacy.write_text(json.dumps(event.to_dict()) + "\n", encoding="utf-8")
            store = AnalystEventStore(results_dir=base / "results", reports_dir=base / "report")

            first = store.load_events()
            second = store.load_events()

            self.assertEqual([row["id"] for row in first], [event.id])
            self.assertEqual([row["id"] for row in second], [event.id])

    def test_suggestion_confirmation_claim_is_atomic(self):
        with TemporaryDirectory() as tmp:
            store = OrderSuggestionStore(results_dir=Path(tmp) / "results")
            store.create(
                {
                    "id": "suggestion-1",
                    "requested_by": "42",
                    "status": "pending",
                    "created_at_utc": "2026-07-29T00:00:00+00:00",
                    "expires_at_utc": "2999-01-01T00:00:00+00:00",
                    "order": {"inst_id": "BTC-USDT"},
                }
            )

            first = store.claim_for_confirmation("suggestion-1", "42")
            second = store.claim_for_confirmation("suggestion-1", "42")

            self.assertEqual(first["status"], "submitting")
            self.assertIsNone(second)
            self.assertIsNone(store.reject("suggestion-1", "42"))

    def test_rejection_closes_pending_suggestion_once(self):
        with TemporaryDirectory() as tmp:
            store = OrderSuggestionStore(results_dir=Path(tmp) / "results")
            store.create(
                {
                    "id": "suggestion-2",
                    "requested_by": "42",
                    "status": "pending",
                    "created_at_utc": "2026-07-29T00:00:00+00:00",
                    "expires_at_utc": "2999-01-01T00:00:00+00:00",
                }
            )

            rejected = store.reject("suggestion-2", "42")

            self.assertEqual(rejected["status"], "rejected")
            self.assertIsNone(store.claim_for_confirmation("suggestion-2", "42"))

    def test_live_store_indexes_csv_artifacts_without_deleting_them(self):
        with TemporaryDirectory() as tmp:
            results_dir = Path(tmp) / "results"
            csv_path = results_dir / "daily" / "2026-07-29" / "1" / "live_trade_decisions_okx_testnet.csv"
            csv_path.parent.mkdir(parents=True)
            pd.DataFrame(
                [{"timestamp_utc": "2026-07-29T00:00:00+00:00", "cycle": 1, "status": "ok", "nav": 100.0}]
            ).to_csv(csv_path, index=False)
            store = LiveDecisionStore(results_dir=results_dir)

            rows = store.load()

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["nav"], 100.0)
            self.assertTrue(csv_path.exists())


if __name__ == "__main__":
    unittest.main()
