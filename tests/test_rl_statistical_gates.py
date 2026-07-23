import json
import unittest
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from scripts import evaluate_rl_statistical_gates as stats


def _row(seed: int, profile: str, ret: float, sharpe: float, drawdown: float = -18.0):
    return {
        "seed": seed,
        "model_label": f"seed_{seed}",
        "cost_profile": profile,
        "total_return_pct": ret,
        "sharpe_ratio": sharpe,
        "max_drawdown_pct": drawdown,
    }


class RLStatisticalGatesTest(unittest.TestCase):
    def test_fails_closed_when_seed_count_and_selection_bias_diagnostics_are_missing(self):
        with TemporaryDirectory() as tmp_name:
            base = Path(tmp_name)
            cost_path = base / "costs.csv"
            rows = []
            for seed in (41, 42, 43, 44, 45):
                rows.append(_row(seed, "live_like_2x", 80.0, 1.2))
                rows.append(_row(seed, "live_like_3x", 3.0, 0.1))
            pd.DataFrame(rows).to_csv(cost_path, index=False)

            out = stats.evaluate_statistical_gates(
                Namespace(
                    candidate_label="hold12captight_seed41_45",
                    cost_stress_by_seed=cost_path,
                    output_dir=base / "stats",
                    run_label="unit",
                    run_date=None,
                    seed=7,
                    n_bootstrap=200,
                    min_statistical_seeds=10,
                    operating_profile="live_like_2x",
                    severe_profile="live_like_3x",
                    min_bootstrap_probability=0.75,
                    min_operating_return_pct=0.0,
                    min_operating_sharpe=0.0,
                    max_operating_drawdown_pct=-40.0,
                    min_severe_return_pct=0.0,
                    min_severe_sharpe=0.0,
                    max_severe_drawdown_pct=-40.0,
                    deflated_sharpe_probability=None,
                    min_deflated_sharpe_probability=0.95,
                    backtest_overfit_probability=None,
                    max_backtest_overfit_probability=0.10,
                    require_selection_bias_diagnostics=True,
                )
            )
            report = json.loads((out / "rl_statistical_report.json").read_text(encoding="utf-8"))
            summary = pd.read_csv(out / "statistical_gate_summary.csv")

        self.assertEqual(report["status"], "FAILED")
        self.assertFalse(report["statistical_gates_passed"])
        self.assertIn("min_statistical_seed_count", report["blocking_failures"])
        self.assertIn("deflated_sharpe_probability", report["blocking_failures"])
        self.assertIn("backtest_overfit_probability", report["blocking_failures"])
        self.assertTrue(
            summary.loc[
                summary["name"] == "severe_bootstrap_return_probability",
                "passed",
            ].iloc[0]
        )

    def test_passes_when_seed_count_bootstrap_and_selection_bias_diagnostics_pass(self):
        with TemporaryDirectory() as tmp_name:
            base = Path(tmp_name)
            cost_path = base / "costs.csv"
            rows = []
            for seed in range(10):
                rows.append(_row(seed, "live_like_2x", 50.0 + seed, 0.8 + seed / 100.0, -20.0))
                rows.append(_row(seed, "live_like_3x", 2.0 + seed / 10.0, 0.1 + seed / 100.0, -22.0))
            pd.DataFrame(rows).to_csv(cost_path, index=False)

            out = stats.evaluate_statistical_gates(
                Namespace(
                    candidate_label="candidate",
                    cost_stress_by_seed=cost_path,
                    output_dir=base / "stats",
                    run_label="unit",
                    run_date=None,
                    seed=11,
                    n_bootstrap=200,
                    min_statistical_seeds=10,
                    operating_profile="live_like_2x",
                    severe_profile="live_like_3x",
                    min_bootstrap_probability=0.75,
                    min_operating_return_pct=0.0,
                    min_operating_sharpe=0.0,
                    max_operating_drawdown_pct=-40.0,
                    min_severe_return_pct=0.0,
                    min_severe_sharpe=0.0,
                    max_severe_drawdown_pct=-40.0,
                    deflated_sharpe_probability=0.97,
                    min_deflated_sharpe_probability=0.95,
                    backtest_overfit_probability=0.08,
                    max_backtest_overfit_probability=0.10,
                    require_selection_bias_diagnostics=True,
                )
            )
            report = json.loads((out / "rl_statistical_report.json").read_text(encoding="utf-8"))

        self.assertEqual(report["status"], "PASSED")
        self.assertTrue(report["statistical_gates_passed"])
        self.assertEqual(report["blocking_failures"], [])
        self.assertIn("p2_5", report["profiles"]["live_like_3x"]["metrics"]["total_return_pct"]["bootstrap_mean_ci"])


if __name__ == "__main__":
    unittest.main()

