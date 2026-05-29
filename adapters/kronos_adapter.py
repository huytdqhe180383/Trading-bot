"""
Kronos forecasting adapter with graceful unavailability handling.

This module keeps Kronos optional so the rest of the pipeline can run
without heavyweight model downloads.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
try:
    from loguru import logger
except Exception:  # pragma: no cover - fallback when loguru is unavailable
    import logging

    logger = logging.getLogger(__name__)

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]


@dataclass
class KronosSignal:
    symbol: str
    horizon_return: float
    confidence: float
    directional_score: float
    source: str
    details: dict[str, Any] = field(default_factory=dict)


class KronosAdapter:
    """Produce short-horizon directional signals per symbol."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        model_id: str = "NeoQuasar/Kronos-mini",
        tokenizer_id: str = "NeoQuasar/Kronos-Tokenizer-2k",
        forecast_horizon: int = 1,
        max_context: int = 512,
        device: str | None = None,
    ):
        self.enabled = enabled
        self.model_id = model_id
        self.tokenizer_id = tokenizer_id
        self.forecast_horizon = max(1, int(forecast_horizon))
        self.max_context = max(64, int(max_context))
        self.device = device

        self._predictor: Any | None = None
        self._backend_name = "unavailable"
        self._missing_ohlcv_logged: set[str] = set()
        if self.enabled:
            self._try_init_kronos_backend()

    @property
    def backend_name(self) -> str:
        return self._backend_name

    def predict_batch(
        self,
        market_state: dict[str, pd.DataFrame],
        *,
        timestamp: pd.Timestamp | None = None,
    ) -> dict[str, KronosSignal]:
        if not self.enabled:
            return {}
        if self._predictor is None:
            return {}
        out: dict[str, KronosSignal] = {}
        for symbol, frame in market_state.items():
            signal = self.predict_single(symbol, frame, timestamp=timestamp)
            if signal is not None:
                out[symbol] = signal
        return out

    def predict_single(
        self,
        symbol: str,
        frame: pd.DataFrame,
        *,
        timestamp: pd.Timestamp | None = None,
    ) -> KronosSignal | None:
        if not self.enabled:
            return None
        if frame is None or frame.empty:
            logger.warning(f"Kronos unavailable for {symbol}: empty market frame.")
            return None

        if self._predictor is not None and self._has_ohlcv(frame):
            try:
                return self._predict_with_kronos(symbol, frame, timestamp=timestamp)
            except Exception as exc:
                logger.warning(f"Kronos inference failed for {symbol}: {exc}. Returning unavailable signal.")
                return None

        if symbol not in self._missing_ohlcv_logged:
            logger.warning(f"Kronos unavailable for {symbol}: native backend or OHLCV columns missing.")
            self._missing_ohlcv_logged.add(symbol)
        return None

    def _try_init_kronos_backend(self) -> None:
        repo_path = os.getenv("KRONOS_REPO_PATH")
        if repo_path:
            p = Path(repo_path)
            if p.exists():
                sys.path.insert(0, str(p))

        try:
            from model import Kronos, KronosPredictor, KronosTokenizer  # type: ignore
        except Exception as exc:
            logger.warning(f"Kronos module not importable ({exc}). Returning unavailable signal.")
            return

        runtime_device = self.device
        if runtime_device is None:
            runtime_device = self._auto_device()

        try:
            tokenizer = KronosTokenizer.from_pretrained(self.tokenizer_id)
            model = Kronos.from_pretrained(self.model_id)
            self._predictor = KronosPredictor(
                model=model,
                tokenizer=tokenizer,
                device=runtime_device,
                max_context=self.max_context,
            )
            self._backend_name = "kronos"
            logger.info(f"Kronos backend initialized ({self.model_id}) on {runtime_device}.")
        except Exception as exc:
            logger.warning(f"Kronos backend init failed ({exc}). Returning unavailable signal.")
            self._predictor = None
            self._backend_name = "unavailable"

    @staticmethod
    def _has_ohlcv(frame: pd.DataFrame) -> bool:
        lower = {str(c).lower() for c in frame.columns}
        return all(c in lower for c in OHLCV_COLUMNS[:4])

    @staticmethod
    def _auto_device() -> str:
        try:
            import torch  # type: ignore

            if torch.cuda.is_available():
                return "cuda:0"
        except Exception:
            pass
        return "cpu"

    @staticmethod
    def _infer_step_delta(index: pd.DatetimeIndex) -> pd.Timedelta:
        if len(index) < 2:
            return pd.Timedelta(hours=1)
        diffs = index.to_series().diff().dropna()
        if diffs.empty:
            return pd.Timedelta(hours=1)
        return diffs.median()

    def _predict_with_kronos(
        self,
        symbol: str,
        frame: pd.DataFrame,
        *,
        timestamp: pd.Timestamp | None = None,
    ) -> KronosSignal:
        x_df = frame.copy()
        x_df.columns = [str(c).lower() for c in x_df.columns]
        x_df = x_df[[c for c in OHLCV_COLUMNS if c in x_df.columns]]
        x_df = x_df.tail(self.max_context)

        if not isinstance(x_df.index, pd.DatetimeIndex):
            x_df.index = pd.to_datetime(x_df.index, utc=True)

        step_delta = self._infer_step_delta(x_df.index)
        anchor_ts = x_df.index[-1] if timestamp is None else timestamp
        y_index = pd.DatetimeIndex(
            [anchor_ts + step_delta * (i + 1) for i in range(self.forecast_horizon)],
            tz="UTC",
        )
        x_timestamp = pd.Series(x_df.index, name="timestamp")
        y_timestamp = pd.Series(y_index, name="timestamp")

        pred_df = self._predictor.predict(  # type: ignore[union-attr]
            df=x_df,
            x_timestamp=x_timestamp,
            y_timestamp=y_timestamp,
            pred_len=self.forecast_horizon,
            T=1.0,
            top_p=0.9,
            sample_count=1,
            verbose=False,
        )

        pred_close = float(pred_df["close"].iloc[self.forecast_horizon - 1])
        last_close = float(x_df["close"].iloc[-1])
        horizon_ret = (pred_close / max(last_close, 1e-9)) - 1.0

        hist_rets = x_df["close"].pct_change().dropna()
        hist_vol = float(hist_rets.std()) if len(hist_rets) > 1 else 0.0
        confidence = float(np.clip(abs(horizon_ret) / (hist_vol + 1e-6), 0.0, 1.0))
        directional = float(np.tanh(horizon_ret * 25.0))

        return KronosSignal(
            symbol=symbol,
            horizon_return=horizon_ret,
            confidence=confidence,
            directional_score=directional,
            source="kronos",
            details={"backend": self._backend_name, "hist_vol": hist_vol},
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
