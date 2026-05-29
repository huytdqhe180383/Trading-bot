import unittest
from collections import deque

import numpy as np

from agents.ensemble_agent import compute_regime_weighted_scores


class RegimeWeightedTest(unittest.TestCase):
    def test_regime_weighted_matches_base_scores_in_calm_regime(self):
        base_scores = {"PPO": 1.5, "SAC": 0.5}
        returns_history = {
            "PPO": deque([0.001] * 24, maxlen=24),
            "SAC": deque([0.0005] * 24, maxlen=24),
        }

        scores, diagnostics = compute_regime_weighted_scores(
            base_scores=base_scores,
            returns_history=returns_history,
            volatility_z=0.2,
            macro_trend=0.1,
            rolling_drawdown=-0.02,
        )

        self.assertAlmostEqual(scores["PPO"], base_scores["PPO"], places=6)
        self.assertAlmostEqual(scores["SAC"], base_scores["SAC"], places=6)
        self.assertEqual(diagnostics["regime_label"], "calm")

    def test_regime_weighted_shifts_weight_in_stress_regime(self):
        base_scores = {"PPO": 1.0, "SAC": 1.0}
        returns_history = {
            "PPO": deque([0.0008] * 24, maxlen=24),
            "SAC": deque([-0.003, 0.001] * 12, maxlen=24),
        }

        scores, diagnostics = compute_regime_weighted_scores(
            base_scores=base_scores,
            returns_history=returns_history,
            volatility_z=1.5,
            macro_trend=-0.1,
            rolling_drawdown=-0.12,
        )

        self.assertGreater(scores["PPO"], scores["SAC"])
        self.assertEqual(diagnostics["regime_label"], "stress")
        self.assertGreater(diagnostics["stress_strength"], 0.0)


if __name__ == "__main__":
    unittest.main()
