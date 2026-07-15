import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tradingbot.analyst.budget import LLMBudget
from tradingbot.analyst.llm import LLMProviderError
from tradingbot.analyst.service import AnalystService
from tradingbot.analyst.store import AnalystEventStore


class _FakeLLM:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result or {
            "recommendation": "HOLD",
            "confidence": 0.7,
            "rationale": "No decisive edge.",
            "risk_notes": "Wait for confirmation.",
            "invalidation": "Breakout with volume.",
        }
        self.error = error
        self.calls = 0
        self.last_kwargs = {}

    def chat_json(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        if self.error:
            raise self.error
        return self.result


class AnalystServiceTest(unittest.TestCase):
    def _service(self, tmp: TemporaryDirectory, *, llm=None, background_budget=4, interactive_budget=4):
        base = Path(tmp.name)
        return AnalystService(
            llm_client=llm or _FakeLLM(),
            budget=LLMBudget(background_daily_limit=background_budget, interactive_daily_limit=interactive_budget),
            store=AnalystEventStore(results_dir=base / "results", reports_dir=base / "report"),
            enabled=True,
        )

    def test_successful_update_records_advisory_signal(self):
        with TemporaryDirectory() as tmp_name:
            tmp = type("Tmp", (), {"name": tmp_name})
            service = self._service(tmp)

            event = service.run_update(symbol="BTCUSDT", market_snapshot={"public": True})

            self.assertEqual(event.status, "ok")
            self.assertEqual(event.recommendation, "HOLD")
            self.assertNotIn("orders", event.to_public_dict())
            self.assertIn("news_snapshot", event.payload)
            events = service.events()
            self.assertEqual(len(events), 1)

    def test_provider_error_records_error_without_fallback_recommendation(self):
        with TemporaryDirectory() as tmp_name:
            tmp = type("Tmp", (), {"name": tmp_name})
            service = self._service(tmp, llm=_FakeLLM(error=LLMProviderError("api down")))

            event = service.run_update(symbol="ETHUSDT")

            self.assertEqual(event.status, "error")
            self.assertIsNone(event.recommendation)
            self.assertIn("LLM unavailable", event.message)
            self.assertTrue(list((Path(tmp_name) / "report" / "daily").glob("*/analyst_errors_*.md")))

    def test_invalid_payload_records_invalid_response_without_fallback(self):
        with TemporaryDirectory() as tmp_name:
            tmp = type("Tmp", (), {"name": tmp_name})
            service = self._service(
                tmp,
                llm=_FakeLLM(
                    result={
                        "recommendation": "BUY",
                        "rationale": "constructive",
                        "target_weights": {"BTC": 0.5},
                    }
                ),
            )

            event = service.run_update(symbol="BTCUSDT")

            self.assertEqual(event.status, "invalid_response")
            self.assertIsNone(event.recommendation)

    def test_budget_exhaustion_blocks_llm_call_without_fallback(self):
        with TemporaryDirectory() as tmp_name:
            tmp = type("Tmp", (), {"name": tmp_name})
            llm = _FakeLLM()
            service = self._service(tmp, llm=llm, interactive_budget=0)

            event = service.run_update(symbol="BTCUSDT", scope="interactive")

            self.assertEqual(event.status, "budget_exhausted")
            self.assertIsNone(event.recommendation)
            self.assertEqual(llm.calls, 0)

    def test_service_source_does_not_import_execution_fusion(self):
        import tradingbot.analyst.service as service_module

        source = Path(service_module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("MetaFusionAgent", source)
        self.assertNotIn("LiveExecutionController", source)
        self.assertNotIn("build_rebalance_orders", source)

    def test_explain_uses_llm_instead_of_copying_original(self):
        with TemporaryDirectory() as tmp_name:
            tmp = type("Tmp", (), {"name": tmp_name})
            llm = _FakeLLM()
            service = self._service(tmp, llm=llm)
            original = service.run_update(symbol="BTCUSDT")
            llm.result = {
                "recommendation": "HOLD",
                "confidence": 0.6,
                "rationale": "Plain-language explanation distinct from the original alert.",
                "risk_notes": "Watch whether the move fades.",
                "invalidation": "A clean breakout changes the read.",
            }

            explained = service.explain(alert_id=original.id)

            self.assertEqual(explained.status, "ok")
            self.assertEqual(explained.event_type, "explain")
            self.assertNotEqual(explained.message, original.message)

    def test_validate_infers_symbol_from_related_alert(self):
        with TemporaryDirectory() as tmp_name:
            tmp = type("Tmp", (), {"name": tmp_name})
            llm = _FakeLLM()
            service = self._service(tmp, llm=llm)
            original = service.run_update(symbol="ETHUSDT")

            validated = service.validate(alert_id=original.id)

            self.assertEqual(validated.symbol, "ETHUSDT")

    def test_background_and_interactive_scopes_use_separate_llm_clients(self):
        with TemporaryDirectory() as tmp_name:
            base = Path(tmp_name)
            interactive_llm = _FakeLLM()
            interactive_llm.model = "strong-model"
            background_llm = _FakeLLM()
            background_llm.model = "cheap-model"
            service = AnalystService(
                interactive_llm_client=interactive_llm,
                background_llm_client=background_llm,
                budget=LLMBudget(background_daily_limit=4, interactive_daily_limit=4),
                store=AnalystEventStore(results_dir=base / "results", reports_dir=base / "report"),
                enabled=True,
            )

            background_event = service.run_update(symbol="BTCUSDT", scope="background")
            chat_event = service.ask(question="Deep read?", symbol="BTCUSDT", scope="interactive")

            self.assertEqual(background_llm.calls, 3)
            self.assertEqual(interactive_llm.calls, 1)
            self.assertEqual(background_event.payload["llm_model"], "cheap-model")
            self.assertEqual(chat_event.payload["llm_model"], "strong-model")
            self.assertEqual([view["role"] for view in chat_event.payload["auxiliary_views"]], ["technical_analyst", "news_analyst"])

    def test_ask_prompt_includes_public_market_snapshot_for_position_advice(self):
        with TemporaryDirectory() as tmp_name:
            tmp = type("Tmp", (), {"name": tmp_name})
            llm = _FakeLLM()
            service = self._service(tmp, llm=llm)

            with patch("tradingbot.analyst.service.fetch_public_snapshot", return_value={"source": "okx_public"}):
                service.ask(question="Should I take a position now?", symbol="BTCUSDT")

            prompt = llm.last_kwargs["messages"][1]["content"]
            self.assertIn("market_snapshot", prompt)
            self.assertIn("auxiliary_views", prompt)
            self.assertIn("Do not default to HOLD merely because the answer is advisory", prompt)

    def test_auxiliary_agent_error_does_not_block_interactive_main(self):
        with TemporaryDirectory() as tmp_name:
            base = Path(tmp_name)
            interactive_llm = _FakeLLM()
            background_llm = _FakeLLM(error=LLMProviderError("weak model down"))
            service = AnalystService(
                interactive_llm_client=interactive_llm,
                background_llm_client=background_llm,
                budget=LLMBudget(background_daily_limit=4, interactive_daily_limit=4),
                store=AnalystEventStore(results_dir=base / "results", reports_dir=base / "report"),
                enabled=True,
            )

            with patch("tradingbot.analyst.service.fetch_public_snapshot", return_value={"source": "okx_public"}):
                event = service.ask(question="Should I take a position?", symbol="BTCUSDT")

            self.assertEqual(event.status, "ok")
            self.assertEqual(event.recommendation, "HOLD")
            self.assertEqual(interactive_llm.calls, 1)
            self.assertEqual(background_llm.calls, 2)
            self.assertEqual(event.payload["auxiliary_views"][0]["status"], "unavailable")
            self.assertIn("weak model down", interactive_llm.last_kwargs["messages"][1]["content"])


if __name__ == "__main__":
    unittest.main()
