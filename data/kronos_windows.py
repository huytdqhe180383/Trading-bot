from __future__ import annotations

from pathlib import Path

import pandas as pd

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]


def load_raw_ohlcv_data(
    symbols: list[str],
    *,
    raw_data_dir: Path,
    start: str,
    end: str,
    timeframe: str = "1h",
) -> dict[str, pd.DataFrame]:
    raw_data: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        frame = pd.read_parquet(raw_data_dir / f"{symbol}_{timeframe}.parquet")
        frame.index = pd.to_datetime(frame.index, utc=True)
        frame = frame.sort_index().loc[start:end]
        raw_data[symbol] = frame[[c for c in OHLCV_COLUMNS if c in frame.columns]].copy()
    return raw_data


def window_raw_ohlcv(
    raw_data: dict[str, pd.DataFrame],
    *,
    timestamp: pd.Timestamp,
    lookback: int,
) -> dict[str, pd.DataFrame]:
    ts = pd.Timestamp(timestamp)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")

    windows: dict[str, pd.DataFrame] = {}
    for symbol, frame in raw_data.items():
        history = frame.loc[:ts].tail(lookback)
        windows[symbol] = history[[c for c in OHLCV_COLUMNS if c in history.columns]].copy()
    return windows
