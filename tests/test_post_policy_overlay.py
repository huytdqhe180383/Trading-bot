import unittest

import numpy as np

from risk.post_policy_overlay import apply_post_policy_overlay


class PostPolicyOverlayTest(unittest.TestCase):
    def test_overlay_de_risks_when_realized_vol_exceeds_target(self):
        current = np.array([0.40, 0.40, 0.20], dtype=np.float32)
        target = np.array([0.55, 0.35, 0.10], dtype=np.float32)

        weights, diag = apply_post_policy_overlay(
            target_weights=target,
            current_weights=current,
            realized_volatility=0.08,
            target_volatility=0.04,
            macro_trend=0.10,
            current_drawdown=-0.02,
            persistence_turnover_cap=1.0,
        )

        self.assertLess(float(weights[:-1].sum()), float(target[:-1].sum()))
        self.assertGreater(float(weights[-1]), float(target[-1]))
        self.assertLess(diag["volatility_scale"], 1.0)

    def test_overlay_caps_turnover_for_action_persistence(self):
        current = np.array([0.05, 0.05, 0.90], dtype=np.float32)
        target = np.array([0.80, 0.15, 0.05], dtype=np.float32)

        weights, diag = apply_post_policy_overlay(
            target_weights=target,
            current_weights=current,
            realized_volatility=0.02,
            target_volatility=0.04,
            macro_trend=0.20,
            current_drawdown=-0.01,
            persistence_turnover_cap=0.20,
        )

        self.assertLessEqual(diag["turnover_after"], 0.20 + 1e-6)
        self.assertLess(diag["turnover_after"], diag["turnover_before"])

    def test_overlay_trend_gate_raises_cash_in_negative_macro_regime(self):
        current = np.array([0.45, 0.40, 0.15], dtype=np.float32)
        target = np.array([0.50, 0.40, 0.10], dtype=np.float32)

        weights, diag = apply_post_policy_overlay(
            target_weights=target,
            current_weights=current,
            realized_volatility=0.02,
            target_volatility=0.04,
            macro_trend=-0.15,
            current_drawdown=-0.03,
            persistence_turnover_cap=1.0,
        )

        self.assertTrue(diag["trend_gate_applied"])
        self.assertGreater(float(weights[-1]), float(target[-1]))


if __name__ == "__main__":
    unittest.main()
