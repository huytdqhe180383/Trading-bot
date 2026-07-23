import json
import unittest
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from scripts import evaluate_rl_promotion_gate as gate


def _row(seed: int, profile: str, ret: float, sharpe: float, promoted: bool, status: str = "VERIFIED"):
    return {
        "seed": seed,
        "model_label": f"seed_{seed}",
        "cost_profile": profile,
        "fee": 0.0,
        "slippage": 0.0,
        "latency_steps": 1,
        "total_return_pct": ret,
        "annualised_return_pct": ret,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sharpe,
        "max_drawdown_pct": -20.0,
        "profit_factor": 1.1,
        "total_trades_count": 100,
        "trade_count": 10,
        "trade_win_rate_pct": 50.0,
        "trade_profit_factor": 1.2,
        "trade_expectancy_pct": 0.5,
        "evidence_status": status,
        "promoted": promoted,
        "code_commit": "abc123",
        "models_dir": f"models/{seed}",
        "backtest_session_dir": f"results/{seed}/{profile}",
        "evidence_path": f"results/{seed}/{profile}/rl_evidence.json",
    }


class RLPromotionGateTest(unittest.TestCase):
    def test_current_style_candidate_fails_closed(self):
        with TemporaryDirectory() as tmp_name:
            base = Path(tmp_name)
            cost_path = base / "costs.csv"
            rows = []
            for seed in (41, 42, 43):
                rows.append(_row(seed, "live_like_2x", 55.0, 0.5, False, status="ABSTAIN"))
                rows.append(_row(seed, "live_like_3x", -40.0, -0.8, False, status="ABSTAIN"))
            pd.DataFrame(rows).to_csv(cost_path, index=False)

            out = gate.evaluate_promotion_gate(
                Namespace(
                    candidate_label="turnover_strict",
                    cost_stress_by_seed=cost_path,
                    validation_best=None,
                    output_dir=base / "gate",
                    run_label="unit",
                    min_seeds=5,
                    operating_profile="live_like_2x",
                    severe_profile="live_like_3x",
                    min_operating_return_pct=0.0,
                    min_operating_sharpe=0.0,
                    max_operating_drawdown_pct=-40.0,
                    min_severe_return_pct=0.0,
                    min_severe_sharpe=0.0,
                    required_evidence_status="VERIFIED",
                    run_date=None,
                )
            )
            report = json.loads((out / "promotion_gate_report.json").read_text(encoding="utf-8"))
            summary = pd.read_csv(out / "promotion_gate_summary.csv")

        self.assertEqual(report["status"], "NOT_PROMOTED")
        self.assertEqual(report["llm_evidence_status"], "ABSTAIN")
        self.assertIn("min_seed_count", report["blocking_failures"])
        self.assertIn("severe_return_all_seeds", report["blocking_failures"])
        self.assertIn("all_evidence_verified", report["blocking_failures"])
        self.assertIn("all_artifacts_marked_promoted", report["blocking_failures"])
        self.assertIn("min_seed_count", summary["name"].tolist())

    def test_promotes_only_when_all_blocking_gates_pass(self):
        with TemporaryDirectory() as tmp_name:
            base = Path(tmp_name)
            cost_path = base / "costs.csv"
            rows = []
            for seed in (41, 42, 43, 44, 45):
                rows.append(_row(seed, "live_like_2x", 10.0, 0.2, True))
                rows.append(_row(seed, "live_like_3x", 1.0, 0.1, True))
            pd.DataFrame(rows).to_csv(cost_path, index=False)

            out = gate.evaluate_promotion_gate(
                Namespace(
                    candidate_label="promotable",
                    cost_stress_by_seed=cost_path,
                    validation_best=None,
                    output_dir=base / "gate",
                    run_label="unit",
                    min_seeds=5,
                    operating_profile="live_like_2x",
                    severe_profile="live_like_3x",
                    min_operating_return_pct=0.0,
                    min_operating_sharpe=0.0,
                    max_operating_drawdown_pct=-40.0,
                    min_severe_return_pct=0.0,
                    min_severe_sharpe=0.0,
                    required_evidence_status="VERIFIED",
                    run_date=None,
                )
            )
            report = json.loads((out / "promotion_gate_report.json").read_text(encoding="utf-8"))

        self.assertEqual(report["status"], "PROMOTED")
        self.assertEqual(report["llm_evidence_status"], "VERIFIED")
        self.assertEqual(report["blocking_failures"], [])


if __name__ == "__main__":
    unittest.main()
