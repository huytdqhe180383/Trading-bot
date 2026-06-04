import subprocess
import sys
import time
import unittest
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts import run_kpi_improvement_experiment as runner


class KpiExperimentRunnerTests(unittest.TestCase):
    def test_run_times_out_and_raises(self):
        start = time.monotonic()

        with self.assertRaises(subprocess.TimeoutExpired):
            runner._run(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                timeout_seconds=0.5,
                poll_seconds=0.1,
            )

        self.assertLess(time.monotonic() - start, 10)

    def test_parse_csv_subset_filters_known_values(self):
        parsed = runner._parse_csv_subset("42,2026", [42, 1337, 2026], item_type=int)

        self.assertEqual(parsed, [42, 2026])

    def test_risk_first_rank_prefers_trade_quality_over_return(self):
        high_return_low_quality = {
            "total_return_pct": 200.0,
            "trade_win_rate_pct": 45.0,
            "trade_profit_factor": 1.05,
            "sharpe_ratio": 1.0,
            "sortino_ratio": 1.2,
            "calmar_ratio": 1.0,
            "max_drawdown_pct": -30.0,
        }
        lower_return_higher_quality = {
            "total_return_pct": 25.0,
            "trade_win_rate_pct": 65.0,
            "trade_profit_factor": 1.35,
            "sharpe_ratio": 1.7,
            "sortino_ratio": 2.0,
            "calmar_ratio": 2.2,
            "max_drawdown_pct": -12.0,
        }

        self.assertGreater(
            runner.risk_first_rank_score(lower_return_higher_quality),
            runner.risk_first_rank_score(high_return_low_quality),
        )

    def test_promotion_gate_fails_closed_on_low_trade_win_rate(self):
        row = {
            "trade_win_rate_pct": 59.9,
            "trade_profit_factor": 1.5,
            "sharpe_ratio": 1.6,
            "sortino_ratio": 2.0,
            "calmar_ratio": 2.5,
            "max_drawdown_pct": -10.0,
            "june_plunge_max_drawdown_pct": -4.0,
        }

        passed, reasons = runner.passes_promotion_gates(row)

        self.assertFalse(passed)
        self.assertTrue(any("trade_win_rate_pct" in reason for reason in reasons))

    def test_train_pair_fresh_mode_does_not_resume_from_baseline(self):
        commands: list[list[str]] = []

        def fake_run(command, **kwargs):
            commands.append(command)

        with patch.object(runner, "_run", side_effect=fake_run):
            runner.train_pair(
                seed=42,
                ppo_steps=100,
                sac_steps=50,
                algos=("PPO", "SAC"),
                env=None,
                dry_run=True,
                resume=False,
            )

        self.assertEqual(len(commands), 2)
        self.assertNotIn("--resume", commands[0])
        self.assertNotIn("--resume", commands[1])
        self.assertIn("--skip-backtest", commands[0])
        self.assertIn("--skip-backtest", commands[1])

    def test_parser_accepts_fresh_training_mode(self):
        args = runner.build_parser().parse_args(["--training-mode", "fresh"])

        self.assertEqual(args.training_mode, "fresh")

    def test_evaluate_methods_uses_fresh_model_dir_for_candidate_backtests(self):
        commands: list[list[str]] = []

        def fake_run(command, **kwargs):
            commands.append(command)

        with patch.object(runner, "_run", side_effect=fake_run):
            runner.evaluate_methods(
                output_dir=Path("results/daily/2026-06-04/kpi/1"),
                phase="phase",
                seed=42,
                variant="fresh",
                env=None,
                dry_run=True,
            )

        backtest_commands = [command for command in commands if "backtest.py" in command]
        self.assertGreaterEqual(len(backtest_commands), 2)
        for command in backtest_commands:
            self.assertIn("--model-dir", command)
            self.assertIn(str(runner.ROOT / "models"), command)

    def test_session_dirs_scan_across_daily_boundaries(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "2026-06-04" / "9").mkdir(parents=True)
            (base / "2026-06-05" / "1").mkdir(parents=True)
            with patch.object(runner, "RESULTS_DAILY", base):
                sessions = runner._session_dirs()

        self.assertIn(base / "2026-06-04" / "9", sessions)
        self.assertIn(base / "2026-06-05" / "1", sessions)

    def test_write_report_labels_fresh_training_mode(self):
        row = {
            "phase": "phase2_quick_screen",
            "variant": "fresh",
            "seed": 42,
            "method": "dynamic_weighted",
            "trade_win_rate_pct": 100.0,
            "trade_profit_factor": 2.0,
            "sharpe_ratio": 0.1,
            "sortino_ratio": 0.2,
            "calmar_ratio": 0.3,
            "total_return_pct": 1.0,
            "max_drawdown_pct": -2.0,
            "june_plunge_max_drawdown_pct": -1.0,
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "results" / "daily" / "2026-06-04" / "kpi_improvement_experiment" / "1"
            output_dir.mkdir(parents=True)
            report_daily = root / "report" / "daily"
            backup = root / "results" / "important" / "model_backups" / "baseline"
            with (
                patch.object(runner, "ROOT", root),
                patch.object(runner, "REPORT_DAILY", report_daily),
                patch.object(runner, "BASELINE_BACKUP", backup),
                patch.object(runner, "_today", return_value="2026-06-04"),
            ):
                report_path = runner.write_report(
                    output_dir,
                    [row],
                    Namespace(phase="phase2-quick", training_mode="fresh"),
                )

            text = report_path.read_text(encoding="utf-8")

        self.assertIn("- Training mode: `fresh`", text)
        self.assertIn("(unused in fresh mode)", text)
        self.assertIn("trains new PPO/SAC policies from scratch", text)
        self.assertNotIn("restores the immutable 107% checkpoint", text)


if __name__ == "__main__":
    unittest.main()
