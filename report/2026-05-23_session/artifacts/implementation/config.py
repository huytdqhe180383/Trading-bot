"""
Central configuration for the BTC/ETH auto-trading system.
"""

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
ARCHIVE_DIR = BASE_DIR / "archive"

for d in [RAW_DATA_DIR, PROCESSED_DATA_DIR, MODELS_DIR, LOGS_DIR, RESULTS_DIR, ARCHIVE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ============================================================
# TRADING ASSETS & EXCHANGE
# ============================================================
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
BASE_CURRENCY = "USDT"
INITIAL_CAPITAL = 10_000.0

PRIMARY_EXCHANGE = "okx"
SUPPORTED_EXCHANGES = ["okx", "binance"]

# Exchange fee model
BINANCE_TAKER_FEE = 0.001
BINANCE_MAKER_FEE = 0.0008
BINANCE_BNB_TAKER = 0.00075
BINANCE_BNB_MAKER = 0.0001
BINANCE_SPOT_FEE = BINANCE_TAKER_FEE
DEFAULT_TRADING_FEE = BINANCE_SPOT_FEE

# ============================================================
# DATA SETTINGS
# ============================================================
TRAIN_START = "2020-01-01"
TRAIN_END = "2023-12-31"

BACKTEST_START = "2024-01-01"
BACKTEST_END = "2026-03-01"

BASE_TIMEFRAME = "1h"
MTF_TIMEFRAMES = ["1h", "4h", "1d"]
KLINE_INTERVAL = "1h"
LOOKBACK_WINDOW = 30

# ============================================================
# ENVIRONMENT SETTINGS
# ============================================================
N_ASSETS = len(SYMBOLS)

MIN_ORDER_USDT = 10.0
SLIPPAGE = 0.001
REBALANCE_THRESHOLD = 0.03

REWARD_WEIGHTS = {
    "profit": 1.0,
    "sharpe": 0.0,
    "drawdown": 10.0,
    "turnover": 0.0,
    "missed_opportunity": 0.5,
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
# TECHNICAL INDICATORS
# ============================================================
INDICATORS = {
    "rsi": [14],
    "macd": [(12, 26, 9)],
    "bbands": [20],
    "ema": [9, 21, 50],
    "atr": [14],
    "adx": [14],
    "obv": [],
    "cci": [20],
}

# ============================================================
# TRAINING HYPERPARAMETERS
# ============================================================
ALGORITHMS = ["PPO", "SAC"]

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

TOTAL_TIMESTEPS = {
    "PPO": 200_000,
    "SAC": 50_000,
}

CHECKPOINT_FREQ = {
    "PPO": 20_000,
    "SAC": 10_000,
}

TRAIN_DEVICE = "auto"
REQUIRE_GPU_FOR_TRAINING = False

# ============================================================
# ENSEMBLE SETTINGS
# ============================================================
ENSEMBLE_METHOD = "mean"

# ============================================================
# LIVE TRADING SETTINGS
# ============================================================
MAX_RECONNECT_ATTEMPTS = 5
RECONNECT_DELAY_SECS = 10
REBALANCE_INTERVAL_SECS = 3600

# ============================================================
# SIGNAL INTEGRATION (Kronos + TradingAgents + Meta-Fusion)
# ============================================================
ENABLE_KRONOS = True
ENABLE_TRADINGAGENTS = True

KRONOS_MODEL_ID = "NeoQuasar/Kronos-mini"
KRONOS_TOKENIZER_ID = "NeoQuasar/Kronos-Tokenizer-2k"
KRONOS_FORECAST_HORIZON = 1

TRADINGAGENTS_PROVIDER = "openai"
TRADINGAGENTS_PROVIDER_FALLBACKS = ["openai", "groq", "ollama"]
TRADINGAGENTS_DECISION_LOG_PATH = LOGS_DIR / "tradingagents_decisions.jsonl"
TRADINGAGENTS_CHECKPOINT_ENABLED = False
TRADINGAGENTS_MAX_RETRIES = 5
TRADINGAGENTS_RETRY_BACKOFF_SECS = 1.0
TRADINGAGENTS_CALL_TIMEOUT_SECS = 45.0
TRADINGAGENTS_BACKTEST_CADENCE = "weekly"
TRADINGAGENTS_LIVE_CADENCE = "hourly"

MAX_TILT_PER_SIGNAL = 0.05
MAX_PORTFOLIO_TURNOVER = 0.25
MAX_ASSET_WEIGHT = 0.80
MIN_CASH_FLOOR = 0.05
FALLBACK_MODE = "rl_only"

LIVE_MAX_DATA_STALENESS_SECS = 7_200
LIVE_KILL_SWITCH_MAX_TURNOVER = 0.25
LIVE_REQUIRE_NATIVE_KRONOS = True
LIVE_REQUIRE_NATIVE_TRADINGAGENTS = True

# ============================================================
# BACKTEST REALISM CONTROLS
# ============================================================
BACKTEST_BASELINE_LATENCY_STEPS = 0
BACKTEST_LIVE_LIKE_LATENCY_STEPS = 1
BACKTEST_BASELINE_FEE = DEFAULT_TRADING_FEE
BACKTEST_LIVE_LIKE_FEE = 0.0012
BACKTEST_BASELINE_SLIPPAGE = SLIPPAGE
BACKTEST_LIVE_LIKE_SLIPPAGE = 0.0018

# ============================================================
# LOGGING
# ============================================================
LOG_LEVEL = "INFO"
