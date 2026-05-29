import unittest
from unittest.mock import Mock

import pandas as pd

from train import (
    _load_resumed_model,
    build_parser,
    build_post_training_backtest_command,
    split_train_validation,
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
            ],
        )

    def test_post_training_backtest_accepts_regime_weighted(self):
        args = build_parser().parse_args(["--post-backtest-method", "regime_weighted"])

        self.assertEqual(args.post_backtest_method, "regime_weighted")

    def test_post_training_backtest_can_be_disabled(self):
        args = build_parser().parse_args(["--skip-backtest"])

        self.assertFalse(args.post_training_backtest)

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


if __name__ == "__main__":
    unittest.main()
