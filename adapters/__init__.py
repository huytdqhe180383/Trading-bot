"""External signal adapters for the trading pipeline."""

from .kronos_adapter import KronosAdapter, KronosSignal
from .tradingagents_adapter import TradingAgentsAdapter, TradingAgentsSignal

__all__ = [
    "KronosAdapter",
    "KronosSignal",
    "TradingAgentsAdapter",
    "TradingAgentsSignal",
]
