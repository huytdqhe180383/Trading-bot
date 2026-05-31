"""
Central configuration for the BTC/ETH auto-trading system.
"""

import os
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip()


def _env_csv(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return tuple(part.strip() for part in raw.split(",") if part.strip())

# ============================================================
# PROJECT PATHS
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
MODELS_DIR = BASE_DIR / "models"
REPORTS_DIR = BASE_DIR / "report"
LIVE_BASELINE_MODEL_DIR = Path(
    _env_str("LIVE_BASELINE_MODEL_DIR", str(MODELS_DIR / "live_baseline"))
)
LOGS_DIR = BASE_DIR / "logs"
RESULTS_DIR = BASE_DIR / "results"
ARCHIVE_DIR = BASE_DIR / "archive"

for d in [RAW_DATA_DIR, PROCESSED_DATA_DIR, MODELS_DIR, REPORTS_DIR, LIVE_BASELINE_MODEL_DIR, LOGS_DIR, RESULTS_DIR, ARCHIVE_DIR]:
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
BACKTEST_END = "2026-05-23"

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
REBALANCE_THRESHOLD_NORMAL = _env_float("REBALANCE_THRESHOLD_NORMAL", REBALANCE_THRESHOLD)
REBALANCE_THRESHOLD_STRESS = _env_float("REBALANCE_THRESHOLD_STRESS", 0.05)
REBALANCE_THRESHOLD_CRISIS = _env_float("REBALANCE_THRESHOLD_CRISIS", 0.08)
MIN_HOLD_BARS = _env_int("MIN_HOLD_BARS", 4)
MATERIAL_TRADE_THRESHOLD = _env_float("MATERIAL_TRADE_THRESHOLD", 0.05)
REVERSAL_HYSTERESIS_MULT = _env_float("REVERSAL_HYSTERESIS_MULT", 1.5)
POSITION_RESET_WEIGHT_THRESHOLD = _env_float("POSITION_RESET_WEIGHT_THRESHOLD", 0.05)
POSITION_RESET_PERSIST_BARS = _env_int("POSITION_RESET_PERSIST_BARS", 2)

SLIPPAGE_MODEL = _env_str("SLIPPAGE_MODEL", "flat")  # flat | vol_scaled
SLIPPAGE_VOL_WINDOW = _env_int("SLIPPAGE_VOL_WINDOW", 24)
SLIPPAGE_VOL_SCALAR = _env_float("SLIPPAGE_VOL_SCALAR", 10.0)
SLIPPAGE_VOL_CAP_MULT = _env_float("SLIPPAGE_VOL_CAP_MULT", 3.0)

KILL_SWITCH_ENABLED_EVAL = _env_bool("KILL_SWITCH_ENABLED_EVAL", False)
KILL_SWITCH_DRAWDOWN_THRESHOLD = _env_float("KILL_SWITCH_DRAWDOWN_THRESHOLD", -0.15)

STEP_TURNOVER_CAP_ENABLED = _env_bool("STEP_TURNOVER_CAP_ENABLED", False)
STEP_TURNOVER_CAP_NORMAL = _env_float("STEP_TURNOVER_CAP_NORMAL", 0.20)
STEP_TURNOVER_CAP_STRESS = _env_float("STEP_TURNOVER_CAP_STRESS", 0.12)
STEP_TURNOVER_CAP_CRISIS = _env_float("STEP_TURNOVER_CAP_CRISIS", 0.08)

REWARD_WEIGHTS = {
    "profit": _env_float("REWARD_PROFIT_WEIGHT", 1.0),
    "sharpe": _env_float("REWARD_SHARPE_WEIGHT", 0.0),
    "drawdown": _env_float("REWARD_DRAWDOWN_WEIGHT", 10.0),
    "turnover": _env_float("REWARD_TURNOVER_WEIGHT", 1.0),
    "missed_opportunity": _env_float("REWARD_MISSED_OPPORTUNITY_WEIGHT", 0.5),
    "tail_loss": _env_float("REWARD_TAIL_LOSS_WEIGHT", 2.0),
}
REWARD_ACTION_DELTA_WEIGHT = _env_float("REWARD_ACTION_DELTA_WEIGHT", 0.10)
REWARD_ACTION_DELTA_DEADBAND = _env_float("REWARD_ACTION_DELTA_DEADBAND", 0.03)
REWARD_ACTION_DELTA_SCALE = _env_float("REWARD_ACTION_DELTA_SCALE", 1.0)

TAIL_RISK_WINDOW = 24 * 7
TAIL_RISK_ALPHA = 0.05

RISK_GOVERNOR_ENABLED = _env_bool("RISK_GOVERNOR_ENABLED", True)
RISK_GOVERNOR_VOL_Z_THRESHOLD = _env_float("RISK_GOVERNOR_VOL_Z_THRESHOLD", 1.0)
RISK_GOVERNOR_DRAWDOWN_THRESHOLD = _env_float("RISK_GOVERNOR_DRAWDOWN_THRESHOLD", -0.08)
RISK_GOVERNOR_CRISIS_DRAWDOWN_THRESHOLD = _env_float("RISK_GOVERNOR_CRISIS_DRAWDOWN_THRESHOLD", -0.15)
RISK_GOVERNOR_STRESS_CASH_FLOOR = _env_float("RISK_GOVERNOR_STRESS_CASH_FLOOR", 0.25)
RISK_GOVERNOR_CRISIS_CASH_FLOOR = _env_float("RISK_GOVERNOR_CRISIS_CASH_FLOOR", 0.45)
RISK_GOVERNOR_STRESS_MAX_RISK_ON = _env_float("RISK_GOVERNOR_STRESS_MAX_RISK_ON", 0.75)
RISK_GOVERNOR_CRISIS_MAX_RISK_ON = _env_float("RISK_GOVERNOR_CRISIS_MAX_RISK_ON", 0.55)

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
TRAIN_VALIDATION_FRACTION = 0.2
TRAIN_SEED = 42

# ============================================================
# ENSEMBLE SETTINGS
# ============================================================
ENSEMBLE_METHOD = "dynamic_weighted"

# ============================================================
# LIVE TRADING SETTINGS
# ============================================================
MAX_RECONNECT_ATTEMPTS = 5
RECONNECT_DELAY_SECS = 10
REBALANCE_INTERVAL_SECS = 3600
LIVE_SESSION_TIMEZONE = _env_str("LIVE_SESSION_TIMEZONE", "Asia/Bangkok")

# ============================================================
# PRIVATE UI / PWA SETTINGS
# ============================================================
UI_USERNAME = _env_str("UI_USERNAME", "")
UI_PASSWORD = _env_str("UI_PASSWORD", "")
UI_SESSION_SECRET = _env_str("UI_SESSION_SECRET", "change-me-before-deploy")
UI_BIND_HOST = _env_str("UI_BIND_HOST", "127.0.0.1")
UI_PORT = _env_int("UI_PORT", 8080)
UI_TAIL_LINES_DEFAULT = _env_int("UI_TAIL_LINES_DEFAULT", 200)
UI_LOGIN_RATE_LIMIT = _env_int("UI_LOGIN_RATE_LIMIT", 5)
UI_ENABLE_CONTROLS = _env_bool("UI_ENABLE_CONTROLS", False)
UI_CONTROL_RATE_LIMIT = _env_int("UI_CONTROL_RATE_LIMIT", 8)
UI_SESSION_MAX_AGE_SECS = _env_int("UI_SESSION_MAX_AGE_SECS", 8 * 3600)
UI_AUDIT_LOG_PATH = LOGS_DIR / "ui_audit.jsonl"
UI_TARGET_SERVICE = _env_str("UI_TARGET_SERVICE", "trading-bot")
UI_TRUST_TAILSCALE_HEADERS = _env_bool("UI_TRUST_TAILSCALE_HEADERS", False)
UI_ALLOWED_TAILSCALE_USERS = _env_csv("UI_ALLOWED_TAILSCALE_USERS", ())
UI_ADMIN_TAILSCALE_USERS = _env_csv("UI_ADMIN_TAILSCALE_USERS", ())

# ============================================================
# SIGNAL INTEGRATION (Kronos + TradingAgents + Meta-Fusion)
# ============================================================
ENABLE_KRONOS = False
ENABLE_TRADINGAGENTS = False

KRONOS_MODEL_ID = "NeoQuasar/Kronos-mini"
KRONOS_TOKENIZER_ID = "NeoQuasar/Kronos-Tokenizer-2k"
KRONOS_FORECAST_HORIZON = 1

TRADINGAGENTS_PROVIDER = "ollama"
TRADINGAGENTS_PROVIDER_FALLBACKS = ["ollama"]
TRADINGAGENTS_DECISION_LOG_PATH = LOGS_DIR / "tradingagents_decisions.jsonl"
TRADINGAGENTS_CHECKPOINT_ENABLED = False
TRADINGAGENTS_MAX_RETRIES = 5
TRADINGAGENTS_RETRY_BACKOFF_SECS = 1.0
TRADINGAGENTS_CALL_TIMEOUT_SECS = 45.0
TRADINGAGENTS_BACKTEST_CADENCE = "weekly"
TRADINGAGENTS_LIVE_CADENCE = "hourly"

# ============================================================
# LLM RISK GATE (LOCAL OLLAMA, LOW-COST)
# ============================================================
LLM_RISK_GATE_ENABLED = True
LLM_RISK_GATE_CADENCE = "weekly"  # 6h | 24h | weekly
LLM_RISK_GATE_CACHE_TTL = 604_800
LLM_RISK_GATE_MAX_CALLS_PER_DAY = 8
LLM_RISK_GATE_MODE = "de_risk"  # allow_only | de_risk | block
LLM_RISK_GATE_TIMEOUT_SECS = 5.0
LLM_RISK_GATE_MAX_RETRIES = 1
LLM_RISK_GATE_DECISION_LOG_PATH = LOGS_DIR / "llm_risk_gate_decisions.jsonl"

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
