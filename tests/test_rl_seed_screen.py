import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from scripts import run_rl_seed_screen as runner


class RLSeedScreenTest(unittest.TestCase):
    def test_parse_seeds_requires_at_least_one_seed(self):
        self.assertEqual(runner.parse_seeds("41, 42,43"), [41, 42, 43])
        with self.assertRaises(ValueError):
            runner.parse_seeds("")

    def test_train_command_uses_isolated_model_dir_and_rolling_validation(self):
        command = runner.build_train_command(
            seed=41,
            models_dir=Path("results/daily/seed_41/models"),
            timesteps=123,
            device="cpu",
            validation_fraction=0.25,
            validation_windows=7,
        )

        self.assertEqual(command[0], sys.executable)
        self.assertIn("train.py", command)
        self.assertIn("--skip-backtest", command)
        self.assertIn("--models-dir", command)
        self.assertIn(str(Path("results/daily/seed_41/models")), command)
        self.assertIn("--validation-windows", command)
        self.assertIn("7", command)

    def test_backtest_command_uses_fixed_live_like_defaults(self):
        command = runner.build_backtest_command(models_dir=Path("models/seed_41"))

        self.assertEqual(command[0], sys.executable)
        self.assertIn("backtest.py", command)
        self.assertIn("--realism-profile", command)
        self.assertIn("live_like", command)
        self.assertIn("--method", command)
        self.assertIn("dynamic_weighted", command)
        self.assertIn("--autosave-profit-threshold", command)

    def test_parse_backtest_session_dir_reads_log_output(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            base = Path(tmp_name)
            stdout = base / "stdout.log"
            stderr = base / "stderr.log"
            stdout.write_text("", encoding="utf-8")
            stderr.write_text(
                "2026-07-22 | INFO | Backtest session output directory -> K:\\BTC-ETH Trading\\results\\daily\\2026-07-22\\9\n",
                encoding="utf-8",
            )

            parsed = runner.parse_backtest_session_dir(stdout_path=stdout, stderr_path=stderr)

        self.assertEqual(str(parsed), "K:\\BTC-ETH Trading\\results\\daily\\2026-07-22\\9")

    def test_write_seed_screen_summary_outputs_expected_columns(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            out = Path(tmp_name)
            path = runner.write_seed_screen_summary(
                out,
                [
                    runner.build_seed_summary_row(
                        seed=41,
                        seed_dir=out / "seed_41",
                        models_dir=out / "seed_41" / "models",
                        backtest_session_dir=Path("results/daily/2026-07-22/4"),
                        evidence_path=out / "seed_41" / "rl_evidence.json",
                        metrics={"total_return_pct": 1.2, "sharpe_ratio": 0.3},
                    )
                ],
            )

            saved = pd.read_csv(path)

        self.assertEqual(saved["seed"].tolist(), [41])
        self.assertEqual(saved["total_return_pct"].tolist(), [1.2])
        self.assertIn("evidence_path", saved.columns)

    def test_run_seed_screen_dry_run_writes_commands_without_executing(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            out = Path(tmp_name) / "screen"
            args = Namespace(
                seeds="41",
                timesteps=10,
                device="cpu",
                validation_fraction=0.2,
                validation_windows=5,
                pipeline="rl_only",
                realism_profile="live_like",
                method="dynamic_weighted",
                output_dir=out,
                run_label="unit",
                dry_run=True,
            )
            with patch.object(runner, "_current_git_commit", return_value="abc123"):
                result = runner.run_seed_screen(args)

            summary = pd.read_csv(result / "seed_screen_summary.csv")
            training_stdout = (result / "seed_41" / "training_stdout.log").read_text(encoding="utf-8")
            backtest_stdout = (result / "seed_41" / "backtest_stdout.log").read_text(encoding="utf-8")

        self.assertEqual(summary["seed"].tolist(), [41])
        self.assertIn("DRY RUN", training_stdout)
        self.assertIn("train.py", training_stdout)
        self.assertIn("backtest.py", backtest_stdout)


if __name__ == "__main__":
    unittest.main()
