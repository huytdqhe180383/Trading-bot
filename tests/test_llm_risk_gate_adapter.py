import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from adapters.llm_risk_gate_adapter import LLMRiskGateAdapter


class LLMRiskGateAdapterTest(unittest.TestCase):
    def _market_state(self) -> dict[str, pd.DataFrame]:
        idx = pd.date_range("2026-05-24", periods=48, freq="h", tz="UTC")
        close = np.linspace(100.0, 110.0, len(idx))
        frame = pd.DataFrame(
            {
                "close": close,
                "rsi_14": np.linspace(40.0, 70.0, len(idx)),
                "bb_width": np.linspace(0.01, 0.05, len(idx)),
                "atr_14": np.linspace(0.2, 1.0, len(idx)),
                "macd": np.linspace(-0.2, 0.3, len(idx)),
            },
            index=idx,
        )
        return {"BTCUSDT": frame, "ETHUSDT": frame.copy()}

    @patch("adapters.llm_risk_gate_adapter.requests.post")
    def test_cache_prevents_duplicate_calls_within_bucket(self, mock_post: MagicMock):
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"message": {"content": '{"risk_flag":"de-risk","confidence":0.9,"rationale":"x"}'}}
        mock_post.return_value = response

        adapter = LLMRiskGateAdapter(
            enabled=True,
            cadence="24h",
            cache_ttl_secs=86_400,
            max_calls_per_day=8,
            max_retries=1,
        )
        ts = pd.Timestamp("2026-05-24T12:00:00Z")
        state = self._market_state()
        s1 = adapter.evaluate(asof=ts, market_state=state, drawdown=-0.1, rolling_drawdown=-0.05, volatility_z=1.1)
        s2 = adapter.evaluate(asof=ts, market_state=state, drawdown=-0.1, rolling_drawdown=-0.05, volatility_z=1.1)

        self.assertIsNotNone(s1)
        self.assertIsNotNone(s2)
        self.assertEqual(mock_post.call_count, 1)
        self.assertTrue(s2.cached)

    @patch("adapters.llm_risk_gate_adapter.requests.post")
    def test_budget_exhaustion_returns_allow_without_network(self, mock_post: MagicMock):
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"message": {"content": '{"risk_flag":"block","confidence":0.9,"rationale":"x"}'}}
        mock_post.return_value = response

        adapter = LLMRiskGateAdapter(
            enabled=True,
            cadence="6h",
            cache_ttl_secs=1,
            max_calls_per_day=1,
            max_retries=1,
        )
        state = self._market_state()
        t1 = pd.Timestamp("2026-05-24T01:00:00Z")
        t2 = pd.Timestamp("2026-05-24T08:00:00Z")
        first = adapter.evaluate(asof=t1, market_state=state, drawdown=-0.1, rolling_drawdown=-0.05, volatility_z=1.1)
        second = adapter.evaluate(asof=t2, market_state=state, drawdown=-0.1, rolling_drawdown=-0.05, volatility_z=1.1)

        self.assertEqual(mock_post.call_count, 1)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(second.risk_flag, "allow")
        self.assertTrue(second.call_budget_exhausted)

    @patch("adapters.llm_risk_gate_adapter.requests.post")
    def test_failure_returns_allow_fallback(self, mock_post: MagicMock):
        mock_post.side_effect = RuntimeError("network down")
        adapter = LLMRiskGateAdapter(enabled=True, max_retries=2)
        out = adapter.evaluate(
            asof=pd.Timestamp("2026-05-24T12:00:00Z"),
            market_state=self._market_state(),
            drawdown=-0.1,
            rolling_drawdown=-0.1,
            volatility_z=1.0,
        )
        self.assertIsNotNone(out)
        self.assertEqual(out.risk_flag, "allow")


if __name__ == "__main__":
    unittest.main()
