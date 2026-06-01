import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from tradingbot.runtime.artifacts import (
    append_csv_row,
    create_numbered_daily_dir,
    load_live_decisions,
    write_json_artifact,
    write_live_session_summary,
)


class RuntimeArtifactsTest(unittest.TestCase):
    def test_create_numbered_daily_dir_uses_next_numeric_child(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "daily" / "2026-05-31" / "1").mkdir(parents=True)
            (root / "daily" / "2026-05-31" / "notes").mkdir()

            session_dir = create_numbered_daily_dir(root, "2026-05-31")

            self.assertEqual(session_dir, root / "daily" / "2026-05-31" / "2")
            self.assertTrue(session_dir.exists())

    def test_write_json_artifact_serializes_paths(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "metadata.json"
            write_json_artifact(out, {"path": Path("models/live_baseline"), "value": 1})

            data = json.loads(out.read_text(encoding="utf-8"))

            self.assertEqual(data["path"], str(Path("models/live_baseline")))
            self.assertEqual(data["value"], 1)

    def test_append_csv_row_writes_header_once(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "rows.csv"

            append_csv_row(out, {"cycle": 1, "status": "ok"})
            append_csv_row(out, {"cycle": 2, "status": "ok"})

            saved = pd.read_csv(out)
            self.assertEqual(saved["cycle"].tolist(), [1, 2])
            self.assertEqual(out.read_text(encoding="utf-8").count("cycle,status"), 1)

    def test_write_live_session_summary_uses_strategy_nav(self):
        with TemporaryDirectory() as tmp:
            session_dir = Path(tmp)
            rows = [
                {"status": "ok", "orders_submitted": 0, "orders_filled": 0, "nav": 100.0},
                {"status": "ok", "orders_submitted": 1, "orders_filled": 1, "nav": 102.0},
            ]

            write_live_session_summary(session_dir, rows)

            summary = json.loads((session_dir / "live_session_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["rows"], 2)
            self.assertEqual(summary["orders_submitted"], 1)
            self.assertEqual(summary["last_nav"], 102.0)

    def test_load_live_decisions_reads_nested_daily_sessions(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = root / "daily" / "2026-05-31" / "1"
            session_dir.mkdir(parents=True)
            pd.DataFrame(
                [
                    {
                        "timestamp_utc": "2026-05-31T00:00:00+00:00",
                        "nav": 100.0,
                        "status": "ok",
                    }
                ]
            ).to_csv(session_dir / "live_trade_decisions_okx_testnet.csv", index=False)

            loaded = load_live_decisions(root)

            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded["session_dir"].iloc[0], str(session_dir))


if __name__ == "__main__":
    unittest.main()
