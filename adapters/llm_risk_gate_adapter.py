"""
Low-cost LLM risk gate adapter.

This adapter does not generate alpha. It only classifies portfolio risk stance:
`allow`, `de-risk`, or `block`.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
try:
    from loguru import logger
except Exception:  # pragma: no cover - fallback when loguru is unavailable
    import logging

    logger = logging.getLogger(__name__)

_SUPPORTED_CADENCES = {"6h", "24h", "weekly"}
_SUPPORTED_FLAGS = {"allow", "de-risk", "block"}


@dataclass
class LLMRiskSignal:
    risk_flag: str
    confidence: float
    rationale: str
    source: str
    cached: bool = False
    call_budget_exhausted: bool = False
    raw_response: dict[str, Any] | None = None


class LLMRiskGateAdapter:
    """
    LLM risk overlay with strict budget, cadence cache, and no-override fallback.
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        base_url: str | None = None,
        model: str | None = None,
        cadence: str = "24h",
        cache_ttl_secs: int = 86_400,
        max_calls_per_day: int = 8,
        timeout_secs: float = 20.0,
        max_retries: int = 1,
        decision_log_path: Path | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        if self.base_url.endswith("/v1"):
            self.base_url = self.base_url[:-3]
        self.model = (
            model
            or os.getenv("LLM_RISK_GATE_MODEL", "").strip()
            or os.getenv("OLLAMA_MODEL", "").strip()
            or "qwen3.5:4b-gpu8k"
        )
        self.cadence = self._normalize_cadence(cadence)
        self.cache_ttl_secs = max(1, int(cache_ttl_secs))
        self.max_calls_per_day = max(1, int(max_calls_per_day))
        self.timeout_secs = max(1e-3, float(timeout_secs))
        self.max_retries = max(1, int(max_retries))
        self.decision_log_path = decision_log_path
        self.backend_name = "llm_risk_gate:ollama"

        self._cache: dict[str, tuple[pd.Timestamp, LLMRiskSignal]] = {}
        self._calls_by_day: dict[str, int] = {}
        self._session_stats = {"total_calls": 0, "cache_hits": 0, "call_budget_blocks": 0}

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._session_stats)

    def evaluate(
        self,
        *,
        asof: pd.Timestamp,
        market_state: dict[str, pd.DataFrame],
        drawdown: float,
        rolling_drawdown: float,
        volatility_z: float,
    ) -> LLMRiskSignal | None:
        if not self.enabled:
            return None

        ts = pd.Timestamp(asof)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")

        bucket = self._bucket(ts)
        now = pd.Timestamp.now(tz="UTC")
        cached_entry = self._cache.get(bucket)
        if cached_entry is not None:
            cached_at, cached_signal = cached_entry
            if (now - cached_at).total_seconds() <= self.cache_ttl_secs:
                self._session_stats["cache_hits"] += 1
                out = LLMRiskSignal(**asdict(cached_signal))
                out.cached = True
                self._append_decision_log(asof=ts, signal=out, cache_bucket=bucket)
                return out

        day_key = ts.strftime("%Y-%m-%d")
        used = self._calls_by_day.get(day_key, 0)
        if used >= self.max_calls_per_day:
            self._session_stats["call_budget_blocks"] += 1
            signal = LLMRiskSignal(
                risk_flag="allow",
                confidence=0.0,
                rationale="call_budget_exhausted",
                source=self.backend_name,
                cached=False,
                call_budget_exhausted=True,
            )
            self._append_decision_log(asof=ts, signal=signal, cache_bucket=bucket)
            return signal

        prompt = self._build_prompt(
            asof=ts,
            market_state=market_state,
            drawdown=drawdown,
            rolling_drawdown=rolling_drawdown,
            volatility_z=volatility_z,
        )
        raw = self._query_ollama(prompt)
        if raw is None:
            fallback = LLMRiskSignal(
                risk_flag="allow",
                confidence=0.0,
                rationale="provider_unavailable",
                source=self.backend_name,
                cached=False,
            )
            self._cache[bucket] = (now, fallback)
            self._append_decision_log(asof=ts, signal=fallback, cache_bucket=bucket)
            return fallback

        signal = self._normalize_response(raw)
        self._calls_by_day[day_key] = used + 1
        self._session_stats["total_calls"] += 1
        self._cache[bucket] = (now, signal)
        self._append_decision_log(asof=ts, signal=signal, cache_bucket=bucket)
        return signal

    @staticmethod
    def _normalize_cadence(cadence: str) -> str:
        value = str(cadence or "24h").strip().lower()
        if value not in _SUPPORTED_CADENCES:
            raise ValueError(f"Unsupported LLM risk-gate cadence '{cadence}'. Expected {_SUPPORTED_CADENCES}.")
        return value

    def _bucket(self, ts: pd.Timestamp) -> str:
        if self.cadence == "6h":
            hour_bucket = int(ts.hour / 6) * 6
            return f"{ts.strftime('%Y-%m-%d')}T{hour_bucket:02d}"
        if self.cadence == "24h":
            return ts.strftime("%Y-%m-%d")
        iso_year, iso_week, _ = ts.isocalendar()
        return f"{iso_year:04d}-W{iso_week:02d}"

    def _build_prompt(
        self,
        *,
        asof: pd.Timestamp,
        market_state: dict[str, pd.DataFrame],
        drawdown: float,
        rolling_drawdown: float,
        volatility_z: float,
    ) -> str:
        payload = {
            "asof_utc": asof.isoformat(),
            "portfolio_state": {
                "abs_drawdown": float(drawdown),
                "rolling_drawdown": float(rolling_drawdown),
                "volatility_z": float(volatility_z),
            },
            "symbols": {},
            "task": (
                "Classify portfolio risk stance for the next cadence window. "
                "Return strict JSON with keys: risk_flag, confidence, rationale. "
                "risk_flag must be one of allow, de-risk, block."
            ),
        }
        for symbol, frame in market_state.items():
            if frame is None or frame.empty:
                continue
            f = frame.copy()
            col = {str(c).lower(): c for c in f.columns}
            close_key = col.get("close")
            ret = np.log(f[close_key].astype(float) / f[close_key].astype(float).shift(1)).dropna() if close_key else pd.Series(dtype=float)
            payload["symbols"][symbol] = {
                "last_close": float(f[close_key].iloc[-1]) if close_key else None,
                "window_return": float(np.exp(ret.sum()) - 1.0) if len(ret) else 0.0,
                "window_volatility": float(ret.std()) if len(ret) > 1 else 0.0,
                "rsi_14": float(f[col["rsi_14"]].iloc[-1]) if "rsi_14" in col else None,
                "bb_width": float(f[col["bb_width"]].iloc[-1]) if "bb_width" in col else None,
                "atr_14": float(f[col["atr_14"]].iloc[-1]) if "atr_14" in col else None,
                "macd": float(f[col["macd"]].iloc[-1]) if "macd" in col else None,
            }
        return json.dumps(payload, ensure_ascii=True)

    def _query_ollama(self, prompt: str) -> dict[str, Any] | None:
        endpoint = f"{self.base_url}/api/chat"
        body = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a portfolio risk gate. "
                        "Output only JSON with keys risk_flag, confidence, rationale."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "options": {"temperature": 0.0, "num_ctx": 4096},
        }
        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.post(endpoint, json=body, timeout=self.timeout_secs)
                response.raise_for_status()
                data = response.json()
                content = (
                    data.get("message", {}).get("content")
                    if isinstance(data, dict)
                    else None
                )
                if content is None:
                    raise ValueError("Missing message content in Ollama response.")
                return json.loads(content)
            except Exception as exc:
                logger.warning(
                    f"LLM risk gate request failed attempt={attempt}/{self.max_retries} ({exc})."
                )
        return None

    def _normalize_response(self, raw: dict[str, Any]) -> LLMRiskSignal:
        flag_raw = str(raw.get("risk_flag", "allow")).strip().lower()
        flag = flag_raw if flag_raw in _SUPPORTED_FLAGS else "allow"
        try:
            confidence = float(raw.get("confidence", 0.5))
        except Exception:
            confidence = 0.5
        if confidence > 1.0:
            confidence = confidence / 100.0
        confidence = float(np.clip(confidence, 0.0, 1.0))
        rationale = str(raw.get("rationale", ""))[:500]
        return LLMRiskSignal(
            risk_flag=flag,
            confidence=confidence,
            rationale=rationale,
            source=self.backend_name,
            raw_response=raw,
        )

    def _append_decision_log(self, *, asof: pd.Timestamp, signal: LLMRiskSignal, cache_bucket: str) -> None:
        if self.decision_log_path is None:
            return
        self.decision_log_path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "logged_at_utc": datetime.now(timezone.utc).isoformat(),
            "asof_utc": asof.isoformat(),
            "cache_bucket": cache_bucket,
            "signal": asdict(signal),
            "stats": dict(self._session_stats),
        }
        with self.decision_log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=True) + "\n")
