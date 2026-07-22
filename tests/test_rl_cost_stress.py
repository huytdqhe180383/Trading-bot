import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from scripts import run_rl_cost_stress as runner


class RLCostStressTest(unittest.TestCase):
    def test_parse_model_specs_requires_label_and_path(self):
        specs = runner.parse_model_specs(["seed_41=results/seed_41/models"])

        self.assertEqual(specs[0].label, "seed_41")
        self.assertEqual(specs[0].models_dir, Path("results/seed_41/models"))
        with self.assertRaises(ValueError):
            runner.parse_model_specs([])
        with self.assertRaises(ValueError):
            runner.parse_model_specs(["missing_separator"])

    def test_parse_cost_profiles_requires_non_negative_values(self):
        profiles = runner.parse_cost_profiles("base:0.001:0.002:1,stress:0.003:0.004:2")

        self.assertEqual([profile.label for profile in profiles], ["base", "stress"])
        self.assertEqual(profiles[0].fee, 0.001)
        self.assertEqual(profiles[1].latency_steps, 2)
        with self.assertRaises(ValueError):
            runner.parse_cost_profiles("")
        with self.assertRaises(ValueError):
            runner.parse_cost_profiles("bad:0.001:0.002")
        with self.assertRaises(ValueError):
            runner.parse_cost_profiles("bad:-0.001:0.002:1")

    def test_backtest_command_includes_cost_overrides(self):
        profile = runner.CostProfile(label="stress", fee=0.003, slippage=0.004, latency_steps=2)

        command = runner.build_backtest_command(
            models_dir=Path("models/seed_41"),
            profile=profile,
            step_turnover_cap_enabled=True,
            step_turnover_cap_normal=0.15,
            step_turnover_cap_stress=0.10,
            step_turnover_cap_crisis=0.06,
        )

        self.assertEqual(command[0], sys.executable)
        self.assertIn("backtest.py", command)
        self.assertIn("--fee-override", command)
        self.assertIn("0.003", command)
        self.assertIn("--slippage-override", command)
        self.assertIn("0.004", command)
        self.assertIn("--latency-steps-override", command)
        self.assertIn("2", command)
        self.assertIn("--step-turnover-cap-enabled", command)
        self.assertIn("--step-turnover-cap-normal", command)
        self.assertIn("0.15", command)
        self.assertIn("--step-turnover-cap-stress", command)
        self.assertIn("0.1", command)
        self.assertIn("--step-turnover-cap-crisis", command)
        self.assertIn("0.06", command)

    def test_run_cost_stress_dry_run_writes_commands_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            out = Path(tmp_name) / "stress"
            args = Namespace(
                model=["seed_41=models/seed_41"],
                profiles="base:0.001:0.002:1",
                pipeline="rl_only",
                realism_profile="live_like",
                method="dynamic_weighted",
                output_dir=out,
                run_label="unit",
                step_turnover_cap_enabled=False,
                step_turnover_cap_normal=None,
                step_turnover_cap_stress=None,
                step_turnover_cap_crisis=None,
                dry_run=True,
            )
            with patch.object(runner, "_current_git_commit", return_value="abc123"):
                result = runner.run_cost_stress(args)

            summary = pd.read_csv(result / "cost_stress_summary.csv")
            stdout = (result / "seed_41" / "base" / "backtest_stdout.log").read_text(encoding="utf-8")

        self.assertEqual(summary["model_label"].tolist(), ["seed_41"])
        self.assertEqual(summary["cost_profile"].tolist(), ["base"])
        self.assertIn("DRY RUN", stdout)
        self.assertIn("--fee-override", stdout)
        self.assertIn("--no-step-turnover-cap-enabled", stdout)

    def test_parse_backtest_session_dir_strips_ansi_codes(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            base = Path(tmp_name)
            stdout = base / "stdout.log"
            stderr = base / "stderr.log"
            stdout.write_text(
                "Backtest session output directory -> K:\\BTC-ETH Trading\\results\\daily\\2026-07-22\\24\x1b[0m\n",
                encoding="utf-8",
            )
            stderr.write_text("", encoding="utf-8")

            parsed = runner.parse_backtest_session_dir(stdout_path=stdout, stderr_path=stderr)

        self.assertEqual(str(parsed), "K:\\BTC-ETH Trading\\results\\daily\\2026-07-22\\24")


if __name__ == "__main__":
    unittest.main()
