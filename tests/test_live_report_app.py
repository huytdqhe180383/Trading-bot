import unittest
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from tradingbot.reports.live_daily import export_report, load_live_decisions, summarize_frame


ROOT = Path(__file__).resolve().parents[1]


class LiveReportApplicationTest(unittest.TestCase):
    def test_live_report_uses_runtime_artifact_loader(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            session = base / "daily" / "2026-05-31" / "1"
            session.mkdir(parents=True)
            pd.DataFrame(
                [
                    {
                        "timestamp_utc": "2026-05-31T00:00:00+00:00",
                        "nav": 100.0,
                        "status": "ok",
                    }
                ]
            ).to_csv(session / "live_trade_decisions_okx_testnet.csv", index=False)

            out = load_live_decisions(base)

            self.assertEqual(len(out), 1)
            self.assertEqual(out["session_dir"].iloc[0], str(session))

    def test_live_report_exports_under_daily_report_folder(self):
        df = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(["2026-05-31T00:00:00+00:00"], utc=True),
                "timestamp_local": ["2026-05-31T07:00:00+07:00"],
                "nav": [100.0],
                "status": ["ok"],
                "session_dir": ["s"],
            }
        )
        with TemporaryDirectory() as tmp:
            json_path, md_path = export_report(
                df,
                "Asia/Bangkok",
                "Live report: 2026-05-31 (Asia/Bangkok)",
                "2026-05-31",
                report_root=Path(tmp) / "report",
            )

            self.assertEqual(json_path.parent, Path(tmp) / "report" / "daily" / "2026-05-31")
            self.assertTrue(md_path.exists())
            self.assertIn("unrealized_pnl_usd", summarize_frame(df, "Asia/Bangkok"))

    def test_script_wrapper_runs_from_repo_root(self):
        result = subprocess.run(
            [sys.executable, "scripts/live_daily_report.py", "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Summarize live paper-trading decisions", result.stdout)


if __name__ == "__main__":
    unittest.main()
