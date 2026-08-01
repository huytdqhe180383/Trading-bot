import json
import unittest

from tradingbot.analyst.llm import LLMInvalidResponseError, LLMProviderError, OpenAICompatibleLLMClient
from tradingbot.analyst.models import AnalystValidationError, validate_analyst_payload


class _Response:
    def __init__(
        self,
        payload,
        status_error: Exception | None = None,
        *,
        status_code: int = 200,
        text: str = "",
    ):
        self.payload = payload
        self.status_error = status_error
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_error:
            raise self.status_error

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class AnalystLLMTest(unittest.TestCase):
    def test_chat_json_uses_openai_compatible_endpoint(self):
        calls = []

        def post(url, **kwargs):
            calls.append((url, kwargs))
            return _Response({"choices": [{"message": {"content": json.dumps({"recommendation": "HOLD"})}}]})

        client = OpenAICompatibleLLMClient(
            base_url="https://provider.example/v1",
            api_key="secret",
            model="cheap-model",
            post=post,
        )

        out = client.chat_json(messages=[{"role": "user", "content": "{}"}])

        self.assertEqual(out["recommendation"], "HOLD")
        self.assertEqual(calls[0][0], "https://provider.example/v1/chat/completions")
        self.assertEqual(calls[0][1]["json"]["model"], "cheap-model")
        self.assertNotIn("secret", str(calls[0][1]["json"]))

    def test_provider_error_is_not_converted_to_decision(self):
        def post(url, **kwargs):
            raise TimeoutError("timeout")

        client = OpenAICompatibleLLMClient(base_url="https://provider.example", api_key="secret", model="m", post=post)

        with self.assertRaises(LLMProviderError):
            client.chat_json(messages=[{"role": "user", "content": "{}"}])

    def test_response_format_can_be_disabled_for_compatible_providers(self):
        calls = []

        def post(url, **kwargs):
            calls.append(kwargs)
            return _Response({"choices": [{"message": {"content": json.dumps({"recommendation": "HOLD"})}}]})

        client = OpenAICompatibleLLMClient(
            base_url="https://provider.example",
            api_key="secret",
            model="m",
            use_response_format=False,
            post=post,
        )

        client.chat_json(messages=[{"role": "user", "content": "{}"}])

        self.assertNotIn("response_format", calls[0]["json"])

    def test_non_json_provider_envelope_is_diagnostic(self):
        def post(url, **kwargs):
            return _Response(ValueError("no json"), status_code=200, text="")

        client = OpenAICompatibleLLMClient(base_url="https://provider.example", api_key="secret", model="m", post=post)

        with self.assertRaisesRegex(
            LLMProviderError,
            "non-JSON response envelope: no json; status=200; body=<empty>",
        ):
            client.chat_json(messages=[{"role": "user", "content": "{}"}])

    def test_http_error_includes_status_and_redacted_body(self):
        def post(url, **kwargs):
            return _Response(
                {},
                status_error=RuntimeError("500 Server Error"),
                status_code=500,
                text="bad provider response echoed secret",
            )

        client = OpenAICompatibleLLMClient(base_url="https://provider.example", api_key="secret", model="m", post=post)

        with self.assertRaises(LLMProviderError) as ctx:
            client.chat_json(messages=[{"role": "user", "content": "{}"}])

        message = str(ctx.exception)
        self.assertIn("status=500", message)
        self.assertIn("[redacted]", message)
        self.assertNotIn("secret", message)

    def test_invalid_json_is_rejected(self):
        def post(url, **kwargs):
            return _Response({"choices": [{"message": {"content": "not json"}}]})

        client = OpenAICompatibleLLMClient(base_url="https://provider.example", api_key="secret", model="m", post=post)

        with self.assertRaises(LLMInvalidResponseError):
            client.chat_json(messages=[{"role": "user", "content": "{}"}])

    def test_validate_rejects_executable_fields(self):
        with self.assertRaises(AnalystValidationError):
            validate_analyst_payload(
                {
                    "recommendation": "BUY",
                    "confidence": 0.8,
                    "rationale": "trend is constructive",
                    "quantity": 1.0,
                }
            )

    def test_validate_rejects_unsupported_recommendation(self):
        with self.assertRaises(AnalystValidationError):
            validate_analyst_payload({"recommendation": "OPEN_LONG", "rationale": "bad shape"})

    def test_chart_annotations_are_preserved_without_order_fields(self):
        parsed = validate_analyst_payload(
            {
                "recommendation": "BUY",
                "confidence": 0.7,
                "rationale": "Price is holding a supplied support zone.",
                "risk_notes": "Trendline depends on current volatility.",
                "invalidation": "A close below the displayed support weakens the thesis.",
                "chart_annotations": [
                    {"kind": "support", "price": 100000, "label": "Observed support"},
                    {
                        "kind": "trend",
                        "start_time": "2026-08-01T00:00:00Z",
                        "start_price": 99000,
                        "end_time": "2026-08-01T01:00:00Z",
                        "end_price": 100000,
                        "label": "Higher-low trend",
                    },
                ],
            }
        )

        self.assertEqual(len(parsed["chart_annotations"]), 2)

    def test_chart_annotation_requires_valid_price(self):
        with self.assertRaises(AnalystValidationError):
            validate_analyst_payload(
                {
                    "recommendation": "HOLD",
                    "rationale": "No decisive edge.",
                    "chart_annotations": [{"kind": "support", "price": 0, "label": "Invalid"}],
                }
            )

    def test_manual_scenario_contract_preserves_conditional_tp_and_sl(self):
        parsed = validate_analyst_payload(
            {
                "recommendation": "BUY",
                "rationale": "A supplied resistance break would improve momentum.",
                "horizon_outlook": [
                    {
                        "horizon": "INTRADAY",
                        "timeframes": ["15m", "1h"],
                        "bias": "BULLISH",
                        "momentum": "ACCELERATING",
                        "objective": "Test the next supplied resistance zone.",
                        "watch_for": ["15m close above resistance"],
                    }
                ],
                "scenarios": [
                    {
                        "name": "Confirmed breakout",
                        "direction": "BULLISH",
                        "condition": "15m candle accepts above supplied resistance.",
                        "confirmation_timeframe": "15m",
                        "entry_zone_low": 100.0,
                        "entry_zone_high": 101.0,
                        "take_profit": [104.0, 108.0],
                        "stop_loss": 98.0,
                        "plan": "Wait for confirmation before reassessing.",
                    }
                ],
            }
        )

        self.assertEqual(parsed["scenarios"][0]["take_profit"], [104.0, 108.0])
        self.assertEqual(parsed["scenarios"][0]["stop_loss"], 98.0)

    def test_manual_scenario_rejects_reversed_entry_zone(self):
        with self.assertRaises(AnalystValidationError):
            validate_analyst_payload(
                {
                    "recommendation": "AVOID",
                    "scenarios": [
                        {
                            "name": "Invalid zone",
                            "direction": "BULLISH",
                            "entry_zone_low": 101.0,
                            "entry_zone_high": 100.0,
                        }
                    ],
                }
            )


if __name__ == "__main__":
    unittest.main()
