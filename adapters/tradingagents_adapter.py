"""
TradingAgents adapter with provider fallback and no heuristic trading fallback.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
try:
    from loguru import logger
except Exception:  # pragma: no cover - fallback when loguru is unavailable
    import logging

    logger = logging.getLogger(__name__)

_DEFAULT_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_DEFAULT_SHOPAI_BASE_URL = "https://api.shopaikey.com/v1"
_DEFAULT_OLLAMA_MODEL = "qwen3.5:4b"
_OLLAMA_MODEL_ALIASES = {
    "qwen-3.5-4b": "qwen3.5:4b",
}
_SUPPORTED_LLM_PROVIDERS = {
    "openai",
    "anthropic",
    "google",
    "azure",
    "xai",
    "deepseek",
    "qwen",
    "qwen-cn",
    "glm",
    "glm-cn",
    "minimax",
    "minimax-cn",
    "openrouter",
    "ollama",
    "shopai",
}

_CRYPTO_TICKER_MAP = {
    "BTCUSDT": ("BTC-USD", "crypto"),
    "ETHUSDT": ("ETH-USD", "crypto"),
}
_SUPPORTED_CADENCES = {"always", "hourly", "daily", "weekly"}


@dataclass
class TradingAgentsSignal:
    bias_score: float
    confidence: float
    max_asset_weight: float
    cash_floor: float
    high_risk: bool
    source: str
    rationale: str
    raw_decision: dict[str, Any] = field(default_factory=dict)


class TradingAgentsAdapter:
    """
    Normalize TradingAgents output into portfolio-level risk and direction signals.

    If every configured provider is unavailable, return None so callers can
    keep the RL policy as the only trading signal.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        provider: str | list[str] = "shopai",
        decision_log_path: Path | None = None,
        config_overrides: dict[str, Any] | None = None,
        max_retries: int = 1,
        retry_backoff_secs: float = 1.0,
        call_timeout_secs: float | None = 180.0,
        checkpoint_enabled: bool = False,
        cadence: str = "daily",
    ):
        self.enabled = enabled
        if isinstance(provider, str):
            self.providers = [p.strip() for p in provider.split(",") if p.strip()]
        else:
            self.providers = [str(p).strip() for p in provider if str(p).strip()]
        if not self.providers:
            self.providers = ["shopai"]
        self.decision_log_path = decision_log_path
        self.config_overrides = config_overrides or {}
        self.max_retries = max(0, int(max_retries))
        self.retry_backoff_secs = max(0.0, float(retry_backoff_secs))
        self.call_timeout_secs = None if call_timeout_secs is None else max(0.001, float(call_timeout_secs))
        self.checkpoint_enabled = bool(checkpoint_enabled)
        self.cadence = self._normalize_cadence(cadence)
        self._decision_cache: dict[tuple[str, str], TradingAgentsSignal] = {}
        self._active_provider_index = -1

        self._graph: Any | None = None
        self._backend_name = "unavailable"
        if self.enabled:
            self._try_init_backend()

    @property
    def backend_name(self) -> str:
        return self._backend_name

    def evaluate(
        self,
        *,
        ticker: str,
        asof: pd.Timestamp,
        market_snapshot: pd.DataFrame | None = None,
    ) -> TradingAgentsSignal | None:
        if not self.enabled:
            self._append_unavailable_log(ticker=ticker, asof=asof, reason="disabled")
            return None

        if self.enabled and self._graph is not None:
            mapped_ticker, asset_type = self._map_ticker(ticker)
            trade_date = asof.strftime("%Y-%m-%d")
            cache_bucket = self._cache_bucket(asof)
            if cache_bucket is not None:
                cache_key = (mapped_ticker, cache_bucket)
                cached = self._decision_cache.get(cache_key)
                if cached is not None:
                    self._append_decision_log(ticker=ticker, asof=asof, signal=cached)
                    return cached
            else:
                cache_key = None

            while self._graph is not None:
                attempts = max(1, self.max_retries)
                for attempt in range(1, attempts + 1):
                    try:
                        logger.info(
                            f"TradingAgents provider call provider={self._provider_display_name()} "
                            f"attempt={attempt}/{attempts} ticker={mapped_ticker} date={trade_date}"
                        )
                        _, decision = self._run_propagate_with_timeout(
                            mapped_ticker=mapped_ticker,
                            trade_date=trade_date,
                            asset_type=asset_type,
                        )
                        signal = self._normalize_decision(decision)
                        if cache_key is not None:
                            self._decision_cache[cache_key] = signal
                        self._append_decision_log(ticker=ticker, asof=asof, signal=signal)
                        return signal
                    except Exception as exc:
                        if self._is_permanent_provider_error(exc):
                            logger.warning(
                                f"TradingAgents hit a permanent provider error on {self._backend_name} ({exc}). "
                                "Switching backend without consuming more retries."
                            )
                            break
                        if attempt < attempts:
                            logger.warning(
                                f"TradingAgents inference attempt {attempt}/{attempts} failed "
                                f"on {self._backend_name} ({exc}). "
                                f"Retrying in {self.retry_backoff_secs:.1f}s."
                            )
                            if self.retry_backoff_secs > 0:
                                time.sleep(self.retry_backoff_secs)
                        else:
                            logger.warning(
                                f"TradingAgents inference failed after {attempts} attempts "
                                f"on {self._backend_name} ({exc})."
                            )

                next_index = self._active_provider_index + 1
                if self._activate_next_backend(start_index=next_index):
                    logger.warning(f"Switching TradingAgents backend to {self._backend_name}.")
                    continue
                break
            logger.warning("TradingAgents provider chain exhausted; returning unavailable signal.")

        self._append_unavailable_log(ticker=ticker, asof=asof, reason="provider_unavailable")
        return None

    def _try_init_backend(self) -> None:
        try:
            import tradingagents.default_config  # type: ignore  # noqa: F401
            import tradingagents.graph.trading_graph  # type: ignore  # noqa: F401
        except Exception as exc:
            logger.warning(f"TradingAgents module not importable ({exc}). Returning unavailable signal.")
            return

        if not self._activate_next_backend(start_index=0):
            logger.warning("TradingAgents initialization failed for all providers. Returning unavailable signal.")
            self._graph = None
            self._backend_name = "unavailable"
            self._active_provider_index = -1

    def _activate_next_backend(self, *, start_index: int) -> bool:
        try:
            from tradingagents.default_config import DEFAULT_CONFIG  # type: ignore
            from tradingagents.graph.trading_graph import TradingAgentsGraph  # type: ignore
        except Exception as exc:
            logger.warning(f"TradingAgents module not importable ({exc}). Returning unavailable signal.")
            return False

        for provider_index in range(max(0, int(start_index)), len(self.providers)):
            provider_raw = self.providers[provider_index]
            try:
                resolved = self._resolve_provider_config(provider_raw)
            except Exception as exc:
                logger.warning(f"TradingAgents provider '{provider_raw}' is invalid ({exc}). Skipping.")
                continue
            llm_provider = resolved["llm_provider"]
            backend_url = resolved["backend_url"]
            display_name = resolved["display_name"]
            model_overrides = resolved["model_overrides"]

            config = DEFAULT_CONFIG.copy()
            config.update(self.config_overrides)
            config.setdefault("checkpoint_enabled", self.checkpoint_enabled)
            config["llm_provider"] = llm_provider
            config.update(model_overrides)

            if "backend_url" not in self.config_overrides:
                config["backend_url"] = backend_url

            try:
                self._apply_provider_env(provider_raw=provider_raw, llm_provider=llm_provider)
                self._graph = TradingAgentsGraph(debug=False, config=config)
                self._backend_name = f"tradingagents:{display_name}"
                self._active_provider_index = provider_index
                logger.info(
                    f"TradingAgents backend initialized with provider={display_name} "
                    f"(llm_provider={llm_provider}, backend_url={config.get('backend_url')}, "
                    f"quick_model={config.get('quick_think_llm')}, deep_model={config.get('deep_think_llm')})."
                )
                return True
            except Exception as exc:
                logger.warning(f"TradingAgents init failed for provider={display_name} ({exc}).")

        self._graph = None
        self._backend_name = "unavailable"
        self._active_provider_index = -1
        return False

    def _resolve_provider_config(self, provider_raw: str) -> dict[str, Any]:
        provider = (provider_raw or "").strip().lower()
        if provider == "groq":
            model = os.getenv("TRADINGAGENTS_GROQ_MODEL", "").strip() or os.getenv("GROQ_MODEL", "").strip()
            return {
                "llm_provider": "openai",
                "backend_url": os.getenv("GROQ_BASE_URL", _DEFAULT_GROQ_BASE_URL),
                "display_name": "groq",
                "model_overrides": self._model_overrides(model),
            }
        if provider == "shopai":
            model = (
                os.getenv("TRADINGAGENTS_SHOPAI_MODEL", "").strip()
                or os.getenv("SHOPAI_MODEL", "").strip()
                or os.getenv("TRADINGAGENTS_OPENAI_MODEL", "").strip()
                or os.getenv("OPENAI_MODEL", "").strip()
            )
            backend_url = (
                os.getenv("SHOPAI_BASE_URL", "").strip()
                or os.getenv("OPENAI_BASE_URL", "").strip()
                or _DEFAULT_SHOPAI_BASE_URL
            )
            return {
                "llm_provider": "openai",
                "backend_url": backend_url,
                "display_name": "shopai",
                "model_overrides": self._model_overrides(model),
            }
        if provider == "grok":
            provider = "xai"
        if provider not in _SUPPORTED_LLM_PROVIDERS:
            raise ValueError(
                f"Unsupported TradingAgents provider '{provider_raw}'. "
                f"Supported: {sorted(_SUPPORTED_LLM_PROVIDERS)} plus aliases 'groq' and 'grok'."
            )
        if provider == "openai":
            model = os.getenv("TRADINGAGENTS_OPENAI_MODEL", "").strip() or os.getenv("OPENAI_MODEL", "").strip()
            backend_url = os.getenv("OPENAI_BASE_URL", "").strip() or None
        elif provider == "ollama":
            raw_model = (
                os.getenv("TRADINGAGENTS_OLLAMA_MODEL", "").strip()
                or os.getenv("OLLAMA_MODEL", "").strip()
                or _DEFAULT_OLLAMA_MODEL
            )
            model = _OLLAMA_MODEL_ALIASES.get(raw_model, raw_model)
            backend_url = os.getenv("OLLAMA_BASE_URL", "").strip() or None
        elif provider == "xai":
            model = os.getenv("TRADINGAGENTS_XAI_MODEL", "").strip() or os.getenv("XAI_MODEL", "").strip()
            backend_url = None
        else:
            model = ""
            backend_url = None
        return {
            "llm_provider": provider,
            "backend_url": backend_url,
            "display_name": provider,
            "model_overrides": self._model_overrides(model),
        }

    @staticmethod
    def _model_overrides(model_name: str) -> dict[str, str]:
        model = str(model_name or "").strip()
        if not model:
            return {}
        return {"quick_think_llm": model, "deep_think_llm": model}

    @staticmethod
    def _apply_provider_env(*, provider_raw: str, llm_provider: str) -> None:
        provider = (provider_raw or "").strip().lower()
        if provider == "shopai":
            shopai_key = os.getenv("SHOPAIKEY_API_KEY", "").strip() or os.getenv("OPENAI_API_KEY", "").strip()
            if not shopai_key:
                raise ValueError("SHOPAIKEY_API_KEY is not set for provider='shopai'.")
            os.environ["OPENAI_API_KEY"] = shopai_key
            return

        if provider == "groq":
            groq_key = os.getenv("GROQ_API_KEY", "").strip()
            if not groq_key:
                raise ValueError("GROQ_API_KEY is not set for provider='groq'.")
            os.environ["OPENAI_API_KEY"] = groq_key
            return

        if llm_provider == "openai":
            openai_key = os.getenv("OPENAI_API_KEY", "").strip()
            if not openai_key:
                raise ValueError("OPENAI_API_KEY is not set for provider='openai'.")
            return

        if llm_provider == "xai":
            xai_key = os.getenv("XAI_API_KEY", "").strip()
            if not xai_key:
                raise ValueError("XAI_API_KEY is not set for provider='xai'.")

    @staticmethod
    def _map_ticker(ticker: str) -> tuple[str, str]:
        key = str(ticker or "").upper().strip()
        if key in _CRYPTO_TICKER_MAP:
            return _CRYPTO_TICKER_MAP[key]
        return ticker, "stock"

    @staticmethod
    def _normalize_cadence(cadence: str) -> str:
        value = str(cadence or "daily").strip().lower()
        if value not in _SUPPORTED_CADENCES:
            raise ValueError(f"Unsupported cadence '{cadence}'. Expected one of {sorted(_SUPPORTED_CADENCES)}.")
        return value

    def _cache_bucket(self, asof: pd.Timestamp) -> str | None:
        ts = pd.Timestamp(asof)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")

        if self.cadence == "always":
            return None
        if self.cadence == "hourly":
            return ts.strftime("%Y-%m-%dT%H")
        if self.cadence == "daily":
            return ts.strftime("%Y-%m-%d")
        iso_year, iso_week, _ = ts.isocalendar()
        return f"{iso_year:04d}-W{iso_week:02d}"

    @staticmethod
    def _is_permanent_provider_error(exc: Exception) -> bool:
        text = str(exc).lower()
        permanent_markers = [
            "request too large",
            "tokens per minute",
            "rate_limit_exceeded",
            "context length",
            "maximum context length",
            "unsupported model",
            "model not found",
            "does not support",
            "invalid api key",
            "invalid token",
            "incorrect api key",
            "authentication",
            "forbidden",
        ]
        return any(marker in text for marker in permanent_markers)

    def _provider_display_name(self) -> str:
        if 0 <= self._active_provider_index < len(self.providers):
            return str(self.providers[self._active_provider_index]).strip().lower()
        return self._backend_name.replace("tradingagents:", "")

    def _run_propagate_with_timeout(
        self,
        *,
        mapped_ticker: str,
        trade_date: str,
        asset_type: str,
    ) -> tuple[Any, Any]:
        if self._graph is None:
            raise RuntimeError("TradingAgents graph is unavailable.")

        call_kwargs = {
            "company_name": mapped_ticker,
            "trade_date": trade_date,
            "asset_type": asset_type,
        }

        if self.call_timeout_secs is None:
            return self._graph.propagate(**call_kwargs)

        holder: dict[str, Any] = {}

        def _invoke() -> None:
            try:
                holder["result"] = self._graph.propagate(**call_kwargs)
            except Exception as exc:  # pragma: no cover - exercised in integration runtime
                holder["error"] = exc

        worker = threading.Thread(target=_invoke, daemon=True)
        worker.start()
        worker.join(self.call_timeout_secs)
        if worker.is_alive():
            raise TimeoutError(
                f"TradingAgents call exceeded timeout ({self.call_timeout_secs:.1f}s)."
            )
        if "error" in holder:
            raise holder["error"]
        if "result" not in holder:
            raise RuntimeError("TradingAgents call returned no result.")
        result = holder["result"]
        if not isinstance(result, tuple) or len(result) != 2:
            raise RuntimeError(f"Unexpected TradingAgents response shape: {type(result)}")
        return result

    def _normalize_decision(self, decision: Any) -> TradingAgentsSignal:
        if isinstance(decision, dict):
            raw = decision
            text = " ".join(str(v) for v in decision.values()).lower()
        else:
            raw = {"decision": str(decision)}
            text = str(decision).lower()

        bias = self._text_score(text)
        confidence = self._extract_confidence(raw)
        high_risk = any(token in text for token in ["risk-off", "high risk", "drawdown", "uncertain", "volatile"])

        max_asset_weight = 0.45 if high_risk else 0.75
        cash_floor = 0.35 if high_risk else 0.08
        rationale = str(raw.get("summary") or raw.get("rationale") or raw.get("decision") or "")[:400]

        return TradingAgentsSignal(
            bias_score=float(np.clip(bias, -1.0, 1.0)),
            confidence=float(np.clip(confidence, 0.0, 1.0)),
            max_asset_weight=max_asset_weight,
            cash_floor=cash_floor,
            high_risk=high_risk,
            source=self._backend_name,
            rationale=rationale,
            raw_decision=raw,
        )

    @staticmethod
    def _extract_returns(frame: pd.DataFrame) -> pd.Series:
        columns = {str(c).lower(): c for c in frame.columns}
        if "log_return_1h" in columns:
            return frame[columns["log_return_1h"]].dropna().astype(float)
        if "log_return" in columns:
            return frame[columns["log_return"]].dropna().astype(float)
        if "close" in columns:
            close = frame[columns["close"]].astype(float)
            return np.log(close / close.shift(1)).dropna()
        return pd.Series(dtype=float)

    @staticmethod
    def _text_score(text: str) -> float:
        positive = ["bull", "buy", "long", "overweight", "accumulate", "risk-on"]
        negative = ["bear", "sell", "short", "underweight", "de-risk", "risk-off"]
        pos_hits = sum(1 for token in positive if token in text)
        neg_hits = sum(1 for token in negative if token in text)
        if pos_hits == 0 and neg_hits == 0:
            return 0.0
        return (pos_hits - neg_hits) / max(pos_hits + neg_hits, 1)

    @staticmethod
    def _extract_confidence(raw: dict[str, Any]) -> float:
        keys = ["confidence", "conviction", "probability", "score"]
        for key in keys:
            if key in raw:
                try:
                    val = float(raw[key])
                    if val > 1.0:
                        val /= 100.0
                    return float(np.clip(val, 0.0, 1.0))
                except Exception:
                    continue
        return 0.5

    def _append_decision_log(self, *, ticker: str, asof: pd.Timestamp, signal: TradingAgentsSignal) -> None:
        if self.decision_log_path is None:
            return
        self.decision_log_path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "logged_at_utc": datetime.now(timezone.utc).isoformat(),
            "ticker": ticker,
            "asof_utc": asof.tz_convert("UTC").isoformat() if asof.tzinfo else asof.isoformat(),
            "signal": asdict(signal),
        }
        with self.decision_log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=True) + "\n")

    def _append_unavailable_log(self, *, ticker: str, asof: pd.Timestamp, reason: str) -> None:
        if self.decision_log_path is None:
            return
        self.decision_log_path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "logged_at_utc": datetime.now(timezone.utc).isoformat(),
            "ticker": ticker,
            "asof_utc": asof.tz_convert("UTC").isoformat() if asof.tzinfo else asof.isoformat(),
            "signal": None,
            "unavailable_reason": reason,
            "backend": self._backend_name,
        }
        with self.decision_log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=True) + "\n")
