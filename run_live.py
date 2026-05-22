"""
Broker-Execution Layer – run_live.py
=====================================
Executes the Ensemble agent in a live (or testnet) trading loop
on Binance Spot.  At each candle close, the agent observes current
market state, proposes portfolio weights, and the broker module
converts those weights into actual Buy/Sell market orders.

Usage:
    python run_live.py [--mode testnet|live]

⚠️  Always start with --mode testnet until you are confident in
    the system. Real trades cannot be undone.
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (
    SYMBOLS, INITIAL_CAPITAL, BINANCE_SPOT_FEE, KLINE_INTERVAL,
    MODELS_DIR, LOGS_DIR, RESULTS_DIR,
    REBALANCE_INTERVAL_SECS, MAX_RECONNECT_ATTEMPTS,
    RECONNECT_DELAY_SECS, ENSEMBLE_METHOD, MIN_ORDER_USDT,
)
from agents.ensemble_agent import load_ensemble, EnsembleAgent
from data.live_feed import get_client, build_live_state, get_balances
from environment.trading_env import BinanceSpotEnv

load_dotenv()


# ──────────────────────────────────────────────────────────────────────────
# BROKER UTILITIES
# ──────────────────────────────────────────────────────────────────────────

def get_prices(client) -> dict[str, float]:
    """Fetch latest mark prices for each trading pair."""
    prices = {}
    for sym in SYMBOLS:
        ticker = client.ticker_price(sym)
        prices[sym] = float(ticker["price"])
    return prices


def compute_target_orders(
    target_weights: np.ndarray,
    current_balances: dict[str, float],
    prices: dict[str, float],
    client,
) -> list[dict]:
    """
    Compare target portfolio weights against current holdings and
    compute the list of Market orders to rebalance.

    Returns list of:
        {"symbol": str, "side": "BUY"|"SELL", "quantity": float}
    """
    # Fetch step sizes to avoid Filter failure: LOT_SIZE
    try:
        exchange_info = client.exchange_info()
        symbols_info = {s["symbol"]: s for s in exchange_info["symbols"]}
    except Exception:
        symbols_info = {}

    def _get_step_size(symbol: str) -> float:
        if symbol not in symbols_info:
            return 0.0001
        for f in symbols_info[symbol]["filters"]:
            if f["filterType"] == "LOT_SIZE":
                return float(f["stepSize"])
        return 0.0001

    # Current total portfolio value in USDT
    portfolio_usdt = current_balances.get("USDT", 0.0)
    for i, sym in enumerate(SYMBOLS):
        asset = sym.replace("USDT", "")
        bal   = current_balances.get(asset, 0.0)
        portfolio_usdt += bal * prices.get(sym, 0.0)

    if portfolio_usdt < MIN_ORDER_USDT:
        logger.warning("Portfolio too small to trade. Skipping rebalance.")
        return []

    orders = []
    for i, sym in enumerate(SYMBOLS):
        asset = sym.replace("USDT", "")
        target_value = portfolio_usdt * float(target_weights[i])   # USD value desired
        current_value = current_balances.get(asset, 0.0) * prices.get(sym, 1.0)

        delta_usd = target_value - current_value
        # Avoid tiny dust orders
        if abs(delta_usd) < MIN_ORDER_USDT:
            continue

        price     = prices[sym]
        raw_quantity = abs(delta_usd) / price   # in base asset units
        
        # Round quantity mathematically to correct Binance tick interval
        step_size = _get_step_size(sym)
        precision = int(np.round(-np.log10(step_size)))
        quantity = round(raw_quantity, precision)

        if quantity > 0:
            orders.append({
                "symbol":   sym,
                "side":     "BUY" if delta_usd > 0 else "SELL",
                "quantity": quantity,
            })

    return orders


def execute_order(client, order: dict, dry_run: bool = False) -> dict | None:
    """Place a single market order. If dry_run, only log."""
    logger.info(f"  ORDER: {order['side']} {order['quantity']} {order['symbol']}")
    if dry_run:
        logger.info("  [DRY RUN] Order not submitted.")
        return None

    try:
        # Re-sync server time natively to prevent recvWindow jitter right before order
        server_time = client.time()['serverTime']
        result = client.new_order(
            symbol=order["symbol"],
            side=order["side"],
            type="MARKET",
            quantity=order["quantity"],
            recvWindow=60000,
            timestamp=server_time
        )
        logger.success(f"  Order filled: {result.get('orderId')}")
        return result
    except Exception as exc:
        logger.error(f"  Order failed: {exc}")
        return None


# ──────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ──────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Run BTC/ETH Ensemble agent live.")
    parser.add_argument("--mode", default=None, choices=["testnet", "live"],
                        help="Override TRADING_MODE from .env (default: use .env value)")
    parser.add_argument("--method", default=ENSEMBLE_METHOD,
                        choices=["mean", "voting", "weighted"])
    args = parser.parse_args()

    # Allow CLI override of mode
    if args.mode:
        os.environ["TRADING_MODE"] = args.mode

    mode = os.getenv("TRADING_MODE", "testnet")
    # For testnet we still want to actually submit the order to the fake exchange
    # We only want dry_run if specifically requested or testing logic
    dry_run = False

    # Setup mode-specific file logging
    log_file = LOGS_DIR / f"run_{mode}.log"
    logger.add(log_file, rotation="10 MB", retention="30 days", level="INFO")

    logger.info(f"Starting live trading | Mode: {mode.upper()} | Ensemble: {args.method}")
    if mode == "live":
        logger.warning("⚠️  LIVE MODE – real money is at risk! Press Ctrl+C to stop.")
        time.sleep(3)

    # ── Load ensemble ──────────────────────────────────────────────────
    client   = get_client()
    ensemble = load_ensemble(MODELS_DIR)
    agent    = EnsembleAgent(ensemble, method=args.method)

    # We need a dummy env just to get observation shape + step logic
    # Use a tiny placeholder – actual obs is built from live feed
    # Build a reference single-step env to get obs dimension
    from data.preprocess import load_and_process
    logger.info("Loading processed data for obs-space reference...")
    local_data = {
        sym: pd.read_parquet(
            Path("data/processed") / f"{sym}_test.parquet"
        )
        for sym in SYMBOLS
    }
    ref_env = BinanceSpotEnv(local_data, mode="eval")
    obs_dim  = ref_env.observation_space.shape[0]
    ref_env.close()

    # ── Trading loop ───────────────────────────────────────────────────
    csv_log_path = LOGS_DIR / "live_trades.csv"
    csv_log_path.parent.mkdir(parents=True, exist_ok=True)

    cycle = 0
    while True:
        cycle += 1
        ts = datetime.now(timezone.utc).isoformat()
        logger.info(f"\n[Cycle {cycle}] {ts}")

        # 1. Fetch live state (latest candles, processed)
        state = build_live_state(client)
        if state is None:
            logger.error("Failed to fetch live state. Waiting before retry...")
            time.sleep(RECONNECT_DELAY_SECS)
            continue

        # 2. Build flat observation (same structure as training env)
        obs_arrays = []
        for sym in SYMBOLS:
            df = state[sym]
            obs_arrays.append(df.values.flatten())
        # Append placeholder portfolio state (will be updated after first cycle)
        portfolio_weights = np.array([1 / len(SYMBOLS)] * len(SYMBOLS) + [0.0], dtype=np.float32)
        obs = np.concatenate(obs_arrays + [portfolio_weights]).astype(np.float32)

        # Pad/trim to expected obs_dim
        if len(obs) < obs_dim:
            obs = np.pad(obs, (0, obs_dim - len(obs)))
        elif len(obs) > obs_dim:
            obs = obs[:obs_dim]

        # 3. Agent inference → target weights
        target_weights = agent.predict(obs)   # [w_BTC, w_ETH, w_USDT]
        logger.info(f"  Target weights → BTC: {target_weights[0]:.3f} | "
                    f"ETH: {target_weights[1]:.3f} | USDT: {target_weights[2]:.3f}")

        # 4. Fetch balances & prices
        balances = get_balances(client)
        prices   = get_prices(client)
        
        # Calculate Current Net Asset Value (NAV)
        current_nav = balances.get("USDT", 0.0)
        for sym in SYMBOLS:
            asset = sym.replace("USDT", "")
            current_nav += balances.get(asset, 0.0) * prices.get(sym, 0.0)
            
        logger.info(f"  Balances: {balances}")
        logger.info(f"  Current NAV: ${current_nav:,.2f}")

        # Track PnL if initial NAV is known
        if cycle == 1:
            initial_nav = 10000.0 if mode == "testnet" else current_nav
            logger.info(f"  Initial Profile Locked: ${initial_nav:,.2f}")
        else:
            pnl_usd = current_nav - initial_nav
            pnl_pct = (pnl_usd / initial_nav) * 100 if initial_nav > 0 else 0.0
            logger.info(f"  Session PnL: ${pnl_usd:,.2f} ({pnl_pct:,.2f}%)")

        # 5. Compute and execute orders
        orders = compute_target_orders(target_weights, balances, prices, client)
        for order in orders:
            execute_order(client, order, dry_run=dry_run)

        # 6. Log to CSV
        log_row = {
            "timestamp": ts, "cycle": cycle,
            "btc_weight": target_weights[0],
            "eth_weight":  target_weights[1],
            "usdt_weight": target_weights[2],
            "nav": current_nav,
            "orders": str(orders),
        }
        pd.DataFrame([log_row]).to_csv(
            str(csv_log_path), mode="a", header=not csv_log_path.exists(), index=False
        )

        # 7. Wait for next candle close
        logger.info(f"  Sleeping {REBALANCE_INTERVAL_SECS}s until next cycle...")
        time.sleep(REBALANCE_INTERVAL_SECS)


if __name__ == "__main__":
    main()
