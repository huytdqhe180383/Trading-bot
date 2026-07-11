"""Analyst-only advisory runtime.

This package is intentionally separate from live execution. It may create
reports, Discord messages, and frontend events, but not orders or portfolio
weight mutations.
"""

from .budget import LLMBudget, LLMBudgetExhausted
from .llm import (
    LLMInvalidResponseError,
    LLMProviderError,
    OpenAICompatibleLLMClient,
)
from .models import AnalystEvent, AnalystStatus, validate_analyst_payload
from .service import AnalystService, create_default_analyst_service

__all__ = [
    "AnalystEvent",
    "AnalystService",
    "AnalystStatus",
    "LLMBudget",
    "LLMBudgetExhausted",
    "LLMInvalidResponseError",
    "LLMProviderError",
    "OpenAICompatibleLLMClient",
    "create_default_analyst_service",
    "validate_analyst_payload",
]
