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
from .rl_evidence import RLEvidenceEnvelope, build_evidence_from_promotion_gate, load_rl_evidence
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
    "RLEvidenceEnvelope",
    "build_evidence_from_promotion_gate",
    "create_default_analyst_service",
    "load_rl_evidence",
    "validate_analyst_payload",
]
