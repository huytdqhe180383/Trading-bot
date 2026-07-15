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


if __name__ == "__main__":
    unittest.main()
