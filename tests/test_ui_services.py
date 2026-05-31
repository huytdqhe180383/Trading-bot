import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from ui.services import (
    STRATEGY_NAV_NOTE,
    build_control_command,
    build_dashboard_payload,
    build_history_payload,
    build_report_payload,
    read_log_source,
    safe_compact_report_path,
)


def _write_live_decisions(results_dir: Path, run_date: str = "2026-05-31", session: str = "1") -> Path:
    session_dir = results_dir / "daily" / run_date / session
    session_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(
        [
            {
                "timestamp_utc": "2026-05-30T17:10:12+00:00",
                "cycle": 1,
                "nav": 10000.0,
                "pnl_pct": 0.0,
                "btc_weight": 0.50,
                "eth_weight": 0.49,
                "cash_weight": 0.01,
                "orders_submitted": 0,
                "orders_filled": 0,
                "status": "ok",
            },
            {
                "timestamp_utc": "2026-05-30T18:10:12+00:00",
                "cycle": 2,
                "nav": 10150.0,
                "pnl_pct": 1.5,
                "btc_weight": 0.51,
                "eth_weight": 0.48,
                "cash_weight": 0.01,
                "orders_submitted": 1,
                "orders_filled": 1,
                "status": "ok",
            },
        ]
    )
    csv_path = session_dir / "live_trade_decisions_okx_testnet.csv"
    df.to_csv(csv_path, index=False)
    return csv_path


class UIServicesTest(unittest.TestCase):
    def test_build_control_command_allows_exact_allowlist(self):
        self.assertEqual(build_control_command("start", service_name="trading-bot"), ["systemctl", "start", "trading-bot"])
        self.assertEqual(build_control_command("status", service_name="trading-bot"), ["systemctl", "status", "trading-bot"])
        with self.assertRaises(ValueError):
            build_control_command("reload", service_name="trading-bot")

    def test_build_control_command_can_prefix_sudo(self):
        self.assertEqual(
            build_control_command("restart", service_name="trading-bot", use_sudo=True),
            ["sudo", "-n", "systemctl", "restart", "trading-bot"],
        )

    def test_safe_compact_report_path_blocks_invalid_names(self):
        with TemporaryDirectory() as tmp:
            reports_dir = Path(tmp)
            day_dir = reports_dir / "daily" / "2026-05-31"
            day_dir.mkdir(parents=True)
            report_file = day_dir / "live_report_2026-05-31.md"
            report_file.write_text("# report\n", encoding="utf-8")

            self.assertEqual(
                safe_compact_report_path("2026-05-31", "live_report_2026-05-31.md", reports_dir=reports_dir),
                report_file.resolve(),
            )
            with self.assertRaises(ValueError):
                safe_compact_report_path("2026-05-31", "../secret.txt", reports_dir=reports_dir)
            with self.assertRaises(ValueError):
                safe_compact_report_path("2026-05-31", ".env", reports_dir=reports_dir)
            with self.assertRaises(ValueError):
                safe_compact_report_path("2026_05_31", "live_report_2026-05-31.md", reports_dir=reports_dir)

    def test_read_log_source_handles_missing_and_invalid_sources(self):
        with TemporaryDirectory() as tmp:
            logs_dir = Path(tmp)
            missing = read_log_source("stderr", lines=50, logs_dir=logs_dir)
            self.assertFalse(missing["available"])
            self.assertIn("live_stderr.log", missing["error"])
            with self.assertRaises(ValueError):
                read_log_source("../../../etc/passwd", lines=50, logs_dir=logs_dir)

    def test_build_report_payload_handles_empty_results(self):
        with TemporaryDirectory() as tmp:
            payload = build_report_payload(mode="date", report_date="2026-05-31", results_dir=Path(tmp), reports_dir=Path(tmp))
            self.assertEqual(payload["summary"]["rows"], 0)
            self.assertEqual(payload["recent_rows"], [])
            self.assertEqual(payload["note"], STRATEGY_NAV_NOTE)

    def test_build_history_payload_groups_sessions_and_marks_trade_rows(self):
        with TemporaryDirectory() as tmp:
            results_dir = Path(tmp)
            _write_live_decisions(results_dir, session="1")
            _write_live_decisions(results_dir, session="2")

            payload = build_history_payload(results_dir=results_dir, tz_name="Asia/Bangkok")
            self.assertEqual(len(payload["sessions"]), 2)
            self.assertEqual(payload["rows"][-1]["ui_action"], "trade")
            self.assertEqual(payload["note"], STRATEGY_NAV_NOTE)

    def test_build_dashboard_payload_includes_status_and_summary(self):
        with TemporaryDirectory() as tmp:
            results_dir = Path(tmp) / "results"
            reports_dir = Path(tmp) / "report"
            _write_live_decisions(results_dir)

            def fake_status_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="ActiveState=active\nSubState=running\nMainPID=123\nExecMainStartTimestamp=Sat 2026-05-31 09:00:00 +07\n",
                    stderr="",
                )

            payload = build_dashboard_payload(
                tz_name="Asia/Bangkok",
                results_dir=results_dir,
                reports_dir=reports_dir,
                status_runner=fake_status_runner,
            )
            self.assertEqual(payload["status"]["active_state"], "active")
            self.assertEqual(payload["today"]["summary"]["rows"], 2)
            self.assertEqual(payload["full_history"]["summary"]["orders_filled"], 1)
            self.assertAlmostEqual(payload["today"]["summary"]["unrealized_pnl_usd"], 150.0, places=6)
            self.assertEqual(payload["note"], STRATEGY_NAV_NOTE)


if __name__ == "__main__":
    unittest.main()
