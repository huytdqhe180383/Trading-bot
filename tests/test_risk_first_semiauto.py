import unittest

import numpy as np
import pandas as pd

from metrics.performance import compute_trade_metrics
from environment.trading_env import SpotPortfolioEnv
from risk.semi_auto import SemiAutoRiskController, classify_recommendation
from scripts.run_live import LiveExecutionController


class RiskFirstSemiAutoTest(unittest.TestCase):
    def test_trade_metrics_are_distinct_from_step_win_rate(self):
        decisions = pd.DataFrame(
            [
                {"portfolio_value": 100.0, "btc_weight": 0.0, "eth_weight": 0.0, "risk_exit_applied": False},
                {"portfolio_value": 101.0, "btc_weight": 0.5, "eth_weight": 0.0, "risk_exit_applied": False},
                {"portfolio_value": 99.0, "btc_weight": 0.5, "eth_weight": 0.0, "risk_exit_applied": False},
                {"portfolio_value": 98.0, "btc_weight": 0.0, "eth_weight": 0.0, "risk_exit_applied": True},
                {"portfolio_value": 99.0, "btc_weight": 0.0, "eth_weight": 0.6, "risk_exit_applied": False},
                {"portfolio_value": 104.0, "btc_weight": 0.0, "eth_weight": 0.0, "risk_exit_applied": False},
            ]
        )

        metrics = compute_trade_metrics(decisions)

        self.assertAlmostEqual(metrics["trade_win_rate_pct"], 50.0, places=6)
        loss = (98.0 / 101.0 - 1.0) * 100.0
        win = (104.0 / 99.0 - 1.0) * 100.0
        self.assertAlmostEqual(metrics["trade_profit_factor"], win / abs(loss), places=6)
        self.assertAlmostEqual(metrics["trade_expectancy_pct"], (win + loss) / 2.0, places=6)
        self.assertAlmostEqual(metrics["avg_trade_win_pct"], win, places=6)
        self.assertAlmostEqual(metrics["avg_trade_loss_pct"], loss, places=6)
        self.assertAlmostEqual(metrics["max_adverse_excursion_pct"], loss, places=6)
        self.assertAlmostEqual(metrics["max_favorable_excursion_pct"], win, places=6)
        self.assertEqual(metrics["time_to_exit_after_risk_trigger_steps"], 0.0)

    def test_classify_recommendation_describes_target_delta(self):
        current = np.array([0.30, 0.20, 0.50], dtype=np.float32)
        self.assertEqual(
            classify_recommendation(current, np.array([0.45, 0.25, 0.30], dtype=np.float32)),
            "recommend_buy",
        )
        self.assertEqual(
            classify_recommendation(current, np.array([0.20, 0.10, 0.70], dtype=np.float32)),
            "recommend_reduce",
        )
        self.assertEqual(
            classify_recommendation(current, np.array([0.0, 0.0, 1.0], dtype=np.float32)),
            "recommend_cash",
        )
        self.assertEqual(
            classify_recommendation(current, np.array([0.31, 0.19, 0.50], dtype=np.float32)),
            "recommend_hold",
        )

    def test_semi_auto_blocks_entry_but_allows_hard_exit_and_locks_reentry(self):
        controller = SemiAutoRiskController()
        current = np.array([0.0, 0.0, 1.0], dtype=np.float32)

        entry, entry_diag = controller.apply(
            target_weights=np.array([0.50, 0.0, 0.50], dtype=np.float32),
            current_weights=current,
            session_drawdown=0.0,
            btc_return_24h=0.0,
        )
        self.assertTrue(entry_diag["human_approval_required"])
        self.assertEqual(entry_diag["recommendation"], "recommend_buy")
        self.assertAlmostEqual(float(entry[-1]), 1.0, places=6)

        exit_weights, exit_diag = controller.apply(
            target_weights=np.array([0.50, 0.0, 0.50], dtype=np.float32),
            current_weights=np.array([0.60, 0.20, 0.20], dtype=np.float32),
            session_drawdown=-0.125,
            btc_return_24h=-0.02,
        )
        self.assertTrue(exit_diag["risk_exit_applied"])
        self.assertTrue(exit_diag["reentry_locked"])
        self.assertLessEqual(float(exit_weights[:-1].sum()), 0.05 + 1e-6)

        reentry, reentry_diag = controller.apply(
            target_weights=np.array([0.30, 0.30, 0.40], dtype=np.float32),
            current_weights=exit_weights,
            session_drawdown=-0.04,
            btc_return_24h=0.02,
        )
        self.assertTrue(reentry_diag["human_approval_required"])
        self.assertTrue(reentry_diag["reentry_locked"])
        self.assertAlmostEqual(float(reentry[-1]), float(exit_weights[-1]), places=6)

        approved, approved_diag = controller.apply(
            target_weights=np.array([0.30, 0.30, 0.40], dtype=np.float32),
            current_weights=exit_weights,
            session_drawdown=-0.04,
            btc_return_24h=0.02,
            human_approved=True,
        )
        self.assertFalse(approved_diag["reentry_locked"])
        self.assertGreater(float(approved[:-1].sum()), float(exit_weights[:-1].sum()))

    def test_live_controller_hard_risk_exit_overrides_deadband(self):
        controller = LiveExecutionController()
        idx = pd.date_range("2026-01-01", periods=25, freq="h", tz="UTC")
        btc = pd.DataFrame(
            {"bb_width": [0.0] * 25, "atr_14": [0.0] * 25, "close": [100.0] * 24 + [91.0]},
            index=idx,
        )
        eth = pd.DataFrame(
            {"bb_width": [0.0] * 25, "atr_14": [0.0] * 25, "close": [50.0] * 25},
            index=idx,
        )
        controller.peak_nav = 100.0

        adjusted, diag = controller.apply(
            target_weights=np.array([0.50, 0.30, 0.20], dtype=np.float32),
            current_weights=np.array([0.50, 0.30, 0.20], dtype=np.float32),
            prices={"BTCUSDT": 91.0, "ETHUSDT": 50.0},
            feature_state={"BTCUSDT": btc, "ETHUSDT": eth},
            nav=91.0,
        )

        self.assertTrue(diag["risk_exit_applied"])
        self.assertEqual(diag["risk_exit_tier"], "severe")
        self.assertLessEqual(float(adjusted[:-1].sum()), 0.15 + 1e-6)
        self.assertFalse(diag["rebalance_blocked_by_deadband"])

    def test_backtest_environment_applies_hard_risk_exit(self):
        idx = pd.date_range("2026-01-01", periods=40, freq="h", tz="UTC")
        base = pd.DataFrame(
            {
                "atr_14": [0.0] * 40,
                "bb_width": [0.0] * 40,
                "macd_1d": [0.0] * 40,
                "raw_dist_sma_200_1d": [0.0] * 40,
                "log_return_1h": [0.0] * 40,
            },
            index=idx,
        )
        data = {"BTCUSDT": base.copy(), "ETHUSDT": base.copy()}
        env = SpotPortfolioEnv(data, initial_capital=100.0, lookback=30, mode="eval")
        env.reset()
        env._weights = np.array([0.50, 0.30, 0.20], dtype=np.float32)
        env._max_portfolio = 100.0
        env._portfolio = 91.0

        _, _, _, _, info = env.step_weights(np.array([0.50, 0.30, 0.20], dtype=np.float32))

        self.assertTrue(info["risk_exit_applied"])
        self.assertEqual(info["risk_exit_tier"], "severe")
        self.assertLessEqual(float(env._weights[:-1].sum()), 0.15 + 1e-6)


if __name__ == "__main__":
    unittest.main()
