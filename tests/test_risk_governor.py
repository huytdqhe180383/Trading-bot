import unittest

import numpy as np

from risk.risk_constraints import apply_stress_risk_governor


class RiskGovernorTest(unittest.TestCase):
    def test_governor_is_noop_in_calm_regime(self):
        weights = np.array([0.45, 0.45, 0.10], dtype=np.float32)

        governed, diag = apply_stress_risk_governor(
            weights=weights,
            n_assets=2,
            volatility_z=0.2,
            drawdown=-0.02,
            vol_z_threshold=1.0,
            drawdown_threshold=-0.08,
            crisis_drawdown_threshold=-0.15,
            stress_cash_floor=0.25,
            crisis_cash_floor=0.45,
            stress_max_risk_on=0.75,
            crisis_max_risk_on=0.55,
        )

        np.testing.assert_allclose(governed, weights, atol=1e-6)
        self.assertFalse(diag["active"])

    def test_governor_raises_cash_and_caps_risk_on_in_stress(self):
        weights = np.array([0.60, 0.35, 0.05], dtype=np.float32)

        governed, diag = apply_stress_risk_governor(
            weights=weights,
            n_assets=2,
            volatility_z=1.5,
            drawdown=-0.10,
            vol_z_threshold=1.0,
            drawdown_threshold=-0.08,
            crisis_drawdown_threshold=-0.15,
            stress_cash_floor=0.25,
            crisis_cash_floor=0.45,
            stress_max_risk_on=0.75,
            crisis_max_risk_on=0.55,
        )

        self.assertTrue(diag["active"])
        self.assertGreaterEqual(float(governed[-1]), 0.25)
        self.assertLessEqual(float(governed[:-1].sum()), 0.75)
        self.assertAlmostEqual(float(governed.sum()), 1.0, places=6)

    def test_governor_uses_crisis_limits_for_deep_drawdown(self):
        weights = np.array([0.50, 0.45, 0.05], dtype=np.float32)

        governed, diag = apply_stress_risk_governor(
            weights=weights,
            n_assets=2,
            volatility_z=0.2,
            drawdown=-0.20,
            vol_z_threshold=1.0,
            drawdown_threshold=-0.08,
            crisis_drawdown_threshold=-0.15,
            stress_cash_floor=0.25,
            crisis_cash_floor=0.45,
            stress_max_risk_on=0.75,
            crisis_max_risk_on=0.55,
        )

        self.assertTrue(diag["active"])
        self.assertIn("crisis_drawdown", diag["reason"])
        self.assertGreaterEqual(float(governed[-1]), 0.45)
        self.assertLessEqual(float(governed[:-1].sum()), 0.55)


if __name__ == "__main__":
    unittest.main()
