import os
import unittest
import time
from unittest.mock import patch

import numpy as np
import pandas as pd

from adapters.tradingagents_adapter import TradingAgentsAdapter


class TradingAgentsAdapterTest(unittest.TestCase):
    @staticmethod
    def _sample_frame() -> pd.DataFrame:
        idx = pd.date_range("2026-01-01", periods=48, freq="h", tz="UTC")
        close = 100 + np.sin(np.linspace(0, 6.28, len(idx)))
        frame = pd.DataFrame({"close": close}, index=idx)
        frame["log_return_1h"] = np.log(frame["close"] / frame["close"].shift(1))
        return frame

    def test_disabled_adapter_returns_unavailable_signal(self):
        frame = self._sample_frame()

        adapter = TradingAgentsAdapter(enabled=False)
        signal = adapter.evaluate(
            ticker="BTCUSDT",
            asof=pd.Timestamp(frame.index[-1]),
            market_snapshot=frame,
        )

        self.assertIsNone(signal)

    def test_provider_alias_shopai_maps_to_openai_compat(self):
        adapter = TradingAgentsAdapter(enabled=False)
        with patch.dict(
            os.environ,
            {
                "SHOPAI_MODEL": "gpt-5.4-nano",
                "SHOPAI_BASE_URL": "https://api.shopaikey.com/v1",
            },
            clear=False,
        ):
            resolved = adapter._resolve_provider_config("shopai")
        self.assertEqual(resolved["llm_provider"], "openai")
        self.assertEqual(resolved["backend_url"], "https://api.shopaikey.com/v1")
        self.assertEqual(resolved["model_overrides"]["quick_think_llm"], "gpt-5.4-nano")

    def test_provider_alias_groq_maps_to_openai_compat(self):
        adapter = TradingAgentsAdapter(enabled=False)
        with patch.dict(os.environ, {"GROQ_MODEL": "qwen/qwen3-32b"}, clear=False):
            resolved = adapter._resolve_provider_config("groq")
        self.assertEqual(resolved["llm_provider"], "openai")
        self.assertIn("groq", str(resolved["backend_url"]).lower())
        self.assertEqual(resolved["model_overrides"]["quick_think_llm"], "qwen/qwen3-32b")

    def test_ollama_provider_uses_local_model_default(self):
        adapter = TradingAgentsAdapter(enabled=False)
        with patch.dict(os.environ, {}, clear=False):
            resolved = adapter._resolve_provider_config("ollama")
        self.assertEqual(resolved["llm_provider"], "ollama")
        self.assertEqual(resolved["model_overrides"]["quick_think_llm"], "qwen3.5:4b-gpu8k")

    def test_ollama_provider_accepts_requested_alias(self):
        adapter = TradingAgentsAdapter(enabled=False)
        with patch.dict(os.environ, {"OLLAMA_MODEL": "qwen-3.5-4b"}, clear=False):
            resolved = adapter._resolve_provider_config("ollama")
        self.assertEqual(resolved["model_overrides"]["quick_think_llm"], "qwen3.5:4b-gpu8k")

    def test_evaluate_maps_crypto_pair_and_asset_type(self):
        captured: dict[str, str] = {}

        class StubGraph:
            def propagate(self, company_name, trade_date, asset_type="stock"):
                captured["company_name"] = company_name
                captured["trade_date"] = trade_date
                captured["asset_type"] = asset_type
                return {}, {"decision": "Buy", "confidence": 0.8}

        frame = self._sample_frame()
        adapter = TradingAgentsAdapter(enabled=False)
        adapter.enabled = True
        adapter._backend_name = "tradingagents:test"
        adapter._graph = StubGraph()
        adapter.call_timeout_secs = None

        signal = adapter.evaluate(
            ticker="BTCUSDT",
            asof=pd.Timestamp(frame.index[-1]),
            market_snapshot=frame,
        )

        self.assertEqual(captured["company_name"], "BTC-USD")
        self.assertEqual(captured["asset_type"], "crypto")
        self.assertEqual(signal.source, "tradingagents:test")

    def test_timeout_returns_unavailable_signal(self):
        class SlowGraph:
            def propagate(self, company_name, trade_date, asset_type="stock"):
                time.sleep(0.2)
                return {}, {"decision": "Buy"}

        frame = self._sample_frame()
        adapter = TradingAgentsAdapter(enabled=False, max_retries=0, call_timeout_secs=0.05)
        adapter.enabled = True
        adapter._graph = SlowGraph()
        adapter.providers = ["unavailable"]
        adapter._active_provider_index = 0

        signal = adapter.evaluate(
            ticker="BTCUSDT",
            asof=pd.Timestamp(frame.index[-1]),
            market_snapshot=frame,
        )
        self.assertIsNone(signal)

    def test_weekly_cache_avoids_duplicate_model_calls(self):
        calls = {"n": 0}

        class StubGraph:
            def propagate(self, company_name, trade_date, asset_type="stock"):
                calls["n"] += 1
                return {}, {"decision": "Hold", "confidence": 0.5}

        frame = self._sample_frame()
        adapter = TradingAgentsAdapter(enabled=False, cadence="weekly")
        adapter.enabled = True
        adapter._backend_name = "tradingagents:test"
        adapter._graph = StubGraph()
        adapter.call_timeout_secs = None

        t1 = pd.Timestamp("2026-01-15 01:00:00", tz="UTC")
        t2 = pd.Timestamp("2026-01-16 20:00:00", tz="UTC")
        _ = adapter.evaluate(ticker="BTCUSDT", asof=t1, market_snapshot=frame)
        _ = adapter.evaluate(ticker="BTCUSDT", asof=t2, market_snapshot=frame)

        self.assertEqual(calls["n"], 1)

    def test_hourly_cadence_recomputes_across_hours(self):
        calls = {"n": 0}

        class StubGraph:
            def propagate(self, company_name, trade_date, asset_type="stock"):
                calls["n"] += 1
                return {}, {"decision": "Hold", "confidence": 0.5}

        frame = self._sample_frame()
        adapter = TradingAgentsAdapter(enabled=False, cadence="hourly")
        adapter.enabled = True
        adapter._backend_name = "tradingagents:test"
        adapter._graph = StubGraph()
        adapter.call_timeout_secs = None

        t1 = pd.Timestamp("2026-01-15 01:00:00", tz="UTC")
        t2 = pd.Timestamp("2026-01-15 02:00:00", tz="UTC")
        _ = adapter.evaluate(ticker="BTCUSDT", asof=t1, market_snapshot=frame)
        _ = adapter.evaluate(ticker="BTCUSDT", asof=t2, market_snapshot=frame)

        self.assertEqual(calls["n"], 2)

    def test_switches_to_next_provider_after_retry_budget(self):
        class FailingGraph:
            def propagate(self, company_name, trade_date, asset_type="stock"):
                raise RuntimeError("provider failed")

        class SuccessGraph:
            def propagate(self, company_name, trade_date, asset_type="stock"):
                return {}, {"decision": "Buy", "confidence": 0.7}

        class SwitchingAdapter(TradingAgentsAdapter):
            def _activate_next_backend(self, *, start_index: int) -> bool:
                if start_index >= len(self.providers):
                    self._graph = None
                    self._backend_name = "unavailable"
                    self._active_provider_index = -1
                    return False
                self._active_provider_index = start_index
                provider_name = self.providers[start_index]
                self._backend_name = f"tradingagents:{provider_name}"
                self._graph = SuccessGraph() if provider_name == "ollama" else FailingGraph()
                return True

        frame = self._sample_frame()
        adapter = SwitchingAdapter(
            enabled=False,
            provider=["shopai", "ollama"],
            max_retries=2,
            cadence="always",
        )
        adapter.enabled = True
        adapter.providers = ["shopai", "ollama"]
        adapter._active_provider_index = 0
        adapter._backend_name = "tradingagents:shopai"
        adapter._graph = FailingGraph()
        adapter.call_timeout_secs = None

        signal = adapter.evaluate(
            ticker="BTCUSDT",
            asof=pd.Timestamp(frame.index[-1]),
            market_snapshot=frame,
        )
        self.assertEqual(signal.source, "tradingagents:ollama")

    def test_permanent_provider_error_switches_without_exhausting_retries(self):
        calls = {"shopai": 0}

        class FailingGraph:
            def propagate(self, company_name, trade_date, asset_type="stock"):
                calls["shopai"] += 1
                raise RuntimeError("Request too large for model")

        class SuccessGraph:
            def propagate(self, company_name, trade_date, asset_type="stock"):
                return {}, {"decision": "Buy", "confidence": 0.7}

        class SwitchingAdapter(TradingAgentsAdapter):
            def _activate_next_backend(self, *, start_index: int) -> bool:
                if start_index >= len(self.providers):
                    self._graph = None
                    self._backend_name = "unavailable"
                    self._active_provider_index = -1
                    return False
                self._active_provider_index = start_index
                provider_name = self.providers[start_index]
                self._backend_name = f"tradingagents:{provider_name}"
                self._graph = SuccessGraph() if provider_name == "ollama" else FailingGraph()
                return True

        frame = self._sample_frame()
        adapter = SwitchingAdapter(
            enabled=False,
            provider=["shopai", "ollama"],
            max_retries=5,
            cadence="always",
        )
        adapter.enabled = True
        adapter.providers = ["shopai", "ollama"]
        adapter._active_provider_index = 0
        adapter._backend_name = "tradingagents:shopai"
        adapter._graph = FailingGraph()
        adapter.call_timeout_secs = None

        signal = adapter.evaluate(
            ticker="BTCUSDT",
            asof=pd.Timestamp(frame.index[-1]),
            market_snapshot=frame,
        )
        self.assertEqual(signal.source, "tradingagents:ollama")
        self.assertEqual(calls["shopai"], 1)

    def test_provider_chain_exhaustion_returns_none(self):
        class FailingGraph:
            def propagate(self, company_name, trade_date, asset_type="stock"):
                raise RuntimeError("provider failed")

        class ExhaustingAdapter(TradingAgentsAdapter):
            def _activate_next_backend(self, *, start_index: int) -> bool:
                if start_index >= len(self.providers):
                    self._graph = None
                    self._backend_name = "unavailable"
                    self._active_provider_index = -1
                    return False
                self._active_provider_index = start_index
                provider_name = self.providers[start_index]
                self._backend_name = f"tradingagents:{provider_name}"
                self._graph = FailingGraph()
                return True

        frame = self._sample_frame()
        adapter = ExhaustingAdapter(
            enabled=False,
            provider=["shopai", "ollama"],
            max_retries=1,
            cadence="always",
        )
        adapter.enabled = True
        adapter.providers = ["shopai", "ollama"]
        adapter._active_provider_index = 0
        adapter._backend_name = "tradingagents:shopai"
        adapter._graph = FailingGraph()
        adapter.call_timeout_secs = None

        signal = adapter.evaluate(
            ticker="BTCUSDT",
            asof=pd.Timestamp(frame.index[-1]),
            market_snapshot=frame,
        )
        self.assertIsNone(signal)

    def test_shopai_env_key_sets_openai_compat_key(self):
        adapter = TradingAgentsAdapter(enabled=False)
        with patch.dict(os.environ, {"SHOPAIKEY_API_KEY": "shopai-test-key"}, clear=True):
            adapter._apply_provider_env(provider_raw="shopai", llm_provider="openai")
            self.assertEqual(os.environ["OPENAI_API_KEY"], "shopai-test-key")

    def test_missing_shopai_key_raises_provider_error(self):
        adapter = TradingAgentsAdapter(enabled=False)
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "SHOPAIKEY_API_KEY"):
                adapter._apply_provider_env(provider_raw="shopai", llm_provider="openai")


if __name__ == "__main__":
    unittest.main()
