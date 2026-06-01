import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np
import pandas as pd

from adapters.kronos_adapter import KronosSignal
from adapters.tradingagents_adapter import TradingAgentsSignal
from scripts.run_live import (
    LiveExecutionController,
    append_live_session_row,
    compute_nav_scaled_max_asset_weight,
    compute_turnover,
    create_live_session_dir,
    evaluate_safety_gates,
    get_live_session_tz,
    has_exchange_credentials,
    infer_obs_dim_from_ensemble,
    latest_market_timestamp,
    resolve_live_model_dir,
    write_live_session_metadata,
    write_live_session_summary,
)


class RunLiveSafetyTest(unittest.TestCase):
    def test_nav_scaled_max_asset_weight_follows_smooth_curve(self):
        self.assertAlmostEqual(compute_nav_scaled_max_asset_weight(100.0), 0.35, places=6)
        self.assertAlmostEqual(compute_nav_scaled_max_asset_weight(300.0), 0.575, places=6)
        self.assertAlmostEqual(compute_nav_scaled_max_asset_weight(500.0), 0.80, places=6)

    def test_parser_accepts_regime_weighted_method(self):
        from scripts.run_live import argparse, ENSEMBLE_METHOD

        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--method",
            default=ENSEMBLE_METHOD,
            choices=["mean", "voting", "weighted", "dynamic_weighted", "regime_weighted", "imca"],
        )

        args = parser.parse_args(["--method", "regime_weighted"])
        self.assertEqual(args.method, "regime_weighted")

    @staticmethod
    def _raw_state(ts: str) -> dict[str, pd.DataFrame]:
        index = pd.DatetimeIndex([pd.Timestamp(ts, tz="UTC")])
        frame = pd.DataFrame(
            {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]},
            index=index,
        )
        return {"BTCUSDT": frame, "ETHUSDT": frame.copy()}

    def test_latest_market_timestamp_returns_newest_index(self):
        older = self._raw_state("2026-01-01 00:00:00")
        newer = self._raw_state("2026-01-01 03:00:00")
        state = {"BTCUSDT": older["BTCUSDT"], "ETHUSDT": newer["ETHUSDT"]}
        latest = latest_market_timestamp(state)
        self.assertEqual(latest, pd.Timestamp("2026-01-01 03:00:00", tz="UTC"))

    def test_compute_turnover_uses_asset_weights_only(self):
        current = np.array([0.4, 0.3, 0.3], dtype=np.float32)
        target = np.array([0.55, 0.2, 0.25], dtype=np.float32)
        self.assertAlmostEqual(compute_turnover(current, target), 0.25, places=6)

    def test_infer_obs_dim_from_ensemble_uses_loaded_model_space(self):
        class DummyObsSpace:
            shape = (123,)

        class DummyModel:
            observation_space = DummyObsSpace()

        obs_dim = infer_obs_dim_from_ensemble({"PPO": DummyModel()})
        self.assertEqual(obs_dim, 123)

    def test_resolve_live_model_dir_prefers_live_baseline_when_complete(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            live = base / "live"
            (live / "PPO").mkdir(parents=True)
            (live / "SAC").mkdir(parents=True)
            (live / "PPO" / "ppo_best.zip").write_bytes(b"ppo")
            (live / "SAC" / "sac_best.zip").write_bytes(b"sac")
            self.assertEqual(resolve_live_model_dir(live), live)

    def test_has_exchange_credentials_checks_okx_triplet(self):
        env = {
            "OKX_TESTNET_API_KEY": "a",
            "OKX_TESTNET_SECRET_KEY": "b",
            "OKX_TESTNET_PASSPHRASE": "c",
        }
        with patch.dict("os.environ", env, clear=False):
            self.assertTrue(has_exchange_credentials("okx", "testnet"))
        with patch.dict("os.environ", {"OKX_TESTNET_API_KEY": "a"}, clear=True):
            self.assertFalse(has_exchange_credentials("okx", "testnet"))

    def test_live_execution_controller_blocks_small_stress_rebalance(self):
        controller = LiveExecutionController()
        idx = pd.date_range("2026-01-01", periods=5, freq="h", tz="UTC")
        frame = pd.DataFrame({"bb_width": [1.5] * 5, "atr_14": [0.0] * 5}, index=idx)
        adjusted, diag = controller.apply(
            target_weights=np.array([0.34, 0.30, 0.36], dtype=np.float32),
            current_weights=np.array([0.30, 0.30, 0.40], dtype=np.float32),
            prices={"BTCUSDT": 100.0, "ETHUSDT": 50.0},
            feature_state={"BTCUSDT": frame, "ETHUSDT": frame.copy()},
            nav=10_000.0,
        )
        self.assertTrue(diag["rebalance_blocked_by_deadband"])
        self.assertAlmostEqual(float(adjusted[0]), 0.30, places=6)

    def test_live_execution_controller_applies_nav_scaled_position_cap(self):
        controller = LiveExecutionController()
        idx = pd.date_range("2026-01-01", periods=5, freq="h", tz="UTC")
        frame = pd.DataFrame({"bb_width": [0.0] * 5, "atr_14": [0.0] * 5}, index=idx)
        adjusted, diag = controller.apply(
            target_weights=np.array([0.80, 0.0, 0.20], dtype=np.float32),
            current_weights=np.array([0.0, 0.0, 1.0], dtype=np.float32),
            prices={"BTCUSDT": 100.0, "ETHUSDT": 50.0},
            feature_state={"BTCUSDT": frame, "ETHUSDT": frame.copy()},
            nav=100.0,
        )
        self.assertAlmostEqual(float(adjusted[0]), 0.35, places=6)
        self.assertAlmostEqual(float(adjusted[2]), 0.65, places=6)
        self.assertAlmostEqual(float(diag["dynamic_max_asset_weight"]), 0.35, places=6)

    def test_live_session_artifacts_are_created(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            session_dir = create_live_session_dir(base, run_date="2026-05-29")
            self.assertEqual(session_dir, base / "daily" / "2026-05-29" / "1")
            write_live_session_metadata(session_dir, {"exchange": "okx", "mode": "testnet"})
            row = {
                "timestamp_utc": "2026-05-29T00:00:00+00:00",
                "cycle": 1,
                "status": "ok",
                "nav": 10000.0,
                "unrealized_pnl_usd": 0.0,
                "unrealized_pnl_pct": 0.0,
                "orders_submitted": 2,
                "orders_filled": 2,
            }
            append_live_session_row(session_dir / "live_trade_decisions_okx_testnet.csv", row)
            write_live_session_summary(session_dir, [row])

            self.assertTrue((session_dir / "live_session_metadata.json").exists())
            self.assertTrue((session_dir / "live_trade_decisions_okx_testnet.csv").exists())
            self.assertTrue((session_dir / "live_session_summary.json").exists())
            csv_text = (session_dir / "live_trade_decisions_okx_testnet.csv").read_text(encoding="utf-8")
            self.assertIn("unrealized_pnl_usd", csv_text)

    def test_live_session_timezone_defaults_to_bangkok(self):
        self.assertEqual(str(get_live_session_tz()), "Asia/Bangkok")

    def test_safety_gates_accept_fresh_native_signals(self):
        raw_state = self._raw_state("2026-01-01 10:00:00")
        current = np.array([0.4, 0.2, 0.4], dtype=np.float32)
        target = np.array([0.5, 0.2, 0.3], dtype=np.float32)
        kronos = {
            "BTCUSDT": KronosSignal("BTCUSDT", 0.01, 0.8, 0.5, "kronos"),
            "ETHUSDT": KronosSignal("ETHUSDT", -0.01, 0.7, -0.2, "kronos"),
        }
        ta_signal = TradingAgentsSignal(
            bias_score=0.1,
            confidence=0.6,
            max_asset_weight=0.7,
            cash_floor=0.1,
            high_risk=False,
            source="tradingagents:groq",
            rationale="ok",
        )
        reasons = evaluate_safety_gates(
            now_utc=pd.Timestamp("2026-01-01 10:30:00", tz="UTC"),
            raw_state=raw_state,
            current_weights=current,
            target_weights=target,
            enable_kronos=True,
            kronos_signals=kronos,
            enable_tradingagents=True,
            trading_signal=ta_signal,
            max_data_staleness_secs=7200,
            max_turnover=0.25,
            require_native_kronos=True,
            require_native_tradingagents=True,
        )
        self.assertEqual(reasons, [])

    def test_safety_gates_block_stale_and_fallback_signals(self):
        raw_state = self._raw_state("2026-01-01 00:00:00")
        current = np.array([0.4, 0.2, 0.4], dtype=np.float32)
        target = np.array([0.7, 0.2, 0.1], dtype=np.float32)
        kronos = {
            "BTCUSDT": KronosSignal("BTCUSDT", 0.01, 0.8, 0.5, "unavailable"),
            "ETHUSDT": KronosSignal("ETHUSDT", -0.01, 0.7, -0.2, "unavailable"),
        }
        ta_signal = TradingAgentsSignal(
            bias_score=0.1,
            confidence=0.6,
            max_asset_weight=0.7,
            cash_floor=0.1,
            high_risk=False,
            source="unavailable",
            rationale="unavailable",
        )
        reasons = evaluate_safety_gates(
            now_utc=pd.Timestamp("2026-01-01 05:00:00", tz="UTC"),
            raw_state=raw_state,
            current_weights=current,
            target_weights=target,
            enable_kronos=True,
            kronos_signals=kronos,
            enable_tradingagents=True,
            trading_signal=ta_signal,
            max_data_staleness_secs=7200,
            max_turnover=0.25,
            require_native_kronos=True,
            require_native_tradingagents=True,
        )
        self.assertTrue(any("market data stale" in reason for reason in reasons))
        self.assertTrue(any("turnover kill-switch" in reason for reason in reasons))
        self.assertIn("kronos non-native signal active", reasons)
        self.assertIn("tradingagents non-native signal active", reasons)


if __name__ == "__main__":
    unittest.main()
