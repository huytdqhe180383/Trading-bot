import tempfile
import unittest
from pathlib import Path

import pandas as pd

from tradingbot.reports.rl_behavior import (
    build_behavior_diagnostics,
    summarize_episode_behavior,
    write_behavior_diagnostics,
)


class RLBehaviorReportTest(unittest.TestCase):
    def test_summarize_episode_behavior_captures_policy_execution_gap_and_risk_exit(self):
        idx = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
        episode = pd.DataFrame(
            {
                "portfolio_value": [100.0, 99.0, 99.5],
                "btc_weight": [0.5, 0.1, 0.0],
                "eth_weight": [0.3, 0.0, 0.0],
                "cash_weight": [0.2, 0.9, 1.0],
                "target_btc_weight": [0.5, 0.4, 0.4],
                "target_eth_weight": [0.3, 0.3, 0.3],
                "target_cash_weight": [0.2, 0.3, 0.3],
                "turnover": [0.0, 0.7, 0.1],
                "transaction_cost": [0.0, 0.001, 0.0],
                "risk_exit_applied": [False, True, True],
                "risk_exit_reason": ["", "session_drawdown<=-6%", "session_drawdown<=-6%"],
                "reentry_locked": [False, True, True],
            },
            index=idx,
        )

        row = summarize_episode_behavior(
            label="unit",
            episode_df=episode,
            metrics={"total_return_pct": -0.5, "sharpe_ratio": -0.1},
        )

        self.assertEqual(row["label"], "unit")
        self.assertEqual(row["risk_exit_applied_count"], 2)
        self.assertGreater(row["risk_tracking_gap_mean"], 0.0)
        self.assertIn("session_drawdown<=-6%", row["risk_exit_reason_counts_json"])
        self.assertEqual(row["total_return_pct"], -0.5)

    def test_write_behavior_diagnostics_outputs_summary_and_monthly_csvs(self):
        idx = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
        episode = pd.DataFrame(
            {
                "portfolio_value": [100.0, 101.0, 100.5],
                "btc_weight": [0.4, 0.5, 0.0],
                "eth_weight": [0.2, 0.2, 0.0],
                "cash_weight": [0.4, 0.3, 1.0],
                "target_btc_weight": [0.4, 0.5, 0.5],
                "target_eth_weight": [0.2, 0.2, 0.2],
                "turnover": [0.0, 0.1, 0.7],
                "risk_exit_applied": [False, False, True],
                "risk_exit_reason": ["", "", "session_drawdown<=-6%"],
            },
            index=idx,
        )

        with tempfile.TemporaryDirectory() as tmp_name:
            base = Path(tmp_name)
            session = base / "session"
            session.mkdir()
            episode.to_parquet(session / "backtest_episode_rl_only_live_like_dynamic_weighted.parquet")
            (session / "backtest_metrics.csv").write_text(",value\ntotal_return_pct,0.5\n", encoding="utf-8")

            summary, monthly = build_behavior_diagnostics({"unit": session})
            paths = write_behavior_diagnostics(runs={"unit": session}, output_dir=base / "out")

            saved_summary = pd.read_csv(paths["summary"])
            saved_monthly = pd.read_csv(paths["monthly"])

        self.assertEqual(summary["label"].tolist(), ["unit"])
        self.assertFalse(monthly.empty)
        self.assertEqual(saved_summary["label"].tolist(), ["unit"])
        self.assertIn("realized_risk_on_mean", saved_monthly.columns)


if __name__ == "__main__":
    unittest.main()
