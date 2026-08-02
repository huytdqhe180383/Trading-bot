"""OpenAI-compatible chat-completions client for analyst-only calls."""

from __future__ import annotations

import json
from typing import Any, Callable

import requests


class LLMProviderError(RuntimeError):
    """Raised for provider configuration, transport, or HTTP failures."""


class LLMInvalidResponseError(RuntimeError):
    """Raised when the provider response is not strict JSON."""


class OpenAICompatibleLLMClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        model_config_name: str = "LLM_MODEL",
        base_url_config_name: str = "LLM_BASE_URL",
        api_key_config_name: str = "LLM_API_KEY",
        timeout_secs: float = 20.0,
        use_response_format: bool = True,
        post: Callable[..., Any] | None = None,
    ) -> None:
        self.base_url = str(base_url or "").rstrip("/")
        self.api_key = str(api_key or "")
        self.model = str(model or "")
        self.model_config_name = str(model_config_name or "LLM_MODEL")
        self.base_url_config_name = str(base_url_config_name or "LLM_BASE_URL")
        self.api_key_config_name = str(api_key_config_name or "LLM_API_KEY")
        self.timeout_secs = max(0.001, float(timeout_secs))
        self.use_response_format = bool(use_response_format)
        self._post = post or requests.post

    def chat_json(self, *, messages: list[dict[str, str]], temperature: float = 0.0) -> dict[str, Any]:
        if not self.base_url:
            raise LLMProviderError(f"{self.base_url_config_name} is not configured.")
        if not self.api_key:
            raise LLMProviderError(f"{self.api_key_config_name} is not configured.")
        if not self.model:
            raise LLMProviderError(f"{self.model_config_name} is not configured.")

        endpoint = f"{self.base_url}/chat/completions"
        if not self.base_url.endswith("/v1"):
            endpoint = f"{self.base_url}/v1/chat/completions"
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": float(temperature),
        }
        if self.use_response_format:
            body["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = self._post(endpoint, json=body, headers=headers, timeout=self.timeout_secs)
        except LLMProviderError:
            raise
        except Exception as exc:
            raise LLMProviderError(f"LLM provider request failed before response: {exc}") from exc

        try:
            response.raise_for_status()
        except Exception as exc:
            raise LLMProviderError(
                "LLM provider HTTP error: "
                f"{exc}; status={_response_status(response)}; body={_response_body_snippet(response, self.api_key)}"
            ) from exc

        try:
            data = response.json()
        except Exception as exc:
            raise LLMProviderError(
                "LLM provider returned non-JSON response envelope: "
                f"{exc}; status={_response_status(response)}; body={_response_body_snippet(response, self.api_key)}"
            ) from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise LLMInvalidResponseError("Missing choices[0].message.content in LLM response.") from exc

        try:
            parsed = json.loads(content)
        except Exception as exc:
            raise LLMInvalidResponseError("LLM response content was not valid JSON.") from exc
        if not isinstance(parsed, dict):
            raise LLMInvalidResponseError("LLM response content must be a JSON object.")
        return parsed


class FallbackLLMClient:
    """Use a second configured key only after the primary provider rejects it.

    This intentionally falls back on provider failures, not malformed model
    output: an invalid response needs investigation, while quota/key rotation
    is an availability concern.
    """

    def __init__(self, primary: OpenAICompatibleLLMClient, fallback: OpenAICompatibleLLMClient | None = None) -> None:
        self.primary = primary
        self.fallback = fallback
        self.model = primary.model

    def chat_json(self, *, messages: list[dict[str, str]], temperature: float = 0.0) -> dict[str, Any]:
        try:
            return self.primary.chat_json(messages=messages, temperature=temperature)
        except LLMProviderError:
            if self.fallback is None:
                raise
            return self.fallback.chat_json(messages=messages, temperature=temperature)


def _response_status(response: Any) -> str:
    return str(getattr(response, "status_code", "unknown"))


def _response_body_snippet(response: Any, secret: str, *, limit: int = 300) -> str:
    text = str(getattr(response, "text", "") or "")
    if not text:
        content = getattr(response, "content", b"")
        if isinstance(content, bytes):
            text = content.decode("utf-8", errors="replace")
        elif content:
            text = str(content)
    if secret:
        text = text.replace(secret, "[redacted]")
    text = " ".join(text.split())
    if len(text) > limit:
        return f"{text[:limit]}..."
    return text or "<empty>"
