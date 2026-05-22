"""
Data Pipeline – Step 3: Live Data Feed
=======================================
Provides a thin wrapper around the Binance REST API for
fetching the latest OHLCV candles during live / testnet trading.
Also includes a WebSocket listener for real-time price streaming.

Uses the official `binance-connector` library.
"""

import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
from loguru import logger
from binance.spot import Spot
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import SYMBOLS, KLINE_INTERVAL, LOOKBACK_WINDOW, MAX_RECONNECT_ATTEMPTS, RECONNECT_DELAY_SECS
from data.preprocess import _add_indicators, _rolling_z_score

load_dotenv()

# ──────────────────────────────────────────
# CLIENT FACTORY
# ──────────────────────────────────────────

def get_client() -> Spot:
    """Return a Binance Spot client configured for testnet or live mode."""
    mode = os.getenv("TRADING_MODE", "testnet").lower()
    api_key = os.getenv("BINANCE_TESTNET_API_KEY") if mode == "testnet" else os.getenv("BINANCE_API_KEY")
    secret  = os.getenv("BINANCE_TESTNET_SECRET_KEY") if mode == "testnet" else os.getenv("BINANCE_SECRET_KEY")

    params = {
        "api_key": api_key,
        "api_secret": secret,
    }
    if mode == "testnet":
        # Official testnet base URL
        params["base_url"] = "https://testnet.binance.vision"
        logger.info("Binance client: TESTNET mode")
    else:
        logger.warning("Binance client: LIVE mode – real trades will be placed!")

    return Spot(**params)


# ──────────────────────────────────────────
# KLINE FETCHER (REST)
# ──────────────────────────────────────────

def fetch_latest_klines(
    client: Spot,
    symbol: str,
    interval: str = KLINE_INTERVAL,
    limit: int = LOOKBACK_WINDOW + 50,   # extra rows for indicator warm-up
) -> pd.DataFrame:
    """
    Fetch the most recent *limit* closed kline candles for *symbol*.
    Returns a DataFrame with the same columns as the preprocessor produces.
    """
    raw = client.klines(symbol, interval, limit=limit)
    columns = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "num_trades",
        "taker_buy_base_volume", "taker_buy_quote_volume", "ignore",
    ]
    df = pd.DataFrame(raw, columns=columns)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df.set_index("open_time", inplace=True)
    df.drop(columns=["ignore", "close_time"], inplace=True)

    # Cast numeric
    float_cols = ["open", "high", "low", "close", "volume",
                  "quote_asset_volume", "taker_buy_base_volume",
                  "taker_buy_quote_volume"]
    df[float_cols] = df[float_cols].astype(float)
    df["num_trades"] = df["num_trades"].astype(int)

    # Compute indicators & normalise using same logic as offline preprocessing
    df = _add_indicators(df)
    df.drop(columns=["open", "high", "low", "close"], inplace=True, errors="ignore")
    df = _rolling_z_score(df, window=len(df))
    df.dropna(inplace=True)

    # Return only the LOOKBACK_WINDOW most recent rows (latest candle last)
    return df.iloc[-LOOKBACK_WINDOW:]


# ──────────────────────────────────────────
# MULTI-SYMBOL STATE BUILDER
# ──────────────────────────────────────────

def build_live_state(client: Spot) -> dict[str, pd.DataFrame] | None:
    """
    Fetch live processed data for all symbols.
    Returns None if any symbol fails after retries.
    """
    state = {}
    for symbol in SYMBOLS:
        for attempt in range(1, MAX_RECONNECT_ATTEMPTS + 1):
            try:
                state[symbol] = fetch_latest_klines(client, symbol)
                break
            except Exception as exc:
                logger.warning(f"[{symbol}] Attempt {attempt}/{MAX_RECONNECT_ATTEMPTS} failed: {exc}")
                if attempt == MAX_RECONNECT_ATTEMPTS:
                    logger.error(f"[{symbol}] All retries exhausted. Skipping cycle.")
                    return None
                time.sleep(RECONNECT_DELAY_SECS)
    return state


# ──────────────────────────────────────────
# ACCOUNT INFO HELPER
# ──────────────────────────────────────────

def get_balances(client: Spot, assets: list[str] = ["BTC", "ETH", "USDT"]) -> dict[str, float]:
    """Return free balance for each asset in *assets*."""
    info = client.account(recvWindow=60000)
    balances = {b["asset"]: float(b["free"]) for b in info["balances"] if b["asset"] in assets}
    return balances
