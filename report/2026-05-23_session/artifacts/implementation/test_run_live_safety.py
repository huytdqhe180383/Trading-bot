import unittest

import numpy as np
import pandas as pd

from adapters.kronos_adapter import KronosSignal
from adapters.tradingagents_adapter import TradingAgentsSignal
from scripts.run_live import compute_turnover, evaluate_safety_gates, latest_market_timestamp


class RunLiveSafetyTest(unittest.TestCase):
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
