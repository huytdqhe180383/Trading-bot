"""
Broker-Execution Layer â€“ run_live.py
=====================================
Executes the Ensemble agent in a live (or testnet) trading loop.
Supports multiple exchanges (Binance, OKX) via CCXT abstraction.
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import ccxt
import numpy as np
import pandas as pd
from loguru import logger
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (
    SYMBOLS, KLINE_INTERVAL, LOOKBACK_WINDOW,
    MODELS_DIR, LOGS_DIR, REBALANCE_INTERVAL_SECS, MAX_RECONNECT_ATTEMPTS,
    RECONNECT_DELAY_SECS, ENSEMBLE_METHOD, MIN_ORDER_USDT
)
from agents.ensemble_agent import load_ensemble, EnsembleAgent
from data.preprocess import _add_indicators, _rolling_z_score
from environment.trading_env import BinanceSpotEnv

load_dotenv()

class CCXTBroker:
    def __init__(self, exchange_id: str, mode: str):
        self.exchange_id = exchange_id.lower()
        self.mode = mode.lower()
        
        try:
            exchange_class = getattr(ccxt, self.exchange_id)
            self.exchange = exchange_class({
                "enableRateLimit": True,
                "options": {
                    "defaultType": "spot",
                }
            })
        except AttributeError:
            raise ValueError(f"Exchange {exchange_id} is not supported by CCXT.")

        prefix = f"{self.exchange_id.upper()}"
        if self.mode == "testnet":
            prefix += "_TESTNET"
            self.exchange.set_sandbox_mode(True)
            logger.info(f"[{self.exchange_id.upper()}] Sandbox / Testnet enabled.")

        self.exchange.apiKey = os.getenv(f"{prefix}_API_KEY")
        self.exchange.secret = os.getenv(f"{prefix}_SECRET_KEY")
        if self.exchange_id == "okx":
            # OKX requires a password/passphrase
            self.exchange.password = os.getenv(f"{prefix}_PASSPHRASE")

        # In CCXT, if keys are missing but you call private methods, it raises AuthenticationError.
        # But load_markets() is public so it doesn't strictly need auth.       
        try:
            self.exchange.load_markets()
        except ccxt.AuthenticationError:
            pass
        except Exception as e:
            logger.error(f"Error loading markets: {e}")
        
    def _format_symbol(self, symbol: str) -> str:
        return symbol.replace("USDT", "/USDT")

    def fetch_state(self) -> dict[str, pd.DataFrame] | None:
        state = {}
        for sym in SYMBOLS:
            ccxt_sym = self._format_symbol(sym)
            for attempt in range(1, MAX_RECONNECT_ATTEMPTS + 1):
                try:
                    ohlcv = self.exchange.fetch_ohlcv(ccxt_sym, timeframe=KLINE_INTERVAL, limit=LOOKBACK_WINDOW + 50)
                    df = pd.DataFrame(ohlcv, columns=["open_time", "open", "high", "low", "close", "volume"])
                    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
                    df.set_index("open_time", inplace=True)
                    
                    # Compute indicators using training pipeline's standard method
                    df = _add_indicators(df)
                    df.drop(columns=["open", "high", "low", "close", "volume"], inplace=True, errors="ignore")
                    df = _rolling_z_score(df, window=len(df))
                    df.dropna(inplace=True)
                    
                    state[sym] = df.iloc[-LOOKBACK_WINDOW:]
                    break
                except Exception as exc:
                    logger.warning(f"[{self.exchange_id}] {sym} fetch failed (Attempt {attempt}): {exc}")
                    if attempt == MAX_RECONNECT_ATTEMPTS:
                        return None
                    time.sleep(RECONNECT_DELAY_SECS)
        return state

    def fetch_balances_and_prices(self) -> tuple[dict[str, float], dict[str, float]]:
        prices = {}
        for sym in SYMBOLS:
            ticker = self.exchange.fetch_ticker(self._format_symbol(sym))
            prices[sym] = ticker["last"]
            
        balances_raw = self.exchange.fetch_balance()
        balances = {asset: balances_raw.get(asset, {}).get("free", 0.0) 
                    for asset in ["BTC", "ETH", "USDT"]}
        return balances, prices

    def place_rebalance_orders(self, target_weights: np.ndarray, balances: dict, prices: dict, dry_run: bool):
        portfolio_usdt = balances.get("USDT", 0.0) + sum(
            balances.get(sym.replace("USDT", ""), 0.0) * prices.get(sym, 0.0) for sym in SYMBOLS
        )
        
        if portfolio_usdt < MIN_ORDER_USDT:
            logger.warning("Portfolio too small. Skipping rebalance.")
            return

        for i, sym in enumerate(SYMBOLS):
            asset = sym.replace("USDT", "")
            target_value = portfolio_usdt * float(target_weights[i])
            current_value = balances.get(asset, 0.0) * prices.get(sym, 1.0)
            
            delta_usd = target_value - current_value
            if abs(delta_usd) < MIN_ORDER_USDT:
                continue

            ccxt_sym = self._format_symbol(sym)
            raw_qty = abs(delta_usd) / prices[sym]
            
            quantity = self.exchange.amount_to_precision(ccxt_sym, raw_qty)
            side = "buy" if delta_usd > 0 else "sell"

            logger.info(f"  ORDER: {side.upper()} {quantity} {ccxt_sym}")
            if dry_run:
                continue
                
            try:
                result = self.exchange.create_market_order(ccxt_sym, side, quantity)
                logger.success(f"  Filled order: {result.get('id')}")
            except ccxt.ExchangeError as e:
                logger.error(f"  Order {side} failed: {e}")
            except Exception as e:
                logger.error(f"  Order {side} unexpected error: {e}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exchange", required=True, choices=["binance", "okx"])
    parser.add_argument("--mode", default="testnet", choices=["testnet", "live"])
    parser.add_argument("--method", default=ENSEMBLE_METHOD, choices=["mean", "voting", "weighted"])
    parser.add_argument("--dry-run", action="store_true", help="Prevent Real API Order Submission")
    args = parser.parse_args()

    mode = args.mode.lower()
    log_file = LOGS_DIR / f"run_{args.exchange}_{mode}.log"
    logger.add(log_file, rotation="10 MB", retention="30 days")   

    logger.info(f"Init {args.exchange.upper()} | Mode: {mode.upper()} | Dry-Run: {args.dry_run}")
    
    broker = CCXTBroker(exchange_id=args.exchange, mode=mode)
    
    ensemble = load_ensemble(MODELS_DIR)
    agent = EnsembleAgent(ensemble, method=args.method)

    from data.preprocess import load_and_process
    local_data = {s: pd.read_parquet(Path("data/processed") / f"{s}_test.parquet") for s in SYMBOLS}
    ref_env = BinanceSpotEnv(local_data, mode="eval")
    obs_dim = ref_env.observation_space.shape[0]
    ref_env.close()

    cycle = 0
    while True:
        cycle += 1
        logger.info(f"\n[Cycle {cycle}] {datetime.now(timezone.utc).isoformat()}")

        state = broker.fetch_state()
        if not state:
            continue

        obs_arrays = [state[sym].values.flatten() for sym in SYMBOLS]
        portfolio_weights = np.array([1 / len(SYMBOLS)] * len(SYMBOLS) + [0.0], dtype=np.float32)
        obs = np.concatenate(obs_arrays + [portfolio_weights]).astype(np.float32)

        if len(obs) < obs_dim: obs = np.pad(obs, (0, obs_dim - len(obs)))
        elif len(obs) > obs_dim: obs = obs[:obs_dim]

        target_weights = agent.predict(obs)
        logger.info(f"  Targets: BTC {target_weights[0]:.2f} | ETH {target_weights[1]:.2f} | USDT {target_weights[2]:.2f}")

        try:
            balances, prices = broker.fetch_balances_and_prices()
        except ccxt.AuthenticationError as e:
            logger.error(f"Cannot fetch balances. Are your {args.exchange.upper()} API keys set in .env? Error: {e}")
            break
            
        broker.place_rebalance_orders(target_weights, balances, prices, args.dry_run)

        time.sleep(REBALANCE_INTERVAL_SECS)

if __name__ == "__main__":
    main()
