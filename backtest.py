"""
Backtesting runner with Kronos/TradingAgents ablation matrix and realism profiles.
"""

from __future__ import annotations

import argparse
import shutil
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from loguru import logger

from adapters import KronosAdapter, LLMRiskGateAdapter, TradingAgentsAdapter
from agents.ensemble_agent import EnsembleAgent, compute_regime_weighted_scores, load_ensemble
from agents.meta_fusion_agent import MetaFusionAgent
from config import (
    BACKTEST_BASELINE_FEE,
    BACKTEST_BASELINE_LATENCY_STEPS,
    BACKTEST_BASELINE_SLIPPAGE,
    BACKTEST_END,
    BACKTEST_START,
    BASE_TIMEFRAME,
    BACKTEST_LIVE_LIKE_FEE,
    BACKTEST_LIVE_LIKE_LATENCY_STEPS,
    BACKTEST_LIVE_LIKE_SLIPPAGE,
    ENSEMBLE_METHOD,
    INITIAL_CAPITAL,
    KRONOS_FORECAST_HORIZON,
    KRONOS_MODEL_ID,
    KRONOS_TOKENIZER_ID,
    LLM_RISK_GATE_CACHE_TTL,
    LLM_RISK_GATE_CADENCE,
    LLM_RISK_GATE_DECISION_LOG_PATH,
    LLM_RISK_GATE_ENABLED,
    LLM_RISK_GATE_MAX_CALLS_PER_DAY,
    LLM_RISK_GATE_MAX_RETRIES,
    LLM_RISK_GATE_MODE,
    LLM_RISK_GATE_TIMEOUT_SECS,
    LOOKBACK_WINDOW,
    MAX_ASSET_WEIGHT,
    MAX_PORTFOLIO_TURNOVER,
    MAX_TILT_PER_SIGNAL,
    LIVE_BASELINE_MODEL_DIR,
    MIN_CASH_FLOOR,
    MODELS_DIR,
    MATERIAL_TRADE_THRESHOLD,
    MIN_HOLD_BARS,
    POSITION_RESET_PERSIST_BARS,
    POSITION_RESET_WEIGHT_THRESHOLD,
    PROCESSED_DATA_DIR,
    REBALANCE_THRESHOLD_CRISIS,
    REBALANCE_THRESHOLD_NORMAL,
    REBALANCE_THRESHOLD_STRESS,
    REVERSAL_HYSTERESIS_MULT,
    RAW_DATA_DIR,
    RESULTS_DIR,
    SYMBOLS,
    TRADINGAGENTS_CALL_TIMEOUT_SECS,
    TRADINGAGENTS_BACKTEST_CADENCE,
    TRADINGAGENTS_CHECKPOINT_ENABLED,
    TRADINGAGENTS_DECISION_LOG_PATH,
    TRADINGAGENTS_MAX_RETRIES,
    TRADINGAGENTS_PROVIDER_FALLBACKS,
    TRADINGAGENTS_RETRY_BACKOFF_SECS,
)
from environment.trading_env import BinanceSpotEnv, _softmax_weights
import environment.trading_env as trading_env_module
from metrics.performance import (
    compute_metrics,
    plot_ensemble_method_comparison,
    plot_equity_curve,
    plot_kpi_radar,
)
from data.kronos_windows import load_raw_ohlcv_data, window_raw_ohlcv
from risk.post_policy_overlay import apply_post_policy_overlay
from tradingbot.runtime.artifacts import create_numbered_daily_dir, write_json_artifact

load_dotenv()

PIPELINES = {
    "rl_only": {"kronos": False, "tradingagents": False},
    "rl_kronos": {"kronos": True, "tradingagents": False},
    "rl_tradingagents": {"kronos": False, "tradingagents": True},
    "rl_full": {"kronos": True, "tradingagents": True},
    "rl_llm_risk_gate": {"kronos": False, "tradingagents": False, "llm_risk_gate": True},
}

REALISM = {
    "baseline": {
        "fee": BACKTEST_BASELINE_FEE,
        "slippage": BACKTEST_BASELINE_SLIPPAGE,
        "latency_steps": BACKTEST_BASELINE_LATENCY_STEPS,
    },
    "live_like": {
        "fee": BACKTEST_LIVE_LIKE_FEE,
        "slippage": BACKTEST_LIVE_LIKE_SLIPPAGE,
        "latency_steps": BACKTEST_LIVE_LIKE_LATENCY_STEPS,
    },
}

ENSEMBLE_METHODS = ["mean", "voting", "weighted", "dynamic_weighted", "regime_weighted", "imca"]
DEFAULT_COMPARISON_METHODS = ["mean", "weighted", "dynamic_weighted", "regime_weighted"]
POST_POLICY_OVERLAYS = ["none", "champion_guard"]


def create_backtest_session_dir(results_dir: Path = RESULTS_DIR, *, run_date: str | None = None) -> Path:
    """Create results/daily/YYYY-MM-DD/N without overwriting prior sessions."""
    return create_numbered_daily_dir(results_dir, run_date)


def create_best_model_snapshot_dir(models_dir: Path = MODELS_DIR, *, run_date: str | None = None) -> Path:
    """Create models/best/YYYY-MM-DD/N without overwriting prior champion snapshots."""
    day = run_date or datetime.now().strftime("%Y-%m-%d")
    daily_dir = Path(models_dir) / "best" / day
    daily_dir.mkdir(parents=True, exist_ok=True)
    existing_numbers = [
        int(child.name)
        for child in daily_dir.iterdir()
        if child.is_dir() and child.name.isdigit()
    ]
    next_number = max(existing_numbers, default=0) + 1
    session_dir = daily_dir / str(next_number)
    session_dir.mkdir(parents=True, exist_ok=False)
    return session_dir


def parse_method_list(raw: str) -> list[str]:
    methods = [item.strip() for item in raw.split(",") if item.strip()]
    invalid = sorted(set(methods).difference(ENSEMBLE_METHODS))
    if invalid:
        raise argparse.ArgumentTypeError(f"Invalid ensemble methods: {invalid}. Valid: {ENSEMBLE_METHODS}")
    if not methods:
        raise argparse.ArgumentTypeError("At least one ensemble method is required.")
    return methods


def parse_overlay_name(raw: str) -> str:
    name = raw.strip().lower()
    if name not in POST_POLICY_OVERLAYS:
        raise argparse.ArgumentTypeError(f"Invalid post-policy overlay: {name}. Valid: {POST_POLICY_OVERLAYS}")
    return name


def resolve_backtest_model_dir(model_dir: Path | None = None) -> Path:
    candidate = Path(model_dir) if model_dir is not None else LIVE_BASELINE_MODEL_DIR
    if (candidate / "PPO" / "ppo_best.zip").exists() and (candidate / "SAC" / "sac_best.zip").exists():
        return candidate
    return MODELS_DIR


def apply_execution_control_overrides(args: argparse.Namespace) -> None:
    trading_env_module.REBALANCE_THRESHOLD_NORMAL = float(args.rebalance_threshold_normal)
    trading_env_module.REBALANCE_THRESHOLD_STRESS = float(args.rebalance_threshold_stress)
    trading_env_module.REBALANCE_THRESHOLD_CRISIS = float(args.rebalance_threshold_crisis)
    trading_env_module.MIN_HOLD_BARS = int(args.min_hold_bars)
    trading_env_module.MATERIAL_TRADE_THRESHOLD = float(args.material_trade_threshold)
    trading_env_module.REVERSAL_HYSTERESIS_MULT = float(args.reversal_hysteresis_mult)
    trading_env_module.POSITION_RESET_WEIGHT_THRESHOLD = float(args.position_reset_weight_threshold)
    trading_env_module.POSITION_RESET_PERSIST_BARS = int(args.position_reset_persist_bars)


def _apply_named_post_policy_overlay(
    *,
    overlay_name: str,
    env: BinanceSpotEnv,
    target_weights: np.ndarray,
    current_weights: np.ndarray,
    target_volatility: float,
    persistence_turnover_cap: float,
    trend_gate_threshold: float,
    trend_gate_multiplier: float,
    drawdown_gate_threshold: float,
    drawdown_gate_multiplier: float,
) -> tuple[np.ndarray, dict[str, Any]]:
    if overlay_name == "none":
        return target_weights.astype(np.float32), {
            "name": "none",
            "applied": False,
            "volatility_scale": 1.0,
            "turnover_before": float(np.abs(target_weights[:-1] - current_weights[:-1]).sum()),
            "turnover_after": float(np.abs(target_weights[:-1] - current_weights[:-1]).sum()),
            "trend_gate_applied": False,
            "drawdown_gate_applied": False,
        }

    regime = env.get_market_regime()
    adjusted, diagnostics = apply_post_policy_overlay(
        target_weights=target_weights,
        current_weights=current_weights,
        realized_volatility=float(env._current_volatility_proxy()),
        target_volatility=float(target_volatility),
        macro_trend=float(regime.get("macro_trend", 0.0)),
        current_drawdown=float(env._current_abs_drawdown()),
        persistence_turnover_cap=float(persistence_turnover_cap),
        trend_gate_threshold=float(trend_gate_threshold),
        trend_gate_multiplier=float(trend_gate_multiplier),
        drawdown_gate_threshold=float(drawdown_gate_threshold),
        drawdown_gate_multiplier=float(drawdown_gate_multiplier),
    )
    diagnostics = {"name": overlay_name, "applied": True, **diagnostics}
    return adjusted.astype(np.float32), diagnostics


def write_session_metadata(session_dir: Path, metadata: dict[str, Any]) -> None:
    write_json_artifact(Path(session_dir) / "session_metadata.json", metadata)


def write_trade_decision_log(episode_df: pd.DataFrame, output_path: Path) -> None:
    """Save a compact, inspectable per-step decision log for a backtest episode."""
    preferred_cols = [
        "portfolio_value",
        "btc_weight",
        "eth_weight",
        "cash_weight",
        "rl_btc_weight",
        "rl_eth_weight",
        "rl_cash_weight",
        "target_btc_weight",
        "target_eth_weight",
        "target_cash_weight",
        "turnover",
        "turnover_before_cap",
        "turnover_after_cap",
        "turnover_cap_applied",
        "turnover_cap_limit",
        "transaction_cost",
        "effective_slippage",
        "slippage_volatility_proxy",
        "step_reward",
        "raw_log_return",
        "profit_component",
        "drawdown_component",
        "turnover_component",
        "raw_action_delta",
        "action_delta_component",
        "opportunity_component",
        "requested_weight_delta",
        "executed_weight_delta",
        "rebalance_threshold",
        "execution_regime_label",
        "rebalance_blocked_by_deadband",
        "rebalance_blocked_by_cooldown",
        "rebalance_blocked_by_hysteresis",
        "rebalance_forced_by_governor",
        "rebalance_forced_by_trailing_stop",
        "trailing_stop_liquidation_count",
        "trailing_stop_liquidation_assets",
        "position_reset_triggered",
        "position_reset_reason",
        "bars_since_last_material_trade",
        "material_trade_executed",
        "abs_drawdown",
        "rolling_drawdown",
        "risk_governor_active",
        "risk_governor_reason",
        "kronos_available",
        "kronos_signal_count",
        "kronos_sources",
        "kronos_btc_directional_score",
        "kronos_eth_directional_score",
        "kronos_btc_confidence",
        "kronos_eth_confidence",
        "kronos_btc_tilt",
        "kronos_eth_tilt",
        "tradingagents_available",
        "tradingagents_source",
        "llm_risk_available",
        "llm_risk_flag",
        "llm_risk_confidence",
        "llm_risk_source",
        "llm_risk_cached",
        "llm_risk_call_budget_exhausted",
        "llm_risk_gate_mode",
        "llm_risk_applied",
        "post_policy_overlay_enabled",
        "post_policy_overlay_name",
        "post_policy_volatility_scale",
        "post_policy_turnover_before",
        "post_policy_turnover_after",
        "post_policy_trend_gate_applied",
        "post_policy_drawdown_gate_applied",
        "fusion_has_kronos",
        "fusion_has_trading_signal",
        "fusion_has_llm_risk",
        "fusion_turnover_pre_clip",
        "fusion_turnover_post_clip",
        "fusion_turnover_clip_ratio",
        "fusion_constraint_clipped",
        "fusion_mechanism_label",
        "fusion_pre_constraint_btc_weight",
        "fusion_pre_constraint_eth_weight",
        "fusion_pre_constraint_cash_weight",
        "fusion_post_constraint_btc_weight",
        "fusion_post_constraint_eth_weight",
        "fusion_post_constraint_cash_weight",
        "ppo_btc_weight",
        "ppo_eth_weight",
        "ppo_cash_weight",
        "sac_btc_weight",
        "sac_eth_weight",
        "sac_cash_weight",
        "ensemble_model_weight_ppo",
        "ensemble_model_weight_sac",
        "ensemble_regime_label",
        "ensemble_stress_strength",
    ]
    cols = [col for col in preferred_cols if col in episode_df.columns]
    decisions = episode_df[cols].copy()
    decisions.insert(0, "timestamp", episode_df.index.astype(str))
    decisions.to_csv(output_path, index=False)


def _average_holding_duration(series: pd.Series, *, threshold: float) -> float:
    active = series.fillna(0.0).to_numpy(dtype=np.float32) > float(threshold)
    durations: list[int] = []
    run = 0
    for flag in active:
        if flag:
            run += 1
        elif run:
            durations.append(run)
            run = 0
    if run:
        durations.append(run)
    if not durations:
        return 0.0
    return float(np.mean(durations))


def _reversal_within_n_bars_rate(
    episode_df: pd.DataFrame,
    *,
    n_bars: int = 6,
) -> float:
    if "material_trade_executed" not in episode_df.columns:
        return 0.0
    trades = episode_df[episode_df["material_trade_executed"].fillna(False)].copy()
    if len(trades) < 2:
        return 0.0
    reversals = 0
    opportunities = 0
    previous_direction: np.ndarray | None = None
    previous_position: int | None = None
    for position, (_, row) in enumerate(trades.iterrows()):
        direction = np.sign(
            np.array(
                [
                    float(row.get("btc_weight", 0.0)) - float(row.get("rl_btc_weight", 0.0)),
                    float(row.get("eth_weight", 0.0)) - float(row.get("rl_eth_weight", 0.0)),
                ],
                dtype=np.float32,
            )
        )
        if previous_direction is not None and previous_position is not None:
            if position - previous_position <= int(n_bars):
                opportunities += 1
                if np.any((direction != 0.0) & (previous_direction != 0.0) & (direction != previous_direction)):
                    reversals += 1
        previous_direction = direction
        previous_position = position
    if opportunities == 0:
        return 0.0
    return float(reversals / opportunities)


def build_trade_diagnostics_tables(
    episode_df: pd.DataFrame,
    *,
    hold_threshold: float = POSITION_RESET_WEIGHT_THRESHOLD,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df = episode_df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    material_trades = df["material_trade_executed"].fillna(False) if "material_trade_executed" in df else pd.Series(False, index=df.index)
    executed_delta = df.get("executed_weight_delta", pd.Series(0.0, index=df.index)).fillna(0.0)
    turnover = df.get("turnover", pd.Series(0.0, index=df.index)).fillna(0.0)

    summary = pd.DataFrame(
        [
            {
                "rows": int(len(df)),
                "change_rate": float((executed_delta > 0.0).mean()) if len(df) else 0.0,
                "mean_turnover": float(turnover.mean()) if len(df) else 0.0,
                "p95_turnover": float(turnover.quantile(0.95)) if len(df) else 0.0,
                "material_trade_count": int(material_trades.sum()),
                "trailing_stop_liquidation_count": int(df.get("trailing_stop_liquidation_count", pd.Series(0, index=df.index)).fillna(0).sum()),
                "sub_threshold_blocked_count": int(df.get("rebalance_blocked_by_deadband", pd.Series(False, index=df.index)).fillna(False).sum()),
                "cooldown_blocked_count": int(df.get("rebalance_blocked_by_cooldown", pd.Series(False, index=df.index)).fillna(False).sum()),
                "hysteresis_blocked_count": int(df.get("rebalance_blocked_by_hysteresis", pd.Series(False, index=df.index)).fillna(False).sum()),
                "position_reset_trigger_count": int(df.get("position_reset_triggered", pd.Series(False, index=df.index)).fillna(False).sum()),
                "btc_avg_holding_bars": _average_holding_duration(df.get("btc_weight", pd.Series(0.0, index=df.index)), threshold=hold_threshold),
                "eth_avg_holding_bars": _average_holding_duration(df.get("eth_weight", pd.Series(0.0, index=df.index)), threshold=hold_threshold),
                "reversal_within_6_bars_rate": _reversal_within_n_bars_rate(df, n_bars=6),
            }
        ]
    )

    month_index = df.index.tz_convert("UTC").tz_localize(None) if getattr(df.index, "tz", None) is not None else df.index
    monthly = (
        df.assign(month=month_index.to_period("M").astype(str))
        .groupby("month", dropna=False)
        .agg(
            change_rate=("executed_weight_delta", lambda s: float((s.fillna(0.0) > 0.0).mean())),
            mean_turnover=("turnover", "mean"),
            material_trade_count=("material_trade_executed", "sum"),
            transaction_cost=("transaction_cost", "sum"),
            trailing_stop_liquidation_count=("trailing_stop_liquidation_count", "sum"),
        )
        .reset_index()
    )

    regime = (
        df.assign(execution_regime_label=df.get("execution_regime_label", pd.Series("", index=df.index)).fillna("unknown"))
        .groupby("execution_regime_label", dropna=False)
        .agg(
            steps=("execution_regime_label", "size"),
            change_rate=("executed_weight_delta", lambda s: float((s.fillna(0.0) > 0.0).mean())),
            mean_turnover=("turnover", "mean"),
            material_trade_count=("material_trade_executed", "sum"),
            blocked_by_deadband=("rebalance_blocked_by_deadband", "sum"),
            blocked_by_cooldown=("rebalance_blocked_by_cooldown", "sum"),
            blocked_by_hysteresis=("rebalance_blocked_by_hysteresis", "sum"),
        )
        .reset_index()
    )

    block = pd.DataFrame(
        [
            {
                "deadband_block_rate": float(df.get("rebalance_blocked_by_deadband", pd.Series(False, index=df.index)).fillna(False).mean()) if len(df) else 0.0,
                "cooldown_block_rate": float(df.get("rebalance_blocked_by_cooldown", pd.Series(False, index=df.index)).fillna(False).mean()) if len(df) else 0.0,
                "hysteresis_block_rate": float(df.get("rebalance_blocked_by_hysteresis", pd.Series(False, index=df.index)).fillna(False).mean()) if len(df) else 0.0,
                "forced_by_governor_rate": float(df.get("rebalance_forced_by_governor", pd.Series(False, index=df.index)).fillna(False).mean()) if len(df) else 0.0,
                "forced_by_trailing_stop_rate": float(df.get("rebalance_forced_by_trailing_stop", pd.Series(False, index=df.index)).fillna(False).mean()) if len(df) else 0.0,
            }
        ]
    )
    return summary, monthly, regime, block


def write_trade_diagnostics_tables(
    episode_df: pd.DataFrame,
    *,
    output_dir: Path,
    stem: str,
) -> None:
    summary, monthly, regime, block = build_trade_diagnostics_tables(episode_df)
    summary.to_csv(output_dir / f"trade_diagnostics_summary_{stem}.csv", index=False)
    monthly.to_csv(output_dir / f"trade_diagnostics_monthly_{stem}.csv", index=False)
    regime.to_csv(output_dir / f"trade_diagnostics_regime_{stem}.csv", index=False)
    block.to_csv(output_dir / f"trade_diagnostics_block_rates_{stem}.csv", index=False)


def maybe_save_best_model_snapshot(
    *,
    metrics: dict[str, Any],
    source_model_dir: Path,
    best_root_dir: Path = MODELS_DIR,
    run_label: str,
    session_dir: Path,
    run_date: str | None = None,
    profit_threshold_pct: float = 70.0,
) -> Path | None:
    """Preserve current PPO/SAC checkpoints once a backtest clears the profit threshold."""
    total_return = float(metrics.get("total_return_pct", 0.0))
    if total_return <= float(profit_threshold_pct):
        return None

    source_model_dir = Path(source_model_dir)
    source_paths = {
        "PPO": source_model_dir / "PPO" / "ppo_best.zip",
        "SAC": source_model_dir / "SAC" / "sac_best.zip",
    }
    missing = [name for name, path in source_paths.items() if not path.exists()]
    if missing:
        logger.warning(f"Skipping best-model snapshot for {run_label}; missing checkpoints for {missing}.")
        return None

    snapshot_dir = create_best_model_snapshot_dir(best_root_dir, run_date=run_date)
    models_out = snapshot_dir / "models"
    for algo, src in source_paths.items():
        dst = models_out / algo / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    metadata = {
        "created_at": datetime.now().isoformat(),
        "run_label": run_label,
        "profit_threshold_pct": float(profit_threshold_pct),
        "metrics": metrics,
        "source_model_dir": str(source_model_dir),
        "source_session_dir": str(session_dir),
    }
    write_json_artifact(snapshot_dir / "snapshot_metadata.json", metadata)
    logger.success(
        f"Saved best-model snapshot for {run_label} with return {total_return:.2f}% -> {snapshot_dir}"
    )
    return snapshot_dir


def load_test_data() -> dict[str, pd.DataFrame]:
    return {sym: pd.read_parquet(PROCESSED_DATA_DIR / f"{sym}_test.parquet") for sym in SYMBOLS}


def load_kronos_raw_data() -> dict[str, pd.DataFrame]:
    return load_raw_ohlcv_data(
        SYMBOLS,
        raw_data_dir=RAW_DATA_DIR,
        start=BACKTEST_START,
        end=BACKTEST_END,
        timeframe=BASE_TIMEFRAME,
    )


def build_benchmark_nav(test_data: dict[str, pd.DataFrame]) -> pd.Series:
    bench_returns = np.mean([np.exp(test_data[s]["log_return_1h"].cumsum()) for s in SYMBOLS], axis=0)
    return pd.Series(bench_returns * INITIAL_CAPITAL, index=test_data[SYMBOLS[0]].index, name="benchmark_nav")


def _print_metrics(label: str, metrics: dict[str, float]) -> None:
    logger.info(
        f"[{label}] return={metrics.get('total_return_pct', 0):.2f}% "
        f"sharpe={metrics.get('sharpe_ratio', 0):.4f} "
        f"max_dd={metrics.get('max_drawdown_pct', 0):.2f}% "
        f"trades={metrics.get('total_trades_count', 0):.0f}"
    )


def _window_state(test_data: dict[str, pd.DataFrame], step_idx: int) -> dict[str, pd.DataFrame]:
    start = max(0, step_idx - LOOKBACK_WINDOW)
    return {sym: test_data[sym].iloc[start:step_idx].copy() for sym in SYMBOLS}


def _episode_diagnostics(df: pd.DataFrame) -> dict[str, float]:
    diagnostics: dict[str, float] = {
        "turnover_sum": float(df["turnover"].sum()) if "turnover" in df else 0.0,
        "turnover_mean": float(df["turnover"].mean()) if "turnover" in df else 0.0,
        "transaction_cost_sum": float(df["transaction_cost"].sum()) if "transaction_cost" in df else 0.0,
        "transaction_cost_mean": float(df["transaction_cost"].mean()) if "transaction_cost" in df else 0.0,
        "raw_action_delta_mean": float(df["raw_action_delta"].mean()) if "raw_action_delta" in df else 0.0,
        "action_delta_component_mean": float(df["action_delta_component"].mean()) if "action_delta_component" in df else 0.0,
        "effective_slippage_mean": float(df["effective_slippage"].mean()) if "effective_slippage" in df else 0.0,
        "turnover_cap_applied_rate": float(df["turnover_cap_applied"].mean()) if "turnover_cap_applied" in df else 0.0,
        "cash_weight_mean": float(df["cash_weight"].mean()) if "cash_weight" in df else 0.0,
        "cash_weight_p95": float(df["cash_weight"].quantile(0.95)) if "cash_weight" in df else 0.0,
        "risk_on_mean": float((df["btc_weight"] + df["eth_weight"]).mean())
        if {"btc_weight", "eth_weight"}.issubset(df.columns)
        else 0.0,
        "risk_governor_active_rate": float(df["risk_governor_active"].mean())
        if "risk_governor_active" in df
        else 0.0,
    }
    if "transaction_cost" in df:
        cost_multiplier = float((1.0 - df["transaction_cost"]).prod())
        diagnostics["cost_multiplier"] = cost_multiplier
        diagnostics["cost_drag_pct"] = (cost_multiplier - 1.0) * 100.0
    if {"target_btc_weight", "target_eth_weight", "rl_btc_weight", "rl_eth_weight"}.issubset(df.columns):
        delta_action = (
            (df["target_btc_weight"] - df["rl_btc_weight"]).abs()
            + (df["target_eth_weight"] - df["rl_eth_weight"]).abs()
        )
        threshold = 0.02
        diagnostics["kronos_action_change_rate_gt_0p02"] = float((delta_action > threshold).mean())
        if "kronos_available" in df:
            mask = df["kronos_available"].astype(bool)
            diagnostics["kronos_action_change_rate_gt_0p02_when_available"] = (
                float((delta_action[mask] > threshold).mean()) if mask.any() else 0.0
            )

        risk_delta = (
            (df["target_btc_weight"] + df["target_eth_weight"])
            - (df["rl_btc_weight"] + df["rl_eth_weight"])
        )
        direction = np.sign(risk_delta.values)
        strong = np.abs(risk_delta.values) > threshold
        reversals = 0
        eligible = 0
        horizon = 3
        for i in range(len(direction) - horizon):
            if not strong[i]:
                continue
            eligible += 1
            if np.any(direction[i + 1 : i + 1 + horizon] * direction[i] < 0):
                reversals += 1
        diagnostics["kronos_reversal_rate_within_3_steps"] = float(reversals / eligible) if eligible > 0 else 0.0
    return diagnostics


def _risk_adjusted_model_score(returns: np.ndarray) -> float:
    mean_ret = float(returns.mean())
    std_ret = float(returns.std()) + 1e-9
    sharpe = (mean_ret / std_ret) * np.sqrt(24 * 365)

    equity = np.cumprod(1.0 + returns)
    peak = np.maximum.accumulate(equity)
    max_dd = abs(float(((equity - peak) / (peak + 1e-9)).min()))

    tail_threshold = float(np.quantile(returns, 0.05))
    tail = returns[returns <= tail_threshold]
    cvar = abs(float(tail.mean())) if len(tail) else 0.0

    score = sharpe - (max_dd * 4.0) - (cvar * np.sqrt(24 * 365) * 2.0)
    return max(float(score), 0.1)


def _update_adaptive_ensemble_weights(
    *,
    method: str,
    agent: EnsembleAgent,
    env: BinanceSpotEnv,
    returns_history: dict[str, deque],
) -> None:
    if method == "dynamic_weighted":
        current = {}
        for algo, hist in returns_history.items():
            if len(hist) > 10:
                arr = np.array(hist, dtype=np.float32)
                current[algo] = _risk_adjusted_model_score(arr)
            else:
                current[algo] = 1.0
        agent._sharpes = current
        agent._model_mix_diagnostics = {"regime_label": "dynamic", "stress_strength": 0.0, **current}
        return

    if method == "regime_weighted":
        base_scores = {}
        for algo, hist in returns_history.items():
            if len(hist) > 10:
                arr = np.array(hist, dtype=np.float32)
                base_scores[algo] = _risk_adjusted_model_score(arr)
            else:
                base_scores[algo] = 1.0
        rolling_peak = max(env._rolling_window) if len(env._rolling_window) else env._portfolio
        rolling_drawdown = float((env._portfolio - rolling_peak) / (rolling_peak + 1e-9))
        regime = env.get_market_regime()
        scores, diagnostics = compute_regime_weighted_scores(
            base_scores=base_scores,
            returns_history=returns_history,
            volatility_z=float(regime["volatility_z"]),
            macro_trend=float(regime["macro_trend"]),
            rolling_drawdown=rolling_drawdown,
        )
        agent._sharpes = scores
        agent._model_mix_diagnostics = {**diagnostics, **scores}
        return

    if method == "imca":
        regime = env.get_market_regime()
        vol_z = float(regime["volatility_z"])
        macro_trend = float(regime["macro_trend"])
        sac_weight = 1.0 / (1.0 + np.exp(-vol_z))
        if macro_trend > 0.05:
            sac_weight *= 0.5
        ppo_weight = 1.0 - sac_weight
        agent._sharpes = {"PPO": ppo_weight, "SAC": sac_weight}
        agent._model_mix_diagnostics = {"regime_label": "imca", "stress_strength": float(np.clip(vol_z, 0.0, 1.0)), "PPO": ppo_weight, "SAC": sac_weight}


def run_backtest(
    *,
    test_data: dict[str, pd.DataFrame],
    raw_ohlcv_data: dict[str, pd.DataFrame] | None = None,
    method: str,
    pipeline: str,
    realism_profile: str,
    model_dir: Path = MODELS_DIR,
    post_policy_overlay: str = "none",
    overlay_target_volatility: float = 0.04,
    overlay_persistence_turnover_cap: float = 0.15,
    overlay_trend_gate_threshold: float = 0.0,
    overlay_trend_gate_multiplier: float = 0.75,
    overlay_drawdown_gate_threshold: float = -0.10,
    overlay_drawdown_gate_multiplier: float = 0.70,
) -> tuple[pd.DataFrame, int, dict[str, Any]]:
    profile = REALISM[realism_profile]
    env = BinanceSpotEnv(
        test_data,
        initial_capital=INITIAL_CAPITAL,
        trading_fee=profile["fee"],
        slippage=profile["slippage"],
        mode="eval",
    )

    ensemble = load_ensemble(model_dir)
    agent = EnsembleAgent(ensemble, method=method)
    pipe_flags = PIPELINES[pipeline]

    kronos = None
    ta_adapter = None
    llm_risk_gate = None
    fusion = None
    if pipe_flags.get("kronos") or pipe_flags.get("tradingagents") or pipe_flags.get("llm_risk_gate"):
        fusion = MetaFusionAgent(
            symbols=SYMBOLS,
            max_tilt_per_signal=MAX_TILT_PER_SIGNAL,
            max_portfolio_turnover=MAX_PORTFOLIO_TURNOVER,
            max_asset_weight=MAX_ASSET_WEIGHT,
            min_cash_floor=MIN_CASH_FLOOR,
            llm_risk_gate_mode=LLM_RISK_GATE_MODE,
        )
    if pipe_flags.get("kronos"):
        kronos = KronosAdapter(
            enabled=True,
            model_id=KRONOS_MODEL_ID,
            tokenizer_id=KRONOS_TOKENIZER_ID,
            forecast_horizon=KRONOS_FORECAST_HORIZON,
        )
    if pipe_flags.get("tradingagents"):
        ta_adapter = TradingAgentsAdapter(
            enabled=True,
            provider=TRADINGAGENTS_PROVIDER_FALLBACKS,
            decision_log_path=TRADINGAGENTS_DECISION_LOG_PATH,
            max_retries=TRADINGAGENTS_MAX_RETRIES,
            retry_backoff_secs=TRADINGAGENTS_RETRY_BACKOFF_SECS,
            call_timeout_secs=TRADINGAGENTS_CALL_TIMEOUT_SECS,
            checkpoint_enabled=TRADINGAGENTS_CHECKPOINT_ENABLED,
            cadence=TRADINGAGENTS_BACKTEST_CADENCE,
        )
    if pipe_flags.get("llm_risk_gate"):
        llm_risk_gate = LLMRiskGateAdapter(
            enabled=LLM_RISK_GATE_ENABLED,
            cadence=LLM_RISK_GATE_CADENCE,
            cache_ttl_secs=LLM_RISK_GATE_CACHE_TTL,
            max_calls_per_day=LLM_RISK_GATE_MAX_CALLS_PER_DAY,
            timeout_secs=LLM_RISK_GATE_TIMEOUT_SECS,
            max_retries=LLM_RISK_GATE_MAX_RETRIES,
            decision_log_path=LLM_RISK_GATE_DECISION_LOG_PATH,
        )

    obs, _ = env.reset()
    records: list[dict[str, Any]] = []
    done = False
    latency_steps = int(profile["latency_steps"])
    pending_weights: deque[np.ndarray] = deque()

    returns_history = {algo: deque(maxlen=24 * 7) for algo in ensemble.keys()}
    virtual_weights = {algo: np.array([0.0, 0.0, 1.0], dtype=np.float32) for algo in ensemble.keys()}

    while not done:
        _update_adaptive_ensemble_weights(method=method, agent=agent, env=env, returns_history=returns_history)

        proposals = {}
        for algo, model in ensemble.items():
            raw_action, _ = model.predict(obs, deterministic=True)
            proposals[algo] = _softmax_weights(raw_action)

        rl_weights = agent.predict(obs)
        timestamp = env._index[env._step_idx - 1]
        state_window = _window_state(test_data, env._step_idx)
        kronos_window = (
            window_raw_ohlcv(
                raw_ohlcv_data,
                timestamp=pd.Timestamp(timestamp),
                lookback=kronos.max_context,
            )
            if kronos is not None and raw_ohlcv_data is not None
            else state_window
        )

        if fusion is not None:
            kronos_signals = kronos.predict_batch(kronos_window, timestamp=pd.Timestamp(timestamp)) if kronos else None
            ta_signal = (
                ta_adapter.evaluate(
                    ticker=SYMBOLS[0],
                    asof=pd.Timestamp(timestamp),
                    market_snapshot=state_window[SYMBOLS[0]],
                )
                if ta_adapter
                else None
            )
            llm_risk_signal = (
                llm_risk_gate.evaluate(
                    asof=pd.Timestamp(timestamp),
                    market_state=state_window,
                    drawdown=float(env._current_abs_drawdown()),
                    rolling_drawdown=float(
                        (env._portfolio - max(env._rolling_window)) / (max(env._rolling_window) + 1e-9)
                    ),
                    volatility_z=float(env.get_market_regime().get("volatility_z", 0.0)),
                )
                if llm_risk_gate
                else None
            )
            target_weights, fusion_diag = fusion.fuse(
                rl_weights=rl_weights,
                current_weights=env._weights.copy(),
                kronos_signals=kronos_signals,
                trading_signal=ta_signal,
                llm_risk_signal=llm_risk_signal,
            )
        else:
            target_weights = rl_weights
            kronos_signals = None
            ta_signal = None
            llm_risk_signal = None
            fusion_diag = None

        target_weights, overlay_diag = _apply_named_post_policy_overlay(
            overlay_name=post_policy_overlay,
            env=env,
            target_weights=target_weights,
            current_weights=env._weights.copy(),
            target_volatility=overlay_target_volatility,
            persistence_turnover_cap=overlay_persistence_turnover_cap,
            trend_gate_threshold=overlay_trend_gate_threshold,
            trend_gate_multiplier=overlay_trend_gate_multiplier,
            drawdown_gate_threshold=overlay_drawdown_gate_threshold,
            drawdown_gate_multiplier=overlay_drawdown_gate_multiplier,
        )

        pending_weights.append(target_weights.astype(np.float32))
        if latency_steps > 0:
            if len(pending_weights) > latency_steps:
                exec_weights = pending_weights.popleft()
            else:
                exec_weights = env._weights.copy()
        else:
            exec_weights = target_weights

        market_returns = env._get_returns()
        for algo in ensemble.keys():
            old_w = virtual_weights[algo]
            prop = proposals[algo]
            tc = env._compute_transaction_cost(old_w, prop)
            asset_pnl = float(np.dot(prop[:-1], market_returns - 1.0))
            net_ret = (1.0 + asset_pnl) * (1.0 - tc)
            returns_history[algo].append(net_ret - 1.0)
            virtual_weights[algo] = prop

        prev_weights = env._weights.copy()
        obs, reward, terminated, truncated, info = env.step_weights(exec_weights)
        done = terminated or truncated
        turnover = float(np.abs(info["weights"][:-1] - prev_weights[:-1]).sum())
        risk_governor_diag = info.get("risk_governor", {}) or {}
        turnover_cap_diag = info.get("turnover_cap", {}) or {}

        record = {
            "timestamp": info["timestamp"],
            "portfolio_value": info["portfolio_value"],
            "btc_weight": info["weights"][0],
            "eth_weight": info["weights"][1],
            "cash_weight": info["weights"][2],
            "transaction_cost": info["transaction_cost"],
            "turnover": turnover,
            "turnover_before_cap": turnover_cap_diag.get("before", turnover),
            "turnover_after_cap": turnover_cap_diag.get("after", turnover),
            "turnover_cap_applied": bool(turnover_cap_diag.get("applied", False)),
            "turnover_cap_limit": turnover_cap_diag.get("limit", 0.0),
            "effective_slippage": info.get("effective_slippage", np.nan),
            "slippage_volatility_proxy": info.get("slippage_volatility_proxy", np.nan),
            "step_reward": reward,
            "raw_log_return": info.get("raw_log_return", 0.0),
            "profit_component": info.get("profit_component", 0.0),
            "drawdown_component": info.get("drawdown_component", 0.0),
            "turnover_component": info.get("turnover_component", 0.0),
            "raw_action_delta": info.get("raw_action_delta", 0.0),
            "action_delta_component": info.get("action_delta_component", 0.0),
            "opportunity_component": info.get("opportunity_component", 0.0),
            "requested_weight_delta": info.get("requested_weight_delta", 0.0),
            "executed_weight_delta": info.get("executed_weight_delta", turnover),
            "rebalance_threshold": info.get("rebalance_threshold", np.nan),
            "execution_regime_label": info.get("execution_regime_label", ""),
            "rebalance_blocked_by_deadband": bool(info.get("rebalance_blocked_by_deadband", False)),
            "rebalance_blocked_by_cooldown": bool(info.get("rebalance_blocked_by_cooldown", False)),
            "rebalance_blocked_by_hysteresis": bool(info.get("rebalance_blocked_by_hysteresis", False)),
            "rebalance_forced_by_governor": bool(info.get("rebalance_forced_by_governor", False)),
            "rebalance_forced_by_trailing_stop": bool(info.get("rebalance_forced_by_trailing_stop", False)),
            "trailing_stop_liquidation_count": int(info.get("trailing_stop_liquidation_count", 0)),
            "trailing_stop_liquidation_assets": info.get("trailing_stop_liquidation_assets", ""),
            "position_reset_triggered": bool(info.get("position_reset_triggered", False)),
            "position_reset_reason": info.get("position_reset_reason", ""),
            "bars_since_last_material_trade": int(info.get("bars_since_last_material_trade", 0)),
            "material_trade_executed": bool(info.get("material_trade_executed", False)),
            "abs_drawdown": info.get("abs_drawdown", 0.0),
            "rolling_drawdown": info.get("rolling_drawdown", 0.0),
            "tail_loss_component": info.get("tail_loss_component", 0.0),
            "risk_governor_active": bool(risk_governor_diag.get("active", False)),
            "risk_governor_reason": risk_governor_diag.get("reason", ""),
            "risk_governor_cash_floor": risk_governor_diag.get("cash_floor", 0.0),
            "risk_governor_max_risk_on": risk_governor_diag.get("max_risk_on", 0.0),
            "rl_btc_weight": rl_weights[0],
            "rl_eth_weight": rl_weights[1],
            "rl_cash_weight": rl_weights[2],
            "ensemble_btc_weight": rl_weights[0],
            "ensemble_eth_weight": rl_weights[1],
            "ensemble_cash_weight": rl_weights[2],
            "target_btc_weight": target_weights[0],
            "target_eth_weight": target_weights[1],
            "target_cash_weight": target_weights[2],
            "kronos_available": bool(kronos_signals),
            "kronos_signal_count": len(kronos_signals or {}),
            "kronos_sources": ",".join(sorted({sig.source for sig in (kronos_signals or {}).values()})),
            "kronos_btc_directional_score": (
                float((kronos_signals or {}).get("BTCUSDT").directional_score)
                if (kronos_signals or {}).get("BTCUSDT") is not None
                else np.nan
            ),
            "kronos_eth_directional_score": (
                float((kronos_signals or {}).get("ETHUSDT").directional_score)
                if (kronos_signals or {}).get("ETHUSDT") is not None
                else np.nan
            ),
            "kronos_btc_confidence": (
                float((kronos_signals or {}).get("BTCUSDT").confidence)
                if (kronos_signals or {}).get("BTCUSDT") is not None
                else np.nan
            ),
            "kronos_eth_confidence": (
                float((kronos_signals or {}).get("ETHUSDT").confidence)
                if (kronos_signals or {}).get("ETHUSDT") is not None
                else np.nan
            ),
            "kronos_btc_tilt": float((fusion_diag.kronos_tilts or {}).get("BTCUSDT", 0.0)) if fusion_diag else 0.0,
            "kronos_eth_tilt": float((fusion_diag.kronos_tilts or {}).get("ETHUSDT", 0.0)) if fusion_diag else 0.0,
            "tradingagents_available": ta_signal is not None,
            "tradingagents_source": ta_signal.source if ta_signal is not None else "",
            "llm_risk_available": llm_risk_signal is not None,
            "llm_risk_flag": llm_risk_signal.risk_flag if llm_risk_signal is not None else "",
            "llm_risk_confidence": (
                float(llm_risk_signal.confidence) if llm_risk_signal is not None else np.nan
            ),
            "llm_risk_source": llm_risk_signal.source if llm_risk_signal is not None else "",
            "llm_risk_cached": bool(llm_risk_signal.cached) if llm_risk_signal is not None else False,
            "llm_risk_call_budget_exhausted": (
                bool(llm_risk_signal.call_budget_exhausted) if llm_risk_signal is not None else False
            ),
            "llm_risk_gate_mode": LLM_RISK_GATE_MODE,
            "llm_risk_applied": bool(fusion_diag.llm_risk_applied) if fusion_diag else False,
            "post_policy_overlay_enabled": post_policy_overlay != "none",
            "post_policy_overlay_name": str(overlay_diag.get("name", "none")),
            "post_policy_volatility_scale": float(overlay_diag.get("volatility_scale", 1.0)),
            "post_policy_turnover_before": float(overlay_diag.get("turnover_before", 0.0)),
            "post_policy_turnover_after": float(overlay_diag.get("turnover_after", 0.0)),
            "post_policy_trend_gate_applied": bool(overlay_diag.get("trend_gate_applied", False)),
            "post_policy_drawdown_gate_applied": bool(overlay_diag.get("drawdown_gate_applied", False)),
            "fusion_has_kronos": bool(fusion_diag.notes.get("has_kronos")) if fusion_diag else False,
            "fusion_has_trading_signal": bool(fusion_diag.notes.get("has_trading_signal")) if fusion_diag else False,
            "fusion_has_llm_risk": bool(fusion_diag.notes.get("has_llm_risk")) if fusion_diag else False,
            "fusion_turnover_pre_clip": float(fusion_diag.turnover_pre_clip) if fusion_diag else 0.0,
            "fusion_turnover_post_clip": float(fusion_diag.turnover_post_clip) if fusion_diag else 0.0,
            "fusion_turnover_clip_ratio": float(fusion_diag.turnover_clip_ratio) if fusion_diag else 1.0,
            "fusion_constraint_clipped": bool(fusion_diag.constraint_clipped) if fusion_diag else False,
            "fusion_mechanism_label": str(fusion_diag.notes.get("mechanism_label", "")) if fusion_diag else "",
            "fusion_pre_constraint_btc_weight": (
                float(fusion_diag.pre_constraint[0]) if fusion_diag else np.nan
            ),
            "fusion_pre_constraint_eth_weight": (
                float(fusion_diag.pre_constraint[1]) if fusion_diag else np.nan
            ),
            "fusion_pre_constraint_cash_weight": (
                float(fusion_diag.pre_constraint[2]) if fusion_diag else np.nan
            ),
            "fusion_post_constraint_btc_weight": (
                float(fusion_diag.post_risk[0]) if fusion_diag else np.nan
            ),
            "fusion_post_constraint_eth_weight": (
                float(fusion_diag.post_risk[1]) if fusion_diag else np.nan
            ),
            "fusion_post_constraint_cash_weight": (
                float(fusion_diag.post_risk[2]) if fusion_diag else np.nan
            ),
            "ensemble_model_weight_ppo": float(agent._sharpes.get("PPO", 1.0)),
            "ensemble_model_weight_sac": float(agent._sharpes.get("SAC", 1.0)),
            "ensemble_regime_label": str(getattr(agent, "_model_mix_diagnostics", {}).get("regime_label", "")),
            "ensemble_stress_strength": float(getattr(agent, "_model_mix_diagnostics", {}).get("stress_strength", 0.0)),
        }
        for algo, weights in proposals.items():
            prefix = algo.lower()
            record[f"{prefix}_btc_weight"] = weights[0]
            record[f"{prefix}_eth_weight"] = weights[1]
            record[f"{prefix}_cash_weight"] = weights[2]
        records.append(record)

    env.close()
    df = pd.DataFrame(records).set_index("timestamp")
    trades_count = int((df["transaction_cost"] > 0).sum())
    meta = {
        "pipeline": pipeline,
        "realism_profile": realism_profile,
        "fee": profile["fee"],
        "slippage": profile["slippage"],
        "latency_steps": latency_steps,
        "model_dir": str(model_dir),
        "post_policy_overlay": post_policy_overlay,
    }
    return df, trades_count, meta


def run_matrix(
    *,
    test_data: dict[str, pd.DataFrame],
    raw_ohlcv_data: dict[str, pd.DataFrame] | None = None,
    method: str,
    realism_profile: str,
    output_dir: Path,
    model_dir: Path = MODELS_DIR,
    post_policy_overlay: str = "none",
    overlay_target_volatility: float = 0.04,
    overlay_persistence_turnover_cap: float = 0.15,
    overlay_trend_gate_threshold: float = 0.0,
    overlay_trend_gate_multiplier: float = 0.75,
    overlay_drawdown_gate_threshold: float = -0.10,
    overlay_drawdown_gate_multiplier: float = 0.70,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    benchmark = build_benchmark_nav(test_data)
    matrix_rows: list[dict[str, Any]] = []
    realism_rows: list[dict[str, Any]] = []

    baseline_metrics = None
    livelike_metrics = None

    for pipeline in PIPELINES.keys():
        episode_df, trades_count, meta = run_backtest(
            test_data=test_data,
            raw_ohlcv_data=raw_ohlcv_data,
            method=method,
            pipeline=pipeline,
            realism_profile=realism_profile,
            model_dir=model_dir,
            post_policy_overlay=post_policy_overlay,
            overlay_target_volatility=overlay_target_volatility,
            overlay_persistence_turnover_cap=overlay_persistence_turnover_cap,
            overlay_trend_gate_threshold=overlay_trend_gate_threshold,
            overlay_trend_gate_multiplier=overlay_trend_gate_multiplier,
            overlay_drawdown_gate_threshold=overlay_drawdown_gate_threshold,
            overlay_drawdown_gate_multiplier=overlay_drawdown_gate_multiplier,
        )

        metrics = compute_metrics(
            episode_df["portfolio_value"],
            initial_capital=INITIAL_CAPITAL,
            benchmark_nav=benchmark,
            trades_count=trades_count,
        )
        _print_metrics(f"{pipeline}/{realism_profile}", metrics)
        row = dict(meta)
        row.update(metrics)
        row.update(_episode_diagnostics(episode_df))
        matrix_rows.append(row)

        out_episode = output_dir / f"backtest_episode_{pipeline}_{realism_profile}_{method}.parquet"
        episode_df.to_parquet(out_episode)
        write_trade_decision_log(
            episode_df,
            output_dir / f"trade_decisions_{pipeline}_{realism_profile}_{method}.csv",
        )
        write_trade_diagnostics_tables(
            episode_df,
            output_dir=output_dir,
            stem=f"{pipeline}_{realism_profile}_{method}",
        )

        if pipeline == "rl_full":
            metrics_path = output_dir / "backtest_metrics.csv"
            pd.Series(metrics).to_csv(metrics_path, header=["value"])
            plot_equity_curve(
                episode_df["portfolio_value"],
                benchmark_nav=benchmark,
                save_path=output_dir / "equity_curve.png",
            )
            plot_kpi_radar(metrics, save_path=output_dir / "kpi_target_radar.png")

        if pipeline == "rl_only":
            if realism_profile == "baseline":
                baseline_metrics = metrics
            if realism_profile == "live_like":
                livelike_metrics = metrics

    matrix_df = pd.DataFrame(matrix_rows)
    matrix_df.to_csv(output_dir / "backtest_matrix_metrics.csv", index=False)
    diagnostics_cols = [
        "pipeline",
        "realism_profile",
        "turnover_sum",
        "turnover_mean",
        "transaction_cost_sum",
        "transaction_cost_mean",
        "raw_action_delta_mean",
        "action_delta_component_mean",
        "effective_slippage_mean",
        "turnover_cap_applied_rate",
        "cash_weight_mean",
        "cash_weight_p95",
        "risk_on_mean",
        "risk_governor_active_rate",
        "cost_multiplier",
        "cost_drag_pct",
        "kronos_action_change_rate_gt_0p02",
        "kronos_action_change_rate_gt_0p02_when_available",
        "kronos_reversal_rate_within_3_steps",
    ]
    matrix_df[[c for c in diagnostics_cols if c in matrix_df.columns]].to_csv(
        output_dir / "backtest_rl_diagnostics.csv",
        index=False,
    )

    if baseline_metrics is not None and livelike_metrics is not None:
        for key in ["total_return_pct", "sharpe_ratio", "max_drawdown_pct", "total_trades_count"]:
            realism_rows.append(
                {
                    "metric": key,
                    "baseline": baseline_metrics.get(key),
                    "live_like": livelike_metrics.get(key),
                    "delta_live_like_minus_baseline": (livelike_metrics.get(key, 0.0) - baseline_metrics.get(key, 0.0)),
                }
            )

    realism_df = pd.DataFrame(realism_rows)
    if not realism_df.empty:
        realism_df.to_csv(output_dir / "backtest_realism_report.csv", index=False)

    return matrix_df, realism_df


def run_ensemble_method_comparison(
    *,
    test_data: dict[str, pd.DataFrame],
    raw_ohlcv_data: dict[str, pd.DataFrame] | None = None,
    pipeline: str,
    realism_profile: str,
    methods: list[str],
    output_dir: Path,
    model_dir: Path = MODELS_DIR,
    post_policy_overlay: str = "none",
    overlay_target_volatility: float = 0.04,
    overlay_persistence_turnover_cap: float = 0.15,
    overlay_trend_gate_threshold: float = 0.0,
    overlay_trend_gate_multiplier: float = 0.75,
    overlay_drawdown_gate_threshold: float = -0.10,
    overlay_drawdown_gate_multiplier: float = 0.70,
) -> pd.DataFrame:
    benchmark = build_benchmark_nav(test_data)
    rows: list[dict[str, Any]] = []
    equity_curves: dict[str, pd.Series] = {}
    for method in methods:
        episode_df, trades_count, meta = run_backtest(
            test_data=test_data,
            raw_ohlcv_data=raw_ohlcv_data,
            method=method,
            pipeline=pipeline,
            realism_profile=realism_profile,
            model_dir=model_dir,
            post_policy_overlay=post_policy_overlay,
            overlay_target_volatility=overlay_target_volatility,
            overlay_persistence_turnover_cap=overlay_persistence_turnover_cap,
            overlay_trend_gate_threshold=overlay_trend_gate_threshold,
            overlay_trend_gate_multiplier=overlay_trend_gate_multiplier,
            overlay_drawdown_gate_threshold=overlay_drawdown_gate_threshold,
            overlay_drawdown_gate_multiplier=overlay_drawdown_gate_multiplier,
        )
        equity_curves[method] = episode_df["portfolio_value"].copy()
        episode_df.to_parquet(output_dir / f"backtest_episode_{pipeline}_{realism_profile}_{method}.parquet")
        write_trade_decision_log(
            episode_df,
            output_dir / f"trade_decisions_{pipeline}_{realism_profile}_{method}.csv",
        )
        write_trade_diagnostics_tables(
            episode_df,
            output_dir=output_dir,
            stem=f"{pipeline}_{realism_profile}_{method}",
        )
        metrics = compute_metrics(
            episode_df["portfolio_value"],
            initial_capital=INITIAL_CAPITAL,
            benchmark_nav=benchmark,
            trades_count=trades_count,
        )
        row = {"method": method, **meta}
        row.update(metrics)
        row.update(_episode_diagnostics(episode_df))
        rows.append(row)
        _print_metrics(f"{pipeline}/{realism_profile}/{method}", metrics)
    out = pd.DataFrame(rows)
    out.to_csv(output_dir / "backtest_ensemble_method_comparison.csv", index=False)
    plot_ensemble_method_comparison(
        out,
        equity_curves,
        save_path=output_dir / "backtest_ensemble_method_comparison.png",
    )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Run backtest with Kronos/TradingAgents fusion and realism controls.")
    parser.add_argument(
        "--method",
        default=ENSEMBLE_METHOD,
        choices=ENSEMBLE_METHODS,
    )
    parser.add_argument("--pipeline", default="rl_full", choices=list(PIPELINES.keys()))
    parser.add_argument("--realism-profile", default="live_like", choices=list(REALISM.keys()))
    parser.add_argument("--run-matrix", action="store_true", help="Run all ablation pipelines for the selected realism profile.")
    parser.add_argument("--diagnose-realism", action="store_true", help="Run RL-only baseline and live_like profiles and save realism report.")
    parser.add_argument(
        "--compare-ensemble-methods",
        action="store_true",
        help="Compare ensemble aggregation methods for the selected pipeline.",
    )
    parser.add_argument(
        "--comparison-methods",
        default=DEFAULT_COMPARISON_METHODS,
        type=parse_method_list,
        help="Comma-separated methods for --compare-ensemble-methods.",
    )
    parser.add_argument("--model-dir", type=Path, default=LIVE_BASELINE_MODEL_DIR, help="Model directory to load PPO/SAC checkpoints from.")
    parser.add_argument(
        "--post-policy-overlay",
        type=parse_overlay_name,
        default="none",
        help="Optional deterministic overlay applied after RL/fusion target weights.",
    )
    parser.add_argument("--overlay-target-volatility", type=float, default=0.04)
    parser.add_argument("--overlay-persistence-turnover-cap", type=float, default=0.15)
    parser.add_argument("--overlay-trend-gate-threshold", type=float, default=0.0)
    parser.add_argument("--overlay-trend-gate-multiplier", type=float, default=0.75)
    parser.add_argument("--overlay-drawdown-gate-threshold", type=float, default=-0.10)
    parser.add_argument("--overlay-drawdown-gate-multiplier", type=float, default=0.70)
    parser.add_argument("--rebalance-threshold-normal", type=float, default=REBALANCE_THRESHOLD_NORMAL)
    parser.add_argument("--rebalance-threshold-stress", type=float, default=REBALANCE_THRESHOLD_STRESS)
    parser.add_argument("--rebalance-threshold-crisis", type=float, default=REBALANCE_THRESHOLD_CRISIS)
    parser.add_argument("--min-hold-bars", type=int, default=MIN_HOLD_BARS)
    parser.add_argument("--material-trade-threshold", type=float, default=MATERIAL_TRADE_THRESHOLD)
    parser.add_argument("--reversal-hysteresis-mult", type=float, default=REVERSAL_HYSTERESIS_MULT)
    parser.add_argument("--position-reset-weight-threshold", type=float, default=POSITION_RESET_WEIGHT_THRESHOLD)
    parser.add_argument("--position-reset-persist-bars", type=int, default=POSITION_RESET_PERSIST_BARS)
    parser.add_argument("--autosave-profit-threshold", type=float, default=70.0)
    args = parser.parse_args()
    args.model_dir = resolve_backtest_model_dir(args.model_dir)
    apply_execution_control_overrides(args)

    test_data = load_test_data()
    raw_ohlcv_data = load_kronos_raw_data()
    benchmark = build_benchmark_nav(test_data)
    session_dir = create_backtest_session_dir(RESULTS_DIR)
    write_session_metadata(
        session_dir,
        {
            "created_at": datetime.now().isoformat(),
            "pipeline": args.pipeline,
            "method": args.method,
            "comparison_methods": args.comparison_methods,
            "realism_profile": args.realism_profile,
            "run_matrix": args.run_matrix,
            "diagnose_realism": args.diagnose_realism,
            "compare_ensemble_methods": args.compare_ensemble_methods,
            "model_dir": args.model_dir,
            "post_policy_overlay": args.post_policy_overlay,
            "rebalance_threshold_normal": args.rebalance_threshold_normal,
            "rebalance_threshold_stress": args.rebalance_threshold_stress,
            "rebalance_threshold_crisis": args.rebalance_threshold_crisis,
            "min_hold_bars": args.min_hold_bars,
            "material_trade_threshold": args.material_trade_threshold,
            "reversal_hysteresis_mult": args.reversal_hysteresis_mult,
            "position_reset_weight_threshold": args.position_reset_weight_threshold,
            "position_reset_persist_bars": args.position_reset_persist_bars,
        },
    )
    logger.info(f"Backtest session output directory -> {session_dir}")

    if args.run_matrix:
        matrix_df, _ = run_matrix(
            test_data=test_data,
            raw_ohlcv_data=raw_ohlcv_data,
            method=args.method,
            realism_profile=args.realism_profile,
            output_dir=session_dir,
            model_dir=args.model_dir,
            post_policy_overlay=args.post_policy_overlay,
            overlay_target_volatility=args.overlay_target_volatility,
            overlay_persistence_turnover_cap=args.overlay_persistence_turnover_cap,
            overlay_trend_gate_threshold=args.overlay_trend_gate_threshold,
            overlay_trend_gate_multiplier=args.overlay_trend_gate_multiplier,
            overlay_drawdown_gate_threshold=args.overlay_drawdown_gate_threshold,
            overlay_drawdown_gate_multiplier=args.overlay_drawdown_gate_multiplier,
        )
        if not matrix_df.empty:
            best_row = matrix_df.sort_values("total_return_pct", ascending=False).iloc[0].to_dict()
            maybe_save_best_model_snapshot(
                metrics=best_row,
                source_model_dir=args.model_dir,
                best_root_dir=MODELS_DIR,
                run_label=f"{best_row.get('pipeline', 'matrix')}_{best_row.get('realism_profile', args.realism_profile)}_{args.method}",
                session_dir=session_dir,
                profit_threshold_pct=args.autosave_profit_threshold,
            )
        logger.info(f"Matrix saved with {len(matrix_df)} rows -> {session_dir / 'backtest_matrix_metrics.csv'}")
        return

    if args.compare_ensemble_methods:
        comparison_df = run_ensemble_method_comparison(
            test_data=test_data,
            raw_ohlcv_data=raw_ohlcv_data,
            pipeline=args.pipeline,
            realism_profile=args.realism_profile,
            methods=args.comparison_methods,
            output_dir=session_dir,
            model_dir=args.model_dir,
            post_policy_overlay=args.post_policy_overlay,
            overlay_target_volatility=args.overlay_target_volatility,
            overlay_persistence_turnover_cap=args.overlay_persistence_turnover_cap,
            overlay_trend_gate_threshold=args.overlay_trend_gate_threshold,
            overlay_trend_gate_multiplier=args.overlay_trend_gate_multiplier,
            overlay_drawdown_gate_threshold=args.overlay_drawdown_gate_threshold,
            overlay_drawdown_gate_multiplier=args.overlay_drawdown_gate_multiplier,
        )
        if not comparison_df.empty:
            best_row = comparison_df.sort_values("total_return_pct", ascending=False).iloc[0].to_dict()
            maybe_save_best_model_snapshot(
                metrics=best_row,
                source_model_dir=args.model_dir,
                best_root_dir=MODELS_DIR,
                run_label=f"{args.pipeline}_{args.realism_profile}_{best_row.get('method', args.method)}",
                session_dir=session_dir,
                profit_threshold_pct=args.autosave_profit_threshold,
            )
        logger.info(
            f"Ensemble comparison saved with {len(comparison_df)} rows -> "
            f"{session_dir / 'backtest_ensemble_method_comparison.csv'}"
        )
        return

    if args.diagnose_realism:
        rows = []
        for profile in ["baseline", "live_like"]:
            episode_df, trades_count, meta = run_backtest(
                test_data=test_data,
                raw_ohlcv_data=raw_ohlcv_data,
                method=args.method,
                pipeline="rl_only",
                realism_profile=profile,
                model_dir=args.model_dir,
                post_policy_overlay=args.post_policy_overlay,
                overlay_target_volatility=args.overlay_target_volatility,
                overlay_persistence_turnover_cap=args.overlay_persistence_turnover_cap,
                overlay_trend_gate_threshold=args.overlay_trend_gate_threshold,
                overlay_trend_gate_multiplier=args.overlay_trend_gate_multiplier,
                overlay_drawdown_gate_threshold=args.overlay_drawdown_gate_threshold,
                overlay_drawdown_gate_multiplier=args.overlay_drawdown_gate_multiplier,
            )
            metrics = compute_metrics(
                episode_df["portfolio_value"],
                initial_capital=INITIAL_CAPITAL,
                benchmark_nav=benchmark,
                trades_count=trades_count,
            )
            row = dict(meta)
            row.update(metrics)
            rows.append(row)
            episode_df.to_parquet(session_dir / f"backtest_episode_rl_only_{profile}_{args.method}.parquet")
            write_trade_decision_log(
                episode_df,
                session_dir / f"trade_decisions_rl_only_{profile}_{args.method}.csv",
            )
            write_trade_diagnostics_tables(
                episode_df,
                output_dir=session_dir,
                stem=f"rl_only_{profile}_{args.method}",
            )
            _print_metrics(f"rl_only/{profile}", metrics)

        realism_df = pd.DataFrame(rows)
        realism_df.to_csv(session_dir / "backtest_realism_report.csv", index=False)
        if not realism_df.empty:
            best_row = realism_df.sort_values("total_return_pct", ascending=False).iloc[0].to_dict()
            maybe_save_best_model_snapshot(
                metrics=best_row,
                source_model_dir=args.model_dir,
                best_root_dir=MODELS_DIR,
                run_label=f"rl_only_{best_row.get('realism_profile', args.realism_profile)}_{args.method}",
                session_dir=session_dir,
                profit_threshold_pct=args.autosave_profit_threshold,
            )
        logger.info(f"Realism report saved -> {session_dir / 'backtest_realism_report.csv'}")
        return

    episode_df, trades_count, meta = run_backtest(
        test_data=test_data,
        raw_ohlcv_data=raw_ohlcv_data,
        method=args.method,
        pipeline=args.pipeline,
        realism_profile=args.realism_profile,
        model_dir=args.model_dir,
        post_policy_overlay=args.post_policy_overlay,
        overlay_target_volatility=args.overlay_target_volatility,
        overlay_persistence_turnover_cap=args.overlay_persistence_turnover_cap,
        overlay_trend_gate_threshold=args.overlay_trend_gate_threshold,
        overlay_trend_gate_multiplier=args.overlay_trend_gate_multiplier,
        overlay_drawdown_gate_threshold=args.overlay_drawdown_gate_threshold,
        overlay_drawdown_gate_multiplier=args.overlay_drawdown_gate_multiplier,
    )
    metrics = compute_metrics(
        episode_df["portfolio_value"],
        initial_capital=INITIAL_CAPITAL,
        benchmark_nav=benchmark,
        trades_count=trades_count,
    )
    _print_metrics(f"{args.pipeline}/{args.realism_profile}", metrics)

    episode_path = session_dir / f"backtest_episode_{args.pipeline}_{args.realism_profile}_{args.method}.parquet"
    episode_df.to_parquet(episode_path)
    write_trade_decision_log(
        episode_df,
        session_dir / f"trade_decisions_{args.pipeline}_{args.realism_profile}_{args.method}.csv",
    )
    write_trade_diagnostics_tables(
        episode_df,
        output_dir=session_dir,
        stem=f"{args.pipeline}_{args.realism_profile}_{args.method}",
    )
    pd.Series(metrics).to_csv(session_dir / "backtest_metrics.csv", header=["value"])
    plot_equity_curve(episode_df["portfolio_value"], benchmark_nav=benchmark, save_path=session_dir / "equity_curve.png")
    plot_kpi_radar(metrics, save_path=session_dir / "kpi_target_radar.png")
    maybe_save_best_model_snapshot(
        metrics=metrics,
        source_model_dir=args.model_dir,
        best_root_dir=MODELS_DIR,
        run_label=f"{args.pipeline}_{args.realism_profile}_{args.method}",
        session_dir=session_dir,
        profit_threshold_pct=args.autosave_profit_threshold,
    )

    logger.info(f"Episode saved -> {episode_path}")
    logger.info(f"Meta: {meta}")


if __name__ == "__main__":
    main()
