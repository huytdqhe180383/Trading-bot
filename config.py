"""
Central configuration for the BTC/ETH Auto-Trading System.
All paths, parameters, and constants are defined here.
"""

import os
from pathlib import Path

# ============================================================
# PROJECT PATHS
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
MODELS_DIR = BASE_DIR / "models"
LOGS_DIR = BASE_DIR / "logs"
RESULTS_DIR = BASE_DIR / "results"

# Create directories if they don't exist
for d in [RAW_DATA_DIR, PROCESSED_DATA_DIR, MODELS_DIR, LOGS_DIR, RESULTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ============================================================
# TRADING ASSETS & EXCHANGE
# ============================================================
SYMBOLS = ["BTCUSDT", "ETHUSDT"]          # Binance Spot symbols
BASE_CURRENCY = "USDT"
INITIAL_CAPITAL = 10_000.0                # Starting portfolio USD value

# Binance Spot fee tiers (Fix 3-D)
# Use BNB_TAKER / BNB_MAKER when the live account has BNB fee-payment enabled.
BINANCE_TAKER_FEE  = 0.001    # 0.10% standard taker (market orders)
BINANCE_MAKER_FEE  = 0.0008   # 0.08% standard maker (resting limit orders)
BINANCE_BNB_TAKER  = 0.00075  # 0.075% taker with BNB discount
BINANCE_BNB_MAKER  = 0.0001   # 0.01%  maker with BNB + VIP discount
BINANCE_SPOT_FEE   = BINANCE_TAKER_FEE   # backward-compat alias → conservative default

# ============================================================
# DATA SETTINGS
# ============================================================
# Historical training window (2020-01-01 to 2023-12-31)
TRAIN_START = "2020-01-01"
TRAIN_END   = "2023-12-31"

# Out-of-sample backtesting window (2024-01-01 to 2026-03-01)
BACKTEST_START = "2024-01-01"
BACKTEST_END   = "2026-03-01"

BASE_TIMEFRAME = "1h"
MTF_TIMEFRAMES = ["1h", "4h", "1d"]
KLINE_INTERVAL = "1h"  # matches Binance interval strings

# How many recent candles the agent observes at each step (lookback window)
LOOKBACK_WINDOW = 30

# ============================================================
# ENVIRONMENT SETTINGS
# ============================================================
# Action space: portfolio weight for each asset + cash
# e.g. [w_BTC, w_ETH, w_CASH] normalised to sum to 1.0
N_ASSETS = len(SYMBOLS)                   # 2

# Minimum trade size in USDT to avoid dust orders on Binance
MIN_ORDER_USDT = 10.0
SLIPPAGE = 0.001                          # 0.1% simulated slippage

# Minimum portfolio weight delta required to trigger a real rebalance (Fix 3-F).
# Below this threshold the env holds current weights to avoid dust-order bleeding.
# 3% of portfolio = $300 on a $10K account, comfortably above Binance's MIN_ORDER_USDT.
REBALANCE_THRESHOLD = 0.03

# Composite Reward Function Weights
# r_t = (w1 * profit_t) + (w2 * sharpe_t) - (w3 * drawdown_penalty_t) - (w4 * missed_opportunity_t)
REWARD_WEIGHTS = {
    "profit": 1.0,
    "sharpe": 0.0,            # Currently using log returns natively.
    "drawdown": 10.0,         # Multiplier for the rolling drawdown continuous penalty
    "turnover": 0.0,          # Covered by slippage implicitly
    "missed_opportunity": 0.5 # Penalty for sitting in cash during macro uptrend
}

# ============================================================
# KPI TARGETS
# ============================================================
KPI_TARGETS = {
    "profit_factor": 1.5,
    "max_drawdown_pct": -30.0,
    "sharpe_ratio": 1.5,
    "win_rate_pct": 60.0,
    "sortino_ratio": 1.5,
    "calmar_ratio": 2.0,
    "recovery_factor": 5.0,
}

# ============================================================
# TECHNICAL INDICATORS (computed during preprocessing)
# ============================================================
INDICATORS = {
    "rsi": [14],
    "macd": [(12, 26, 9)],
    "bbands": [20],
    "ema": [9, 21, 50],
    "atr": [14],
    "adx": [14],
    "obv": [],         # On-Balance Volume (no window needed)
    "cci": [20],
}

# ============================================================
# TRAINING HYPERPARAMETERS
# ============================================================
ALGORITHMS = ["PPO", "SAC"]   # Core members

ALGO_KWARGS = {
    "PPO": {
        "learning_rate": 3e-4,
        "n_steps": 2048,
        "batch_size": 64,
        "n_epochs": 10,
        "gamma": 0.99,
        "gae_lambda": 0.95,
        "clip_range": 0.2,
        "verbose": 1,
    },
    "SAC": {
        "learning_rate": 3e-4,
        "buffer_size": 100_000,
        "learning_starts": 1000,
        "batch_size": 256,
        "gamma": 0.99,
        "verbose": 1,
    },
}

# Number of environment steps per training run (optimized for sample efficiency)
TOTAL_TIMESTEPS = {
    "PPO": 2_000_000,   # On-policy: needs large steady stream of fresh experiences
    "SAC": 300_000,     # Off-policy: highly sample-efficient via replay buffer
}

# Checkpoint save interval (steps)
CHECKPOINT_FREQ = {
    "PPO": 200_000,
    "SAC": 30_000,
}

# ============================================================
# ENSEMBLE SETTINGS
# ============================================================
# Aggregation method: "mean" | "voting" | "weighted"
ENSEMBLE_METHOD = "mean"

# ============================================================
# LIVE TRADING SETTINGS
# ============================================================
# Reconnect retry attempts on network failure
MAX_RECONNECT_ATTEMPTS = 5
RECONNECT_DELAY_SECS = 10

# Minimum elapsed seconds between two consecutive rebalance decisions
REBALANCE_INTERVAL_SECS = 3600   # 1 hour (matches KLINE_INTERVAL)

# ============================================================
# LOGGING
# ============================================================
LOG_LEVEL = "INFO"
