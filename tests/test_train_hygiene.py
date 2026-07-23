import unittest
from unittest.mock import Mock
from unittest.mock import patch

import pandas as pd

from config import MODELS_DIR
from train import (
    build_rolling_validation_windows,
    _load_resumed_model,
    _resolve_tensorboard_log_dir,
    build_parser,
    build_post_training_backtest_command,
    parse_validation_cost_profiles,
    RollingValidationCallback,
    summarize_validation_windows,
    split_train_validation,
    validation_selection_score,
)


class TrainHygieneTest(unittest.TestCase):
    def test_split_train_validation_is_chronological(self):
        idx = pd.date_range("2024-01-01", periods=10, freq="h", tz="UTC")
        data = {
            "BTCUSDT": pd.DataFrame({"x": range(10)}, index=idx),
            "ETHUSDT": pd.DataFrame({"x": range(10, 20)}, index=idx),
        }

        train_data, validation_data = split_train_validation(data, 0.2)

        self.assertEqual(len(train_data["BTCUSDT"]), 8)
        self.assertEqual(len(validation_data["BTCUSDT"]), 2)
        self.assertLess(train_data["BTCUSDT"].index[-1], validation_data["BTCUSDT"].index[0])
        self.assertEqual(validation_data["ETHUSDT"]["x"].tolist(), [18, 19])

    def test_rolling_validation_windows_are_distinct_and_chronological(self):
        idx = pd.date_range("2024-01-01", periods=12, freq="h", tz="UTC")
        data = {
            "BTCUSDT": pd.DataFrame({"x": range(12)}, index=idx),
            "ETHUSDT": pd.DataFrame({"x": range(100, 112)}, index=idx),
        }

        windows = build_rolling_validation_windows(data, n_windows=3, min_rows=3)
        summaries = summarize_validation_windows(windows)

        self.assertEqual(len(windows), 3)
        self.assertEqual([summary["rows"] for summary in summaries], [4, 4, 4])
        self.assertLess(windows[0]["BTCUSDT"].index[-1], windows[1]["BTCUSDT"].index[0])
        self.assertLess(windows[1]["BTCUSDT"].index[-1], windows[2]["BTCUSDT"].index[0])
        self.assertEqual(windows[2]["ETHUSDT"]["x"].tolist(), [108, 109, 110, 111])

    def test_rolling_validation_windows_fall_back_when_data_is_too_short(self):
        idx = pd.date_range("2024-01-01", periods=5, freq="h", tz="UTC")
        data = {
            "BTCUSDT": pd.DataFrame({"x": range(5)}, index=idx),
            "ETHUSDT": pd.DataFrame({"x": range(10, 15)}, index=idx),
        }

        windows = build_rolling_validation_windows(data, n_windows=5, min_rows=6)

        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]["BTCUSDT"].index.tolist(), idx.tolist())

    def test_parser_accepts_validation_windows(self):
        args = build_parser().parse_args(["--validation-windows", "7"])

        self.assertEqual(args.validation_windows, 7)

    def test_parse_validation_cost_profiles(self):
        profiles = parse_validation_cost_profiles("nominal:0.0012:0.0018,stress2x:0.0024:0.0036")

        self.assertEqual([profile.label for profile in profiles], ["nominal", "stress2x"])
        self.assertEqual(profiles[0].fee, 0.0012)
        self.assertEqual(profiles[1].slippage, 0.0036)

        with self.assertRaises(Exception):
            parse_validation_cost_profiles("bad:0.001")
        with self.assertRaises(Exception):
            parse_validation_cost_profiles("bad:-0.001:0.002")

    def test_validation_selection_score_can_use_worst_profile_mean(self):
        score = validation_selection_score(
            profile_mean_rewards={"nominal": 10.0, "stress2x": -5.0},
            all_rewards=[12.0, 8.0, -4.0, -6.0],
            mode="worst_profile_mean",
        )

        self.assertEqual(score, -5.0)

    def test_rolling_validation_early_stop_triggers_at_patience_boundary(self):
        callback = RollingValidationCallback(
            validation_windows=[],
            best_model_save_path="models/PPO",
            algo="PPO",
            eval_freq=1,
            max_no_improvement_evals=1,
            min_evals=2,
            verbose=0,
        )
        callback.eval_count = 2
        callback.no_improvement_evals = 1

        self.assertTrue(callback.should_stop_early())

        callback.no_improvement_evals = 0
        self.assertFalse(callback.should_stop_early())

    def test_parser_accepts_cost_aware_validation_options(self):
        args = build_parser().parse_args(
            [
                "--validation-cost-profiles",
                "nominal:0.0012:0.0018,stress2x:0.0024:0.0036",
                "--validation-score-mode",
                "worst_profile_mean",
                "--validation-early-stop-patience",
                "1",
                "--validation-early-stop-min-evals",
                "2",
                "--training-fee",
                "0.0024",
                "--training-slippage",
                "0.0036",
            ]
        )

        self.assertEqual(args.validation_score_mode, "worst_profile_mean")
        self.assertEqual(args.validation_cost_profiles[1].label, "stress2x")
        self.assertEqual(args.validation_early_stop_patience, 1)
        self.assertEqual(args.validation_early_stop_min_evals, 2)
        self.assertEqual(args.training_fee, 0.0024)
        self.assertEqual(args.training_slippage, 0.0036)

    def test_parser_accepts_training_reward_and_turnover_cap_options(self):
        args = build_parser().parse_args(
            [
                "--training-reward-turnover-weight",
                "5.0",
                "--training-reward-action-delta-weight",
                "2.0",
                "--training-reward-action-delta-deadband",
                "0.0",
                "--training-reward-action-delta-scale",
                "1.5",
                "--training-step-turnover-cap",
                "--training-step-turnover-cap-normal",
                "0.15",
                "--training-step-turnover-cap-stress",
                "0.10",
                "--training-step-turnover-cap-crisis",
                "0.06",
                "--training-rebalance-threshold-normal",
                "0.08",
                "--training-rebalance-threshold-stress",
                "0.12",
                "--training-rebalance-threshold-crisis",
                "0.18",
                "--training-min-hold-bars",
                "8",
                "--training-material-trade-threshold",
                "0.10",
                "--training-reversal-hysteresis-mult",
                "2.0",
            ]
        )

        self.assertEqual(args.training_reward_turnover_weight, 5.0)
        self.assertEqual(args.training_reward_action_delta_weight, 2.0)
        self.assertEqual(args.training_reward_action_delta_deadband, 0.0)
        self.assertEqual(args.training_reward_action_delta_scale, 1.5)
        self.assertTrue(args.training_step_turnover_cap)
        self.assertEqual(args.training_step_turnover_cap_normal, 0.15)
        self.assertEqual(args.training_step_turnover_cap_stress, 0.10)
        self.assertEqual(args.training_step_turnover_cap_crisis, 0.06)
        self.assertEqual(args.training_rebalance_threshold_normal, 0.08)
        self.assertEqual(args.training_rebalance_threshold_stress, 0.12)
        self.assertEqual(args.training_rebalance_threshold_crisis, 0.18)
        self.assertEqual(args.training_min_hold_bars, 8)
        self.assertEqual(args.training_material_trade_threshold, 0.10)
        self.assertEqual(args.training_reversal_hysteresis_mult, 2.0)

    def test_post_training_backtest_defaults_to_dynamic_rl_only(self):
        args = build_parser().parse_args([])

        self.assertTrue(args.post_training_backtest)
        self.assertEqual(args.post_backtest_pipeline, "rl_only")
        self.assertEqual(args.post_backtest_realism_profile, "live_like")
        self.assertEqual(args.post_backtest_method, "dynamic_weighted")

        command = build_post_training_backtest_command(args)

        self.assertEqual(
            command,
            [
                "backtest.py",
                "--pipeline",
                "rl_only",
                "--realism-profile",
                "live_like",
                "--method",
                "dynamic_weighted",
                "--model-dir",
                str(MODELS_DIR),
            ],
        )

    def test_post_training_backtest_accepts_regime_weighted(self):
        args = build_parser().parse_args(["--post-backtest-method", "regime_weighted"])

        self.assertEqual(args.post_backtest_method, "regime_weighted")

    def test_post_training_backtest_can_be_disabled(self):
        args = build_parser().parse_args(["--skip-backtest"])

        self.assertFalse(args.post_training_backtest)

    def test_post_training_backtest_forwards_turnover_cap_controls(self):
        args = build_parser().parse_args(
            [
                "--training-step-turnover-cap",
                "--training-step-turnover-cap-normal",
                "0.15",
                "--training-step-turnover-cap-stress",
                "0.10",
                "--training-step-turnover-cap-crisis",
                "0.06",
                "--training-rebalance-threshold-normal",
                "0.08",
                "--training-rebalance-threshold-stress",
                "0.12",
                "--training-rebalance-threshold-crisis",
                "0.18",
                "--training-min-hold-bars",
                "8",
                "--training-material-trade-threshold",
                "0.10",
                "--training-reversal-hysteresis-mult",
                "2.0",
            ]
        )

        command = build_post_training_backtest_command(args)

        self.assertIn("--step-turnover-cap-enabled", command)
        self.assertIn("--step-turnover-cap-normal", command)
        self.assertIn("0.15", command)
        self.assertIn("--step-turnover-cap-stress", command)
        self.assertIn("0.1", command)
        self.assertIn("--step-turnover-cap-crisis", command)
        self.assertIn("0.06", command)
        self.assertIn("--rebalance-threshold-normal", command)
        self.assertIn("0.08", command)
        self.assertIn("--rebalance-threshold-stress", command)
        self.assertIn("0.12", command)
        self.assertIn("--rebalance-threshold-crisis", command)
        self.assertIn("0.18", command)
        self.assertIn("--min-hold-bars", command)
        self.assertIn("8", command)
        self.assertIn("--material-trade-threshold", command)
        self.assertIn("0.1", command)
        self.assertIn("--reversal-hysteresis-mult", command)
        self.assertIn("2.0", command)

    def test_load_resumed_model_reapplies_requested_seed(self):
        cls = Mock()
        model = Mock()
        cls.load.return_value = model

        loaded = _load_resumed_model(
            cls,
            checkpoint="models/PPO/ppo_best.zip",
            env="env",
            device="cpu",
            tensorboard_log="logs/tensorboard",
            seed=2026,
        )

        self.assertIs(loaded, model)
        cls.load.assert_called_once()
        model.set_random_seed.assert_called_once_with(2026)

    def test_tensorboard_log_dir_is_disabled_when_package_missing(self):
        with patch("train.importlib.util.find_spec", return_value=None):
            self.assertIsNone(_resolve_tensorboard_log_dir())


if __name__ == "__main__":
    unittest.main()
