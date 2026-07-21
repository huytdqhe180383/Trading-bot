import math
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from backtest import (
    REALISM,
    TRADE_PROFILES,
    append_backtest_trial_registry,
    apply_realism_overrides,
    apply_trade_profile_overrides,
    build_block_bootstrap_statistical_report,
    build_backtest_provenance,
    build_arg_parser,
    build_backtest_trial_registry_row,
    build_baseline_metrics_table,
    build_baseline_navs,
    build_benchmark_nav,
    build_trade_diagnostics_tables,
    create_backtest_session_dir,
    create_best_model_snapshot_dir,
    maybe_save_best_model_snapshot,
    resolve_backtest_model_dir,
    write_backtest_reliability_artifacts,
    write_backtest_statistical_report,
    write_trade_decision_log,
)


class BacktestSessionOutputsTest(unittest.TestCase):
    def test_build_arg_parser_accepts_custom_initial_capital(self):
        parser = build_arg_parser()

        args = parser.parse_args(["--initial-capital", "100"])

        self.assertEqual(args.initial_capital, 100.0)

    def test_build_arg_parser_accepts_realism_cost_overrides(self):
        parser = build_arg_parser()

        args = parser.parse_args(
            [
                "--realism-profile",
                "live_like",
                "--fee-override",
                "0.004",
                "--slippage-override",
                "0.005",
                "--latency-steps-override",
                "3",
            ]
        )

        self.assertEqual(args.fee_override, 0.004)
        self.assertEqual(args.slippage_override, 0.005)
        self.assertEqual(args.latency_steps_override, 3)

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

    def test_apply_realism_overrides_updates_selected_profile_only(self):
        parser = build_arg_parser()
        args = parser.parse_args(
            [
                "--realism-profile",
                "live_like",
                "--fee-override",
                "0.004",
                "--slippage-override",
                "0.005",
                "--latency-steps-override",
                "3",
            ]
        )
        old_live_like = dict(REALISM["live_like"])
        old_baseline = dict(REALISM["baseline"])
        try:
            apply_realism_overrides(args)

            self.assertEqual(REALISM["live_like"]["fee"], 0.004)
            self.assertEqual(REALISM["live_like"]["slippage"], 0.005)
            self.assertEqual(REALISM["live_like"]["latency_steps"], 3)
            self.assertEqual(REALISM["baseline"], old_baseline)
        finally:
            REALISM["live_like"] = old_live_like
            REALISM["baseline"] = old_baseline

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

    def test_build_baseline_navs_align_after_lookback_warmup(self):
        idx = pd.date_range("2026-01-01", periods=4, freq="h", tz="UTC")
        test_data = {
            "BTCUSDT": pd.DataFrame({"log_return_1h": [0.0, 0.1, -0.05, 0.02]}, index=idx),
            "ETHUSDT": pd.DataFrame({"log_return_1h": [0.0, 0.05, -0.02, 0.01]}, index=idx),
        }

        navs = build_baseline_navs(test_data, initial_capital=100.0, warmup_steps=2)

        self.assertEqual(navs["cash"].index.tolist(), idx[2:].tolist())
        self.assertAlmostEqual(float(navs["cash"].iloc[-1]), 100.0, places=6)
        expected_btc = 100.0 * math.exp(-0.05) * math.exp(0.02)
        self.assertAlmostEqual(float(navs["btcusdt_buy_and_hold"].iloc[-1]), expected_btc, places=6)

    def test_baseline_metrics_table_contains_required_baselines(self):
        idx = pd.date_range("2026-01-01", periods=4, freq="h", tz="UTC")
        test_data = {
            "BTCUSDT": pd.DataFrame({"log_return_1h": [0.0, 0.1, -0.05, 0.02]}, index=idx),
            "ETHUSDT": pd.DataFrame({"log_return_1h": [0.0, 0.05, -0.02, 0.01]}, index=idx),
        }

        table = build_baseline_metrics_table(test_data, initial_capital=100.0, warmup_steps=1)

        self.assertEqual(
            set(table["baseline"]),
            {
                "cash",
                "btcusdt_buy_and_hold",
                "ethusdt_buy_and_hold",
                "equal_weight_hourly_rebalanced_before_costs",
            },
        )
        self.assertIn("total_return_pct", table.columns)
        self.assertTrue((table["rows"] == 3).all())

    def test_write_backtest_reliability_artifacts_outputs_baselines_and_provenance(self):
        idx = pd.date_range("2026-01-01", periods=4, freq="h", tz="UTC")
        test_data = {
            "BTCUSDT": pd.DataFrame({"log_return_1h": [0.0, 0.1, -0.05, 0.02]}, index=idx),
            "ETHUSDT": pd.DataFrame({"log_return_1h": [0.0, 0.05, -0.02, 0.01]}, index=idx),
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            model_dir = out / "models"
            (model_dir / "PPO").mkdir(parents=True)
            (model_dir / "SAC").mkdir(parents=True)
            (model_dir / "PPO" / "ppo_best.zip").write_bytes(b"ppo")
            (model_dir / "SAC" / "sac_best.zip").write_bytes(b"sac")

            write_backtest_reliability_artifacts(
                test_data=test_data,
                output_dir=out,
                initial_capital=100.0,
                model_dir=model_dir,
                backtest_window="unit",
            )

            baselines = pd.read_csv(out / "backtest_baselines.csv")
            provenance = (out / "backtest_provenance.json").read_text(encoding="utf-8")

        self.assertIn("cash", set(baselines["baseline"]))
        self.assertIn("feature_schema_sha256", provenance)

    def test_backtest_provenance_records_model_hashes(self):
        idx = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
        test_data = {
            "BTCUSDT": pd.DataFrame({"log_return_1h": [0.0, 0.1]}, index=idx),
            "ETHUSDT": pd.DataFrame({"log_return_1h": [0.0, 0.05]}, index=idx),
        }
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp) / "models"
            (model_dir / "PPO").mkdir(parents=True)
            (model_dir / "SAC").mkdir(parents=True)
            (model_dir / "PPO" / "ppo_best.zip").write_bytes(b"ppo")
            (model_dir / "SAC" / "sac_best.zip").write_bytes(b"sac")

            provenance = build_backtest_provenance(
                test_data=test_data,
                model_dir=model_dir,
                backtest_window="unit",
            )

        self.assertEqual(provenance["backtest_window"], "unit")
        self.assertTrue(provenance["models"]["ppo_best"]["exists"])
        self.assertEqual(len(provenance["feature_schema_sha256"]), 64)

    def test_backtest_trial_registry_row_contains_hashes_gates_and_metrics(self):
        provenance = {
            "backtest_window": "unit",
            "feature_schema_sha256": "a" * 64,
            "data": {"BTCUSDT": {"data_sha256": "btc_hash"}},
            "models": {"ppo_best": {"sha256": "ppo_hash"}},
            "model_dir": "models/unit",
        }

        row = build_backtest_trial_registry_row(
            session_dir=Path("results/daily/2026-01-01/1"),
            run_label="rl_only_live_like_dynamic_weighted",
            metrics={"total_return_pct": 1.5, "sharpe_ratio": 0.2},
            meta={
                "pipeline": "rl_only",
                "method": "dynamic_weighted",
                "realism_profile": "live_like",
                "initial_capital": 100.0,
            },
            provenance=provenance,
        )

        self.assertEqual(row["run_label"], "rl_only_live_like_dynamic_weighted")
        self.assertEqual(row["backtest_window"], "unit")
        self.assertIn("btc_hash", row["data_hashes_json"])
        self.assertIn("ppo_hash", row["model_hashes_json"])
        self.assertIn("promotion_status", row["gate_status_json"])
        self.assertEqual(row["total_return_pct"], 1.5)

    def test_append_backtest_trial_registry_appends_to_daily_file(self):
        provenance = {
            "backtest_window": "unit",
            "feature_schema_sha256": "a" * 64,
            "data": {"BTCUSDT": {"data_sha256": "btc_hash"}},
            "models": {"ppo_best": {"sha256": "ppo_hash"}},
            "model_dir": "models/unit",
        }
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "daily" / "2026-01-01" / "1"
            session_dir.mkdir(parents=True)

            append_backtest_trial_registry(
                session_dir=session_dir,
                run_label="first",
                metrics={"total_return_pct": 1.0},
                meta={"pipeline": "rl_only"},
                provenance=provenance,
            )
            append_backtest_trial_registry(
                session_dir=session_dir,
                run_label="second",
                metrics={"total_return_pct": 2.0},
                meta={"pipeline": "rl_only"},
                provenance=provenance,
            )

            registry = pd.read_csv(session_dir.parent / "backtest_trial_registry.csv")

        self.assertEqual(registry["run_label"].tolist(), ["first", "second"])
        self.assertEqual(registry["total_return_pct"].tolist(), [1.0, 2.0])

    def test_block_bootstrap_statistical_report_contains_intervals_and_baseline_odds(self):
        idx = pd.date_range("2026-01-01", periods=6, freq="h", tz="UTC")
        episode = pd.DataFrame({"portfolio_value": [100.0, 101.0, 100.5, 102.0, 103.0, 102.5]}, index=idx)
        baselines = {
            "cash": pd.Series([100.0] * len(idx), index=idx),
            "buy_and_hold": pd.Series([100.0, 100.4, 100.6, 101.0, 100.8, 101.2], index=idx),
        }

        report = build_block_bootstrap_statistical_report(
            episode_df=episode,
            baseline_navs=baselines,
            initial_capital=100.0,
            seed=7,
            n_bootstrap=50,
            block_size=2,
        )

        self.assertEqual(report["method"], "circular_block_bootstrap")
        self.assertEqual(report["parameters"]["n_bootstrap"], 50)
        self.assertIn("p2_5", report["strategy"]["bootstrap_ci"]["total_return_pct"])
        self.assertIn("cash", report["baselines"])
        self.assertIn(
            "total_return_pct",
            report["baselines"]["cash"]["probability_strategy_beats_baseline"],
        )
        self.assertEqual(report["gate_status"]["statistical_uncertainty"], "partial")

    def test_block_bootstrap_statistical_report_handles_block_larger_than_series(self):
        idx = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
        episode = pd.DataFrame({"portfolio_value": [100.0, 100.5]}, index=idx)

        report = build_block_bootstrap_statistical_report(
            episode_df=episode,
            baseline_navs={"cash": pd.Series([100.0, 100.0], index=idx)},
            initial_capital=100.0,
            n_bootstrap=10,
            block_size=99,
        )

        self.assertEqual(report["sample"]["effective_block_size"], 2)
        self.assertIsNotNone(report["strategy"]["bootstrap_ci"]["total_return_pct"]["median"])

    def test_write_backtest_statistical_report_outputs_json(self):
        idx = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
        episode = pd.DataFrame({"portfolio_value": [100.0, 101.0, 102.0]}, index=idx)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_backtest_statistical_report(
                episode_df=episode,
                baseline_navs={"cash": pd.Series([100.0, 100.0, 100.0], index=idx)},
                output_dir=out,
                initial_capital=100.0,
                n_bootstrap=10,
                block_size=2,
            )

            payload = (out / "backtest_statistical_report.json").read_text(encoding="utf-8")

        self.assertIn("circular_block_bootstrap", payload)
        self.assertIn("probability_strategy_beats_baseline", payload)

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
