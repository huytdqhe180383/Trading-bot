import tempfile
import unittest
from pathlib import Path

import pandas as pd

from backtest import (
    TRADE_PROFILES,
    apply_trade_profile_overrides,
    build_arg_parser,
    build_benchmark_nav,
    build_trade_diagnostics_tables,
    create_backtest_session_dir,
    create_best_model_snapshot_dir,
    maybe_save_best_model_snapshot,
    resolve_backtest_model_dir,
    write_trade_decision_log,
)


class BacktestSessionOutputsTest(unittest.TestCase):
    def test_build_arg_parser_accepts_custom_initial_capital(self):
        parser = build_arg_parser()

        args = parser.parse_args(["--initial-capital", "100"])

        self.assertEqual(args.initial_capital, 100.0)

    def test_build_arg_parser_accepts_trade_profile_and_position_cap_mode(self):
        parser = build_arg_parser()

        args = parser.parse_args(["--trade-profile", "aggressive", "--position-cap-mode", "smooth_nav"])

        self.assertEqual(args.trade_profile, "aggressive")
        self.assertEqual(args.position_cap_mode, "smooth_nav")

    def test_build_arg_parser_accepts_june_plunge_replay_window(self):
        parser = build_arg_parser()

        args = parser.parse_args(["--backtest-window", "june_plunge"])

        self.assertEqual(args.backtest_window, "june_plunge")

    def test_apply_trade_profile_overrides_sets_expected_thresholds(self):
        parser = build_arg_parser()
        args = parser.parse_args(["--trade-profile", "moderate"])

        apply_trade_profile_overrides(args)

        self.assertEqual(args.rebalance_threshold_normal, TRADE_PROFILES["moderate"]["rebalance_threshold_normal"])
        self.assertEqual(args.rebalance_threshold_stress, TRADE_PROFILES["moderate"]["rebalance_threshold_stress"])
        self.assertEqual(args.rebalance_threshold_crisis, TRADE_PROFILES["moderate"]["rebalance_threshold_crisis"])
        self.assertEqual(args.material_trade_threshold, TRADE_PROFILES["moderate"]["material_trade_threshold"])

    def test_build_benchmark_nav_scales_with_initial_capital(self):
        idx = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
        test_data = {
            "BTCUSDT": pd.DataFrame({"log_return_1h": [0.0, 0.1, -0.05]}, index=idx),
            "ETHUSDT": pd.DataFrame({"log_return_1h": [0.0, 0.05, -0.02]}, index=idx),
        }

        benchmark = build_benchmark_nav(test_data, initial_capital=100.0)

        self.assertEqual(benchmark.name, "benchmark_nav")
        self.assertEqual(benchmark.index.tolist(), idx.tolist())
        self.assertAlmostEqual(float(benchmark.iloc[0]), 100.0, places=6)

    def test_create_backtest_session_dir_uses_daily_incrementing_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "daily" / "2026-05-24" / "1").mkdir(parents=True)
            (base / "daily" / "2026-05-24" / "not_a_run").mkdir()

            session_dir = create_backtest_session_dir(base, run_date="2026-05-24")

            self.assertEqual(session_dir, base / "daily" / "2026-05-24" / "2")
            self.assertTrue(session_dir.exists())

    def test_write_trade_decision_log_keeps_decision_columns(self):
        idx = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
        episode = pd.DataFrame(
            {
                "portfolio_value": [100.0, 101.0],
                "btc_weight": [0.4, 0.5],
                "eth_weight": [0.3, 0.2],
                "cash_weight": [0.3, 0.3],
                "target_btc_weight": [0.5, 0.6],
                "target_eth_weight": [0.2, 0.1],
                "target_cash_weight": [0.3, 0.3],
                "turnover": [0.0, 0.2],
                "transaction_cost": [0.0, 0.001],
                "kronos_available": [False, True],
                "tradingagents_available": [False, False],
            },
            index=idx,
        )

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "trade_decisions.csv"
            write_trade_decision_log(episode, out)
            saved = pd.read_csv(out)

        self.assertIn("timestamp", saved.columns)
        self.assertIn("target_btc_weight", saved.columns)
        self.assertIn("transaction_cost", saved.columns)
        self.assertEqual(len(saved), 2)

    def test_trade_diagnostics_tables_include_overtrading_columns(self):
        idx = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
        episode = pd.DataFrame(
            {
                "portfolio_value": [100.0, 101.0, 100.5],
                "btc_weight": [0.4, 0.45, 0.35],
                "eth_weight": [0.3, 0.25, 0.30],
                "turnover": [0.0, 0.08, 0.02],
                "transaction_cost": [0.0, 0.001, 0.0005],
                "executed_weight_delta": [0.0, 0.08, 0.02],
                "material_trade_executed": [False, True, False],
                "rebalance_blocked_by_deadband": [False, False, True],
                "rebalance_blocked_by_cooldown": [False, True, False],
                "rebalance_blocked_by_hysteresis": [False, False, True],
                "rebalance_forced_by_governor": [False, False, False],
                "rebalance_forced_by_trailing_stop": [False, False, False],
                "trailing_stop_liquidation_count": [0, 1, 0],
                "position_reset_triggered": [False, False, True],
                "execution_regime_label": ["normal", "stress", "stress"],
                "rl_btc_weight": [0.4, 0.4, 0.4],
                "rl_eth_weight": [0.3, 0.3, 0.3],
            },
            index=idx,
        )

        summary, monthly, regime, block = build_trade_diagnostics_tables(episode)

        self.assertIn("change_rate", summary.columns)
        self.assertIn("sub_threshold_blocked_count", summary.columns)
        self.assertIn("material_trade_count", monthly.columns)
        self.assertIn("blocked_by_cooldown", regime.columns)
        self.assertIn("cooldown_block_rate", block.columns)

    def test_create_best_model_snapshot_dir_uses_daily_incrementing_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "best" / "2026-05-27" / "1").mkdir(parents=True)

            snapshot_dir = create_best_model_snapshot_dir(base, run_date="2026-05-27")

            self.assertEqual(snapshot_dir, base / "best" / "2026-05-27" / "2")
            self.assertTrue(snapshot_dir.exists())

    def test_maybe_save_best_model_snapshot_copies_models_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_models = tmp_path / "models"
            (source_models / "PPO").mkdir(parents=True)
            (source_models / "SAC").mkdir(parents=True)
            (source_models / "PPO" / "ppo_best.zip").write_bytes(b"ppo")
            (source_models / "SAC" / "sac_best.zip").write_bytes(b"sac")

            session_dir = tmp_path / "results" / "daily" / "2026-05-27" / "1"
            session_dir.mkdir(parents=True)

            saved_dir = maybe_save_best_model_snapshot(
                metrics={"total_return_pct": 107.06, "sharpe_ratio": 2.1},
                source_model_dir=source_models,
                best_root_dir=tmp_path / "models",
                run_label="rl_only_live_like_dynamic_weighted",
                session_dir=session_dir,
                run_date="2026-05-27",
            )

            self.assertIsNotNone(saved_dir)
            assert saved_dir is not None
            self.assertTrue((saved_dir / "models" / "PPO" / "ppo_best.zip").exists())
            self.assertTrue((saved_dir / "models" / "SAC" / "sac_best.zip").exists())
            self.assertTrue((saved_dir / "snapshot_metadata.json").exists())

    def test_maybe_save_best_model_snapshot_skips_below_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_models = tmp_path / "models"
            (source_models / "PPO").mkdir(parents=True)
            (source_models / "SAC").mkdir(parents=True)
            (source_models / "PPO" / "ppo_best.zip").write_bytes(b"ppo")
            (source_models / "SAC" / "sac_best.zip").write_bytes(b"sac")

            saved_dir = maybe_save_best_model_snapshot(
                metrics={"total_return_pct": 69.99},
                source_model_dir=source_models,
                best_root_dir=tmp_path / "models",
                run_label="rl_only_live_like_dynamic_weighted",
                session_dir=tmp_path / "results",
                run_date="2026-05-27",
            )

            self.assertIsNone(saved_dir)
            self.assertFalse((tmp_path / "models" / "best" / "2026-05-27").exists())

    def test_resolve_backtest_model_dir_prefers_live_baseline_when_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            live = base / "live_baseline"
            (live / "PPO").mkdir(parents=True)
            (live / "SAC").mkdir(parents=True)
            (live / "PPO" / "ppo_best.zip").write_bytes(b"ppo")
            (live / "SAC" / "sac_best.zip").write_bytes(b"sac")

            resolved = resolve_backtest_model_dir(live)

            self.assertEqual(resolved, live)


if __name__ == "__main__":
    unittest.main()
