import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import data.live_feed as live_feed
import environment.trading_env as trading_env
from data.live_feed import CCXTExchangeGateway
from environment.trading_env import SpotPortfolioEnv


def _sample_data(rows: int = 64) -> dict[str, pd.DataFrame]:
    idx = pd.date_range("2026-01-01", periods=rows, freq="h", tz="UTC")
    base = pd.DataFrame(
        {
            "log_return_1h": np.zeros(rows),
            "atr_14": np.zeros(rows),
            "bb_width": np.zeros(rows),
            "raw_dist_sma_200_1d": np.arange(rows, dtype=float),
        },
        index=idx,
    )
    return {"BTCUSDT": base.copy(), "ETHUSDT": base.copy()}


class AuditHotfixTest(unittest.TestCase):
    def test_market_regime_and_reward_use_completed_bar_macro_trend(self):
        env = SpotPortfolioEnv(_sample_data(), lookback=30, mode="eval")
        env._step_idx = 30
        env._macro_trend_array[29] = 0.0
        env._macro_trend_array[30] = 1.0

        regime = env.get_market_regime()
        _, components = env._compute_reward(
            net_return=1.0,
            transaction_cost=0.0,
            rolling_drawdown=0.0,
            old_weights=np.array([0.0, 0.0, 1.0], dtype=np.float32),
            new_weights=np.array([0.0, 0.0, 1.0], dtype=np.float32),
        )

        self.assertEqual(regime["macro_trend"], 0.0)
        self.assertEqual(components["opportunity_component"], 0.0)

    def test_live_higher_timeframe_features_are_shifted_before_indicators(self):
        idx = pd.date_range("2026-01-01", periods=40, freq="4h", tz="UTC")
        raw = pd.DataFrame(
            {
                "open": np.arange(40, dtype=float),
                "high": np.arange(40, dtype=float),
                "low": np.arange(40, dtype=float),
                "close": np.arange(40, dtype=float),
                "volume": np.ones(40),
            },
            index=idx,
        )
        gateway = object.__new__(CCXTExchangeGateway)
        gateway.timeframe = "4h"
        gateway.lookback_window = 5
        gateway.fetch_raw_ohlcv = lambda: {"BTCUSDT": raw}
        captured = {}

        def fake_add_indicators(frame):
            captured["first_close"] = frame["close"].iloc[0]
            captured["last_close"] = frame["close"].iloc[-1]
            return pd.DataFrame({"feature": np.arange(len(frame), dtype=float)}, index=frame.index)

        with patch.object(live_feed, "_add_indicators", side_effect=fake_add_indicators):
            features = gateway.fetch_feature_state()

        self.assertIsNotNone(features)
        self.assertTrue(np.isnan(captured["first_close"]))
        self.assertEqual(captured["last_close"], 38.0)

    def test_vol_scaled_slippage_is_monotonic_and_capped(self):
        old_model = trading_env.SLIPPAGE_MODEL
        old_scalar = trading_env.SLIPPAGE_VOL_SCALAR
        old_cap = trading_env.SLIPPAGE_VOL_CAP_MULT
        try:
            trading_env.SLIPPAGE_MODEL = "vol_scaled"
            trading_env.SLIPPAGE_VOL_SCALAR = 10_000.0
            trading_env.SLIPPAGE_VOL_CAP_MULT = 2.0
            data = _sample_data()
            for frame in data.values():
                frame["log_return_1h"] = np.log(1.02)
            env = SpotPortfolioEnv(data, lookback=30, slippage=0.001, mode="eval")
            env._step_idx = 40

            effective = env._effective_slippage()

            self.assertGreaterEqual(effective, 0.001)
            self.assertLessEqual(effective, 0.002)
        finally:
            trading_env.SLIPPAGE_MODEL = old_model
            trading_env.SLIPPAGE_VOL_SCALAR = old_scalar
            trading_env.SLIPPAGE_VOL_CAP_MULT = old_cap

    def test_turnover_cap_interpolates_target_weights(self):
        old_enabled = trading_env.STEP_TURNOVER_CAP_ENABLED
        old_normal = trading_env.STEP_TURNOVER_CAP_NORMAL
        try:
            trading_env.STEP_TURNOVER_CAP_ENABLED = True
            trading_env.STEP_TURNOVER_CAP_NORMAL = 0.20
            env = SpotPortfolioEnv(_sample_data(), lookback=30, mode="eval")
            env._weights = np.array([0.0, 0.0, 1.0], dtype=np.float32)
            target = np.array([0.8, 0.0, 0.2], dtype=np.float32)

            capped = env._apply_step_turnover_cap(target)

            self.assertTrue(env._last_turnover_cap_diag["applied"])
            self.assertAlmostEqual(float(capped[0]), 0.20, places=5)
            self.assertAlmostEqual(float(capped[-1]), 0.80, places=5)
        finally:
            trading_env.STEP_TURNOVER_CAP_ENABLED = old_enabled
            trading_env.STEP_TURNOVER_CAP_NORMAL = old_normal

    def test_eval_kill_switch_can_terminate_backtest_episode(self):
        old_enabled = trading_env.KILL_SWITCH_ENABLED_EVAL
        old_threshold = trading_env.KILL_SWITCH_DRAWDOWN_THRESHOLD
        try:
            trading_env.KILL_SWITCH_ENABLED_EVAL = True
            trading_env.KILL_SWITCH_DRAWDOWN_THRESHOLD = -0.005
            data = _sample_data()
            for frame in data.values():
                frame.iloc[29, frame.columns.get_loc("log_return_1h")] = np.log(0.99)
            env = SpotPortfolioEnv(data, lookback=30, mode="eval")
            env._weights = np.array([1.0, 0.0, 0.0], dtype=np.float32)

            _, _, terminated, _, info = env.step_weights(np.array([1.0, 0.0, 0.0], dtype=np.float32))

            self.assertTrue(terminated)
            self.assertLessEqual(info["abs_drawdown"], -0.005)
        finally:
            trading_env.KILL_SWITCH_ENABLED_EVAL = old_enabled
            trading_env.KILL_SWITCH_DRAWDOWN_THRESHOLD = old_threshold

    def test_action_delta_penalty_increases_with_larger_reallocations(self):
        old_weight = trading_env.REWARD_ACTION_DELTA_WEIGHT
        old_deadband = trading_env.REWARD_ACTION_DELTA_DEADBAND
        old_scale = trading_env.REWARD_ACTION_DELTA_SCALE
        try:
            trading_env.REWARD_ACTION_DELTA_WEIGHT = 1.0
            trading_env.REWARD_ACTION_DELTA_DEADBAND = 0.0
            trading_env.REWARD_ACTION_DELTA_SCALE = 1.0
            env = SpotPortfolioEnv(_sample_data(), lookback=30, mode="eval")
            old_weights = np.array([0.2, 0.2, 0.6], dtype=np.float32)

            reward_small, components_small = env._compute_reward(
                net_return=1.0,
                transaction_cost=0.0,
                rolling_drawdown=0.0,
                old_weights=old_weights,
                new_weights=np.array([0.3, 0.2, 0.5], dtype=np.float32),
            )
            reward_large, components_large = env._compute_reward(
                net_return=1.0,
                transaction_cost=0.0,
                rolling_drawdown=0.0,
                old_weights=old_weights,
                new_weights=np.array([0.8, 0.1, 0.1], dtype=np.float32),
            )

            self.assertGreater(components_large["action_delta_component"], components_small["action_delta_component"])
            self.assertLess(reward_large, reward_small)
        finally:
            trading_env.REWARD_ACTION_DELTA_WEIGHT = old_weight
            trading_env.REWARD_ACTION_DELTA_DEADBAND = old_deadband
            trading_env.REWARD_ACTION_DELTA_SCALE = old_scale

    def test_action_delta_deadband_suppresses_tiny_reallocations(self):
        old_weight = trading_env.REWARD_ACTION_DELTA_WEIGHT
        old_deadband = trading_env.REWARD_ACTION_DELTA_DEADBAND
        old_scale = trading_env.REWARD_ACTION_DELTA_SCALE
        try:
            trading_env.REWARD_ACTION_DELTA_WEIGHT = 1.0
            trading_env.REWARD_ACTION_DELTA_DEADBAND = 0.10
            trading_env.REWARD_ACTION_DELTA_SCALE = 1.0
            env = SpotPortfolioEnv(_sample_data(), lookback=30, mode="eval")

            _, components = env._compute_reward(
                net_return=1.0,
                transaction_cost=0.0,
                rolling_drawdown=0.0,
                old_weights=np.array([0.2, 0.2, 0.6], dtype=np.float32),
                new_weights=np.array([0.24, 0.2, 0.56], dtype=np.float32),
            )

            self.assertAlmostEqual(components["raw_action_delta"], 0.04, places=6)
            self.assertAlmostEqual(components["action_delta_component"], 0.0, places=6)
        finally:
            trading_env.REWARD_ACTION_DELTA_WEIGHT = old_weight
            trading_env.REWARD_ACTION_DELTA_DEADBAND = old_deadband
            trading_env.REWARD_ACTION_DELTA_SCALE = old_scale

    def test_stress_threshold_blocks_small_rebalance_even_above_normal_threshold(self):
        old_normal = trading_env.REBALANCE_THRESHOLD_NORMAL
        old_stress = trading_env.REBALANCE_THRESHOLD_STRESS
        old_crisis = trading_env.REBALANCE_THRESHOLD_CRISIS
        try:
            trading_env.REBALANCE_THRESHOLD_NORMAL = 0.03
            trading_env.REBALANCE_THRESHOLD_STRESS = 0.05
            trading_env.REBALANCE_THRESHOLD_CRISIS = 0.08
            env = SpotPortfolioEnv(_sample_data(), lookback=30, mode="eval")
            env._weights = np.array([0.30, 0.30, 0.40], dtype=np.float32)
            env._obs_arrays["BTCUSDT"][env._step_idx - 1, env._bb_width_idx] = 1.5

            _, _, _, _, info = env.step_weights(np.array([0.34, 0.30, 0.36], dtype=np.float32))

            self.assertTrue(info["rebalance_blocked_by_deadband"])
            self.assertAlmostEqual(float(info["requested_weight_delta"]), 0.04, places=5)
            self.assertAlmostEqual(float(info["executed_weight_delta"]), 0.0, places=5)
            self.assertEqual(info["execution_regime_label"], "stress")
        finally:
            trading_env.REBALANCE_THRESHOLD_NORMAL = old_normal
            trading_env.REBALANCE_THRESHOLD_STRESS = old_stress
            trading_env.REBALANCE_THRESHOLD_CRISIS = old_crisis

    def test_cooldown_blocks_repeat_rebalance_but_trailing_stop_can_still_exit(self):
        old_normal = trading_env.REBALANCE_THRESHOLD_NORMAL
        old_hold = trading_env.MIN_HOLD_BARS
        old_material = trading_env.MATERIAL_TRADE_THRESHOLD
        try:
            trading_env.REBALANCE_THRESHOLD_NORMAL = 0.01
            trading_env.MIN_HOLD_BARS = 3
            trading_env.MATERIAL_TRADE_THRESHOLD = 0.05
            data = _sample_data()
            env = SpotPortfolioEnv(data, lookback=30, mode="eval")

            _, _, _, _, info_open = env.step_weights(np.array([0.40, 0.30, 0.30], dtype=np.float32))
            self.assertFalse(info_open["rebalance_blocked_by_cooldown"])
            self.assertTrue(info_open["material_trade_executed"])

            _, _, _, _, info_blocked = env.step_weights(np.array([0.10, 0.10, 0.80], dtype=np.float32))
            self.assertTrue(info_blocked["rebalance_blocked_by_cooldown"])
            self.assertAlmostEqual(float(info_blocked["executed_weight_delta"]), 0.0, places=6)

            env._returns_array[env._step_idx - 1, 0] = 0.80
            env._asset_synthetic_prices[0] = 1.0
            env._asset_highest_prices[0] = 1.0
            _, _, _, _, info_stop = env.step_weights(env._weights.copy())

            self.assertTrue(info_stop["rebalance_forced_by_trailing_stop"])
            self.assertGreaterEqual(int(info_stop["trailing_stop_liquidation_count"]), 1)
            self.assertEqual(float(info_stop["weights"][0]), 0.0)
        finally:
            trading_env.REBALANCE_THRESHOLD_NORMAL = old_normal
            trading_env.MIN_HOLD_BARS = old_hold
            trading_env.MATERIAL_TRADE_THRESHOLD = old_material

    def test_hysteresis_requires_stronger_reversal_than_continuation(self):
        old_normal = trading_env.REBALANCE_THRESHOLD_NORMAL
        old_material = trading_env.MATERIAL_TRADE_THRESHOLD
        old_hysteresis = trading_env.REVERSAL_HYSTERESIS_MULT
        try:
            trading_env.REBALANCE_THRESHOLD_NORMAL = 0.01
            trading_env.MATERIAL_TRADE_THRESHOLD = 0.05
            trading_env.REVERSAL_HYSTERESIS_MULT = 2.0
            env = SpotPortfolioEnv(_sample_data(), lookback=30, mode="eval")
            env._weights = np.array([0.40, 0.20, 0.40], dtype=np.float32)
            env._last_material_trade_direction = np.array([1.0, 0.0], dtype=np.float32)
            env._bars_since_last_material_trade = 10

            _, _, _, _, info = env.step_weights(np.array([0.37, 0.20, 0.43], dtype=np.float32))

            self.assertTrue(info["rebalance_blocked_by_hysteresis"])
            self.assertAlmostEqual(float(info["executed_weight_delta"]), 0.0, places=6)
        finally:
            trading_env.REBALANCE_THRESHOLD_NORMAL = old_normal
            trading_env.MATERIAL_TRADE_THRESHOLD = old_material
            trading_env.REVERSAL_HYSTERESIS_MULT = old_hysteresis

    def test_position_reset_persistence_delays_high_water_reset(self):
        old_threshold = trading_env.POSITION_RESET_WEIGHT_THRESHOLD
        old_persist = trading_env.POSITION_RESET_PERSIST_BARS
        try:
            trading_env.POSITION_RESET_WEIGHT_THRESHOLD = 0.05
            trading_env.POSITION_RESET_PERSIST_BARS = 2
            env = SpotPortfolioEnv(_sample_data(), lookback=30, mode="eval")
            env._weights = np.array([0.02, 0.00, 0.98], dtype=np.float32)
            env._asset_synthetic_prices[0] = 1.95
            env._asset_highest_prices[0] = 2.0

            _, _, _, _, info_first = env.step_weights(env._weights.copy())
            self.assertFalse(info_first["position_reset_triggered"])
            self.assertAlmostEqual(float(env._asset_highest_prices[0]), 2.0, places=6)

            _, _, _, _, info_second = env.step_weights(env._weights.copy())
            self.assertTrue(info_second["position_reset_triggered"])
            self.assertAlmostEqual(float(env._asset_highest_prices[0]), 1.95, places=6)
        finally:
            trading_env.POSITION_RESET_WEIGHT_THRESHOLD = old_threshold
            trading_env.POSITION_RESET_PERSIST_BARS = old_persist

    def test_step_weights_blocks_subminimum_notional_rebalance(self):
        env = SpotPortfolioEnv(_sample_data(), lookback=30, initial_capital=100.0, mode="eval")

        _, _, _, _, info = env.step_weights(np.array([0.05, 0.0, 0.95], dtype=np.float32))

        self.assertTrue(info["rebalance_blocked_by_min_notional"])
        self.assertEqual(info["min_notional_blocked_count"], 1)
        self.assertEqual(info["min_notional_blocked_assets"], "BTCUSDT")
        self.assertAlmostEqual(float(info["weights"][0]), 0.0, places=6)
        self.assertAlmostEqual(float(info["weights"][1]), 0.0, places=6)
        self.assertAlmostEqual(float(info["weights"][2]), 1.0, places=6)

    def test_step_weights_executes_tradeable_legs_and_blocks_dust_legs(self):
        env = SpotPortfolioEnv(_sample_data(), lookback=30, initial_capital=100.0, mode="eval")

        _, _, _, _, info = env.step_weights(np.array([0.12, 0.06, 0.82], dtype=np.float32))

        self.assertTrue(info["rebalance_blocked_by_min_notional"])
        self.assertEqual(info["min_notional_blocked_count"], 1)
        self.assertEqual(info["min_notional_blocked_assets"], "ETHUSDT")
        self.assertAlmostEqual(float(info["weights"][0]), 0.12, places=6)
        self.assertAlmostEqual(float(info["weights"][1]), 0.0, places=6)
        self.assertAlmostEqual(float(info["weights"][2]), 0.88, places=6)


if __name__ == "__main__":
    unittest.main()
