"""
Data Pipeline – Step 1: Historical Download
===========================================
Downloads BTC/USDT and ETH/USDT OHLCV kline data from
Binance's public bulk-data portal (data.binance.vision).

This avoids REST API rate limits and is much faster than
paginating through the API for multi-year history.

Usage:
    python -m data.download_historical --start 2020-01-01 --end 2025-12-31 --interval 1h
"""

import argparse
import io
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests
from tqdm import tqdm

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import SYMBOLS, MTF_TIMEFRAMES, TRAIN_START, BACKTEST_END, RAW_DATA_DIR

# Binance public data base URL
BASE_URL = "https://data.binance.vision/data/spot/monthly/klines"

COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_asset_volume", "num_trades",
    "taker_buy_base_volume", "taker_buy_quote_volume", "ignore",
]


def _month_range(start: str, end: str):
    """Yield (year, month) tuples inclusive of start and end months."""
    s = date.fromisoformat(start).replace(day=1)
    e = date.fromisoformat(end).replace(day=1)
    cur = s
    while cur <= e:
        yield cur.year, cur.month
        # advance one month
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1)
        else:
            cur = cur.replace(month=cur.month + 1)


def download_symbol(symbol: str, interval: str, start: str, end: str, out_dir: Path):
    """Download monthly CSV zip files for *symbol* and concatenate into one parquet."""
    all_months = []
    months = list(_month_range(start, end))

    for year, month in tqdm(months, desc=f"{symbol} {interval}", unit="month"):
        filename = f"{symbol}-{interval}-{year}-{month:02d}.zip"
        url = f"{BASE_URL}/{symbol}/{interval}/{filename}"

        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
        except requests.HTTPError as e:
            print(f"  [WARN] {year}-{month:02d} not available: {e}")
            continue

        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            csv_name = zf.namelist()[0]
            with zf.open(csv_name) as f:
                df = pd.read_csv(f, header=None, names=COLUMNS)

        all_months.append(df)

    if not all_months:
        print(f"[ERROR] No data downloaded for {symbol}")
        return

    full = pd.concat(all_months, ignore_index=True)
    full["open_time"] = full["open_time"].astype(float)
    full["open_time"] = full["open_time"].where(full["open_time"] < 1e14, full["open_time"] / 1000)
    full["close_time"] = full["close_time"].astype(float)
    full["close_time"] = full["close_time"].where(full["close_time"] < 1e14, full["close_time"] / 1000)
    
    # Parse timestamps (milliseconds since epoch)
    full["open_time"] = pd.to_datetime(full["open_time"], unit="ms", utc=True)
    full["close_time"] = pd.to_datetime(full["close_time"], unit="ms", utc=True)
    full.set_index("open_time", inplace=True)
    full.drop(columns=["ignore"], inplace=True)

    # Cast OHLCV to float
    ohlcv_cols = ["open", "high", "low", "close", "volume",
                  "quote_asset_volume", "taker_buy_base_volume",
                  "taker_buy_quote_volume"]
    full[ohlcv_cols] = full[ohlcv_cols].astype(float)
    full["num_trades"] = full["num_trades"].astype(int)

    out_path = out_dir / f"{symbol}_{interval}.parquet"
    full.to_parquet(out_path)
    print(f"[OK] Saved {len(full):,} rows → {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Download Binance historical kline data.")
    parser.add_argument("--symbols", nargs="+", default=SYMBOLS)
    parser.add_argument("--intervals", nargs="+", default=MTF_TIMEFRAMES)
    parser.add_argument("--start", default=TRAIN_START)
    parser.add_argument("--end", default=BACKTEST_END)
    args = parser.parse_args()

    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)

    for sym in args.symbols:
        for ivl in args.intervals:
            download_symbol(sym, ivl, args.start, args.end, RAW_DATA_DIR)


if __name__ == "__main__":
    main()
