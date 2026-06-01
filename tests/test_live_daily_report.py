import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from scripts.live_daily_report import export_report, load_live_decisions, summarize_frame


class LiveDailyReportTest(unittest.TestCase):
    def test_load_live_decisions_reads_nested_daily_csvs(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            session = base / "daily" / "2026-05-31" / "1"
            session.mkdir(parents=True)
            df = pd.DataFrame(
                [
                    {
                        "timestamp_utc": "2026-05-30T17:10:12+00:00",
                        "nav": 10000.0,
                        "orders_submitted": 0,
                        "orders_filled": 0,
                        "status": "ok",
                    }
                ]
            )
            df.to_csv(session / "live_trade_decisions_okx_testnet.csv", index=False)
            out = load_live_decisions(base)
            self.assertEqual(len(out), 1)
            self.assertIn("session_dir", out.columns)

    def test_summarize_frame_computes_pnl(self):
        df = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    ["2026-05-30T17:10:12+00:00", "2026-05-30T18:10:12+00:00"], utc=True
                ),
                "timestamp_local": ["2026-05-31T00:10:12+07:00", "2026-05-31T01:10:12+07:00"],
                "nav": [10000.0, 10100.0],
                "orders_submitted": [0, 1],
                "orders_filled": [0, 1],
                "status": ["ok", "ok"],
                "btc_weight": [0.5, 0.51],
                "eth_weight": [0.49, 0.48],
                "cash_weight": [0.01, 0.01],
                "session_dir": ["a", "a"],
            }
        )
        summary = summarize_frame(df, "Asia/Bangkok")
        self.assertEqual(summary["rows"], 2)
        self.assertEqual(summary["orders_filled"], 1)
        self.assertAlmostEqual(summary["unrealized_pnl_usd"], 100.0, places=6)
        self.assertAlmostEqual(summary["unrealized_pnl_pct"], 1.0, places=6)

    def test_export_report_writes_json_and_markdown(self):
        df = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(["2026-05-30T17:10:12+00:00"], utc=True),
                "timestamp_local": ["2026-05-31T00:10:12+07:00"],
                "nav": [10000.0],
                "orders_submitted": [0],
                "orders_filled": [0],
                "status": ["ok"],
                "session_dir": ["a"],
            }
        )
        with TemporaryDirectory() as tmp:
            from scripts import live_daily_report as module

            original_base = module.BASE_DIR
            module.BASE_DIR = Path(tmp)
            try:
                json_path, md_path = export_report(df, "Asia/Bangkok", "Live report: 2026-05-31 (Asia/Bangkok)", "2026-05-31")
                self.assertTrue(json_path.exists())
                self.assertTrue(md_path.exists())
            finally:
                module.BASE_DIR = original_base


if __name__ == "__main__":
    unittest.main()
