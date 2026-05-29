"""
Live market feed and broker utilities (OKX-first, CCXT-backed).
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import ccxt
import pandas as pd
from dotenv import load_dotenv
from loguru import logger

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import (
    BASE_TIMEFRAME,
    KLINE_INTERVAL,
    LOOKBACK_WINDOW,
    MAX_RECONNECT_ATTEMPTS,
    MIN_ORDER_USDT,
    RECONNECT_DELAY_SECS,
    SYMBOLS,
)
from data.preprocess import _add_indicators, _rolling_z_score

load_dotenv()


def to_ccxt_symbol(symbol: str) -> str:
    return symbol.replace("USDT", "/USDT")


class CCXTExchangeGateway:
    def __init__(
        self,
        *,
        exchange_id: str,
        mode: str,
        symbols: list[str] | None = None,
        timeframe: str = KLINE_INTERVAL,
        lookback_window: int = LOOKBACK_WINDOW,
    ):
        self.exchange_id = exchange_id.lower()
        self.mode = mode.lower()
        self.symbols = symbols or SYMBOLS
        self.timeframe = timeframe
        self.lookback_window = lookback_window
        self.exchange = self._build_exchange()

    def _build_exchange(self) -> ccxt.Exchange:
        try:
            cls = getattr(ccxt, self.exchange_id)
        except AttributeError as exc:
            raise ValueError(f"Exchange {self.exchange_id} is not supported by CCXT.") from exc

        exchange = cls({"enableRateLimit": True, "options": {"defaultType": "spot"}})
        if self.mode == "testnet":
            try:
                exchange.set_sandbox_mode(True)
                logger.info(f"[{self.exchange_id}] sandbox mode enabled.")
            except Exception:
                logger.warning(f"[{self.exchange_id}] sandbox mode not available; continuing in normal endpoint mode.")

        prefix = self.exchange_id.upper()
        if self.mode == "testnet":
            prefix = f"{prefix}_TESTNET"

        exchange.apiKey = os.getenv(f"{prefix}_API_KEY")
        exchange.secret = os.getenv(f"{prefix}_SECRET_KEY")
        if self.exchange_id == "okx":
            exchange.password = os.getenv(f"{prefix}_PASSPHRASE")

        exchange.load_markets()
        return exchange

    def fetch_raw_ohlcv(self) -> dict[str, pd.DataFrame] | None:
        state: dict[str, pd.DataFrame] = {}
        limit = self.lookback_window + 80
        for symbol in self.symbols:
            market = to_ccxt_symbol(symbol)
            for attempt in range(1, MAX_RECONNECT_ATTEMPTS + 1):
                try:
                    rows = self.exchange.fetch_ohlcv(market, timeframe=self.timeframe, limit=limit)
                    if not rows:
                        raise RuntimeError("empty OHLCV response")
                    frame = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume"])
                    frame["open_time"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
                    frame.set_index("open_time", inplace=True)
                    state[symbol] = frame
                    break
                except Exception as exc:
                    logger.warning(f"[{self.exchange_id}] {symbol} fetch failed attempt {attempt}: {exc}")
                    if attempt == MAX_RECONNECT_ATTEMPTS:
                        return None
                    time.sleep(RECONNECT_DELAY_SECS)
        return state

    def fetch_feature_state(self) -> dict[str, pd.DataFrame] | None:
        raw_state = self.fetch_raw_ohlcv()
        if raw_state is None:
            return None

        features: dict[str, pd.DataFrame] = {}
        for symbol, frame in raw_state.items():
            feature_input = frame.copy()
            if self.timeframe != BASE_TIMEFRAME:
                feature_input = feature_input.shift(1)
            enriched = _add_indicators(feature_input)
            drop_cols = ["open", "high", "low", "close", "volume"]
            enriched.drop(columns=drop_cols, inplace=True, errors="ignore")
            enriched = _rolling_z_score(enriched, window=len(enriched))
            enriched.dropna(inplace=True)
            features[symbol] = enriched.iloc[-self.lookback_window :]
        return features

    def fetch_balances_and_prices(self) -> tuple[dict[str, float], dict[str, float]]:
        prices: dict[str, float] = {}
        for symbol in self.symbols:
            ticker = self.exchange.fetch_ticker(to_ccxt_symbol(symbol))
            prices[symbol] = float(ticker["last"])

        raw = self.exchange.fetch_balance()
        balances = {asset: float(raw.get(asset, {}).get("free", 0.0)) for asset in ["BTC", "ETH", "USDT"]}
        return balances, prices

    def amount_to_precision(self, symbol: str, amount: float) -> float:
        ccxt_symbol = to_ccxt_symbol(symbol)
        return float(self.exchange.amount_to_precision(ccxt_symbol, amount))

    def create_market_order(self, symbol: str, side: str, amount: float) -> dict[str, Any]:
        ccxt_symbol = to_ccxt_symbol(symbol)
        return self.exchange.create_market_order(ccxt_symbol, side, amount)

    def build_rebalance_orders(
        self,
        *,
        target_weights: list[float] | tuple[float, ...],
        balances: dict[str, float],
        prices: dict[str, float],
    ) -> list[dict[str, Any]]:
        portfolio_usdt = balances.get("USDT", 0.0)
        for symbol in self.symbols:
            asset = symbol.replace("USDT", "")
            portfolio_usdt += balances.get(asset, 0.0) * prices.get(symbol, 0.0)

        if portfolio_usdt < MIN_ORDER_USDT:
            return []

        orders: list[dict[str, Any]] = []
        for i, symbol in enumerate(self.symbols):
            asset = symbol.replace("USDT", "")
            target_value = portfolio_usdt * float(target_weights[i])
            current_value = balances.get(asset, 0.0) * prices.get(symbol, 0.0)
            delta_usd = target_value - current_value
            if abs(delta_usd) < MIN_ORDER_USDT:
                continue
            raw_amount = abs(delta_usd) / max(prices.get(symbol, 0.0), 1e-9)
            amount = self.amount_to_precision(symbol, raw_amount)
            if amount <= 0:
                continue
            orders.append(
                {
                    "symbol": symbol,
                    "side": "buy" if delta_usd > 0 else "sell",
                    "amount": amount,
                }
            )
        return orders
