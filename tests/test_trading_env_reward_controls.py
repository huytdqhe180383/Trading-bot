import unittest

import numpy as np
import pandas as pd

from environment.trading_env import SpotPortfolioEnv


def _sample_data(rows: int = 64) -> dict[str, pd.DataFrame]:
    idx = pd.date_range("2026-01-01", periods=rows, freq="h", tz="UTC")
    base = pd.DataFrame(
        {
            "log_return_1h": np.zeros(rows),
            "atr_14": np.zeros(rows),
            "bb_width": np.zeros(rows),
            "raw_dist_sma_200_1d": np.zeros(rows),
        },
        index=idx,
    )
    return {"BTCUSDT": base.copy(), "ETHUSDT": base.copy()}


class TradingEnvRewardControlsTest(unittest.TestCase):
    def test_cash_buffer_and_risk_exposure_reward_controls_shape_survival_bias(self):
        env = SpotPortfolioEnv(
            _sample_data(),
            lookback=30,
            mode="train",
            reward_missed_opportunity_weight=0.0,
            reward_cash_buffer_weight=1.0,
            reward_cash_buffer_threshold=0.5,
            reward_risk_exposure_weight=1.0,
            reward_risk_exposure_threshold=0.2,
            reward_turnover_weight=0.0,
            reward_action_delta_weight=0.0,
        )
        old_weights = np.array([0.0, 0.0, 1.0], dtype=np.float32)

        cash_reward, cash_components = env._compute_reward(
            net_return=1.0,
            transaction_cost=0.0,
            rolling_drawdown=0.0,
            old_weights=old_weights,
            new_weights=np.array([0.1, 0.1, 0.8], dtype=np.float32),
        )
        risk_reward, risk_components = env._compute_reward(
            net_return=1.0,
            transaction_cost=0.0,
            rolling_drawdown=0.0,
            old_weights=old_weights,
            new_weights=np.array([0.7, 0.1, 0.2], dtype=np.float32),
        )

        self.assertAlmostEqual(cash_components["cash_buffer_component"], 0.3, places=6)
        self.assertAlmostEqual(cash_components["risk_exposure_component"], 0.0, places=6)
        self.assertAlmostEqual(risk_components["cash_buffer_component"], 0.0, places=6)
        self.assertAlmostEqual(risk_components["risk_exposure_component"], 0.6, places=6)
        self.assertGreater(cash_reward, risk_reward)

    def test_missed_opportunity_constructor_override_does_not_mutate_default_env(self):
        data = _sample_data()
        data["BTCUSDT"]["raw_dist_sma_200_1d"] = 1.0
        data["ETHUSDT"]["raw_dist_sma_200_1d"] = 1.0
        default_env = SpotPortfolioEnv(data, lookback=30, mode="train")
        relaxed_env = SpotPortfolioEnv(
            data,
            lookback=30,
            mode="train",
            reward_missed_opportunity_weight=0.0,
        )
        old_weights = np.array([0.0, 0.0, 1.0], dtype=np.float32)
        new_weights = np.array([0.0, 0.0, 1.0], dtype=np.float32)

        default_reward, default_components = default_env._compute_reward(
            net_return=1.0,
            transaction_cost=0.0,
            rolling_drawdown=0.0,
            old_weights=old_weights,
            new_weights=new_weights,
        )
        relaxed_reward, relaxed_components = relaxed_env._compute_reward(
            net_return=1.0,
            transaction_cost=0.0,
            rolling_drawdown=0.0,
            old_weights=old_weights,
            new_weights=new_weights,
        )

        self.assertGreater(default_components["opportunity_component"], 0.0)
        self.assertEqual(relaxed_components["opportunity_component"], default_components["opportunity_component"])
        self.assertGreater(relaxed_reward, default_reward)


if __name__ == "__main__":
    unittest.main()
