"""
Historical OHLCV downloader (OKX-first, CCXT-based).

This replaces the old Binance bulk downloader as the canonical path.
The legacy Binance script is preserved under archive/binance_legacy/.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import ccxt
import pandas as pd
from loguru import logger

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import (
    BACKTEST_END,
    MTF_TIMEFRAMES,
    PRIMARY_EXCHANGE,
    RAW_DATA_DIR,
    SYMBOLS,
    TRAIN_START,
)


def _to_ccxt_symbol(symbol: str) -> str:
    return symbol.replace("USDT", "/USDT")


def _to_exchange(exchange_id: str) -> ccxt.Exchange:
    try:
        cls = getattr(ccxt, exchange_id)
    except AttributeError as exc:
        raise ValueError(f"Unsupported exchange: {exchange_id}") from exc
    exchange = cls({"enableRateLimit": True, "options": {"defaultType": "spot"}})
    exchange.load_markets()
    return exchange


def _fetch_ohlcv_paginated(
    exchange: ccxt.Exchange,
    *,
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
    limit: int = 1000,
) -> pd.DataFrame:
    ccxt_symbol = _to_ccxt_symbol(symbol)
    tf_ms = int(exchange.parse_timeframe(timeframe) * 1000)
    since = exchange.parse8601(f"{start}T00:00:00Z")
    end_ms = exchange.parse8601(f"{end}T23:59:59Z")

    rows: list[list[float]] = []
    while since is not None and since <= end_ms:
        batch = exchange.fetch_ohlcv(ccxt_symbol, timeframe=timeframe, since=since, limit=limit)
        if not batch:
            break
        rows.extend(batch)
        last_open = int(batch[-1][0])
        next_since = last_open + tf_ms
        if next_since <= since:
            break
        since = next_since
        sleep_seconds = max(exchange.rateLimit / 1000.0, 0.05)
        time.sleep(sleep_seconds)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume"])
    df.drop_duplicates(subset=["open_time"], inplace=True)
    df.sort_values("open_time", inplace=True)

    df["close_time"] = df["open_time"] + tf_ms - 1
    df["quote_asset_volume"] = 0.0
    df["num_trades"] = 0
    df["taker_buy_base_volume"] = 0.0
    df["taker_buy_quote_volume"] = 0.0

    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    df.set_index("open_time", inplace=True)

    numeric_cols = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_asset_volume",
        "taker_buy_base_volume",
        "taker_buy_quote_volume",
    ]
    for c in numeric_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["num_trades"] = pd.to_numeric(df["num_trades"], errors="coerce").fillna(0).astype(int)
    df.dropna(subset=["open", "high", "low", "close", "volume"], inplace=True)

    return df


def download_symbol(
    exchange: ccxt.Exchange,
    *,
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
    out_dir: Path,
) -> Path | None:
    logger.info(f"Downloading {symbol} {timeframe} from {start} to {end}...")
    df = _fetch_ohlcv_paginated(
        exchange,
        symbol=symbol,
        timeframe=timeframe,
        start=start,
        end=end,
    )
    if df.empty:
        logger.warning(f"No data downloaded for {symbol} {timeframe}.")
        return None
    out_path = out_dir / f"{symbol}_{timeframe}.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path)
    logger.success(f"Saved {len(df):,} rows -> {out_path}")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Download historical OHLCV via CCXT.")
    parser.add_argument("--exchange", default=PRIMARY_EXCHANGE)
    parser.add_argument("--symbols", nargs="+", default=SYMBOLS)
    parser.add_argument("--intervals", nargs="+", default=MTF_TIMEFRAMES)
    parser.add_argument("--start", default=TRAIN_START)
    parser.add_argument("--end", default=BACKTEST_END)
    args = parser.parse_args()

    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    exchange = _to_exchange(args.exchange.lower())

    for sym in args.symbols:
        for ivl in args.intervals:
            download_symbol(
                exchange,
                symbol=sym,
                timeframe=ivl,
                start=args.start,
                end=args.end,
                out_dir=RAW_DATA_DIR,
            )


if __name__ == "__main__":
    main()
