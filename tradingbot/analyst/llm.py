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
        timeout_secs: float = 20.0,
        post: Callable[..., Any] | None = None,
    ) -> None:
        self.base_url = str(base_url or "").rstrip("/")
        self.api_key = str(api_key or "")
        self.model = str(model or "")
        self.timeout_secs = max(0.001, float(timeout_secs))
        self._post = post or requests.post

    def chat_json(self, *, messages: list[dict[str, str]], temperature: float = 0.0) -> dict[str, Any]:
        if not self.base_url:
            raise LLMProviderError("LLM_BASE_URL is not configured.")
        if not self.api_key:
            raise LLMProviderError("LLM_API_KEY is not configured.")
        if not self.model:
            raise LLMProviderError("LLM_MODEL is not configured.")

        endpoint = f"{self.base_url}/chat/completions"
        if not self.base_url.endswith("/v1"):
            endpoint = f"{self.base_url}/v1/chat/completions"
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": float(temperature),
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = self._post(endpoint, json=body, headers=headers, timeout=self.timeout_secs)
            response.raise_for_status()
            data = response.json()
        except LLMProviderError:
            raise
        except Exception as exc:
            raise LLMProviderError(f"LLM provider request failed: {exc}") from exc

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
