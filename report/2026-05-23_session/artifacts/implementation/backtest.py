"""
Backtesting runner with Kronos/TradingAgents ablation matrix and realism profiles.
"""

from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from loguru import logger

from adapters import KronosAdapter, TradingAgentsAdapter
from agents.ensemble_agent import EnsembleAgent, load_ensemble
from agents.meta_fusion_agent import MetaFusionAgent
from config import (
    BACKTEST_BASELINE_FEE,
    BACKTEST_BASELINE_LATENCY_STEPS,
    BACKTEST_BASELINE_SLIPPAGE,
    BACKTEST_LIVE_LIKE_FEE,
    BACKTEST_LIVE_LIKE_LATENCY_STEPS,
    BACKTEST_LIVE_LIKE_SLIPPAGE,
    ENABLE_KRONOS,
    ENABLE_TRADINGAGENTS,
    ENSEMBLE_METHOD,
    INITIAL_CAPITAL,
    KRONOS_FORECAST_HORIZON,
    KRONOS_MODEL_ID,
    KRONOS_TOKENIZER_ID,
    MAX_ASSET_WEIGHT,
    MAX_PORTFOLIO_TURNOVER,
    MAX_TILT_PER_SIGNAL,
    MIN_CASH_FLOOR,
    MODELS_DIR,
    PROCESSED_DATA_DIR,
    RESULTS_DIR,
    SYMBOLS,
    TRADINGAGENTS_CALL_TIMEOUT_SECS,
    TRADINGAGENTS_BACKTEST_CADENCE,
    TRADINGAGENTS_CHECKPOINT_ENABLED,
    TRADINGAGENTS_DECISION_LOG_PATH,
    TRADINGAGENTS_MAX_RETRIES,
    TRADINGAGENTS_PROVIDER_FALLBACKS,
    TRADINGAGENTS_RETRY_BACKOFF_SECS,
    LOOKBACK_WINDOW,
)
from environment.trading_env import BinanceSpotEnv, _softmax_weights
from metrics.performance import compute_metrics, plot_equity_curve, plot_kpi_radar

load_dotenv()

PIPELINES = {
    "rl_only": {"kronos": False, "tradingagents": False},
    "rl_kronos": {"kronos": True, "tradingagents": False},
    "rl_tradingagents": {"kronos": False, "tradingagents": True},
    "rl_full": {"kronos": True, "tradingagents": True},
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


def load_test_data() -> dict[str, pd.DataFrame]:
    return {sym: pd.read_parquet(PROCESSED_DATA_DIR / f"{sym}_test.parquet") for sym in SYMBOLS}


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
        "cash_weight_mean": float(df["cash_weight"].mean()) if "cash_weight" in df else 0.0,
        "cash_weight_p95": float(df["cash_weight"].quantile(0.95)) if "cash_weight" in df else 0.0,
        "risk_on_mean": float((df["btc_weight"] + df["eth_weight"]).mean())
        if {"btc_weight", "eth_weight"}.issubset(df.columns)
        else 0.0,
    }
    if "transaction_cost" in df:
        cost_multiplier = float((1.0 - df["transaction_cost"]).prod())
        diagnostics["cost_multiplier"] = cost_multiplier
        diagnostics["cost_drag_pct"] = (cost_multiplier - 1.0) * 100.0
    return diagnostics


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
                mean_ret = float(arr.mean())
                std_ret = float(arr.std()) + 1e-9
                sharpe = (mean_ret / std_ret) * np.sqrt(24 * 365)
                current[algo] = max(sharpe, 0.1)
            else:
                current[algo] = 1.0
        agent._sharpes = current
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


def run_backtest(
    *,
    test_data: dict[str, pd.DataFrame],
    method: str,
    pipeline: str,
    realism_profile: str,
) -> tuple[pd.DataFrame, int, dict[str, Any]]:
    profile = REALISM[realism_profile]
    env = BinanceSpotEnv(
        test_data,
        initial_capital=INITIAL_CAPITAL,
        trading_fee=profile["fee"],
        slippage=profile["slippage"],
        mode="eval",
    )

    ensemble = load_ensemble(MODELS_DIR)
    agent = EnsembleAgent(ensemble, method=method)
    pipe_flags = PIPELINES[pipeline]

    kronos = None
    ta_adapter = None
    fusion = None
    if pipe_flags["kronos"] or pipe_flags["tradingagents"]:
        fusion = MetaFusionAgent(
            symbols=SYMBOLS,
            max_tilt_per_signal=MAX_TILT_PER_SIGNAL,
            max_portfolio_turnover=MAX_PORTFOLIO_TURNOVER,
            max_asset_weight=MAX_ASSET_WEIGHT,
            min_cash_floor=MIN_CASH_FLOOR,
        )
    if pipe_flags["kronos"]:
        kronos = KronosAdapter(
            enabled=True,
            model_id=KRONOS_MODEL_ID,
            tokenizer_id=KRONOS_TOKENIZER_ID,
            forecast_horizon=KRONOS_FORECAST_HORIZON,
        )
    if pipe_flags["tradingagents"]:
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

        if fusion is not None:
            kronos_signals = kronos.predict_batch(state_window, timestamp=pd.Timestamp(timestamp)) if kronos else None
            ta_signal = (
                ta_adapter.evaluate(
                    ticker=SYMBOLS[0],
                    asof=pd.Timestamp(timestamp),
                    market_snapshot=state_window[SYMBOLS[0]],
                )
                if ta_adapter
                else None
            )
            target_weights, fusion_diag = fusion.fuse(
                rl_weights=rl_weights,
                current_weights=env._weights.copy(),
                kronos_signals=kronos_signals,
                trading_signal=ta_signal,
            )
        else:
            target_weights = rl_weights
            kronos_signals = None
            ta_signal = None
            fusion_diag = None

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

        record = {
            "timestamp": info["timestamp"],
            "portfolio_value": info["portfolio_value"],
            "btc_weight": info["weights"][0],
            "eth_weight": info["weights"][1],
            "cash_weight": info["weights"][2],
            "transaction_cost": info["transaction_cost"],
            "turnover": turnover,
            "step_reward": reward,
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
            "tradingagents_available": ta_signal is not None,
            "tradingagents_source": ta_signal.source if ta_signal is not None else "",
            "fusion_has_kronos": bool(fusion_diag.notes.get("has_kronos")) if fusion_diag else False,
            "fusion_has_trading_signal": bool(fusion_diag.notes.get("has_trading_signal")) if fusion_diag else False,
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
    }
    return df, trades_count, meta


def run_matrix(
    *,
    test_data: dict[str, pd.DataFrame],
    method: str,
    realism_profile: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    benchmark = build_benchmark_nav(test_data)
    matrix_rows: list[dict[str, Any]] = []
    realism_rows: list[dict[str, Any]] = []

    baseline_metrics = None
    livelike_metrics = None

    for pipeline in PIPELINES.keys():
        episode_df, trades_count, meta = run_backtest(
            test_data=test_data,
            method=method,
            pipeline=pipeline,
            realism_profile=realism_profile,
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

        out_episode = RESULTS_DIR / f"backtest_episode_{pipeline}_{realism_profile}.parquet"
        episode_df.to_parquet(out_episode)

        if pipeline == "rl_full":
            metrics_path = RESULTS_DIR / "backtest_metrics.csv"
            pd.Series(metrics).to_csv(metrics_path, header=["value"])
            plot_equity_curve(
                episode_df["portfolio_value"],
                benchmark_nav=benchmark,
                save_path=RESULTS_DIR / "equity_curve.png",
            )
            plot_kpi_radar(metrics, save_path=RESULTS_DIR / "kpi_target_radar.png")

        if pipeline == "rl_only":
            if realism_profile == "baseline":
                baseline_metrics = metrics
            if realism_profile == "live_like":
                livelike_metrics = metrics

    matrix_df = pd.DataFrame(matrix_rows)
    matrix_df.to_csv(RESULTS_DIR / "backtest_matrix_metrics.csv", index=False)
    diagnostics_cols = [
        "pipeline",
        "realism_profile",
        "turnover_sum",
        "turnover_mean",
        "transaction_cost_sum",
        "transaction_cost_mean",
        "cash_weight_mean",
        "cash_weight_p95",
        "risk_on_mean",
        "cost_multiplier",
        "cost_drag_pct",
    ]
    matrix_df[[c for c in diagnostics_cols if c in matrix_df.columns]].to_csv(
        RESULTS_DIR / "backtest_rl_diagnostics.csv",
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
        realism_df.to_csv(RESULTS_DIR / "backtest_realism_report.csv", index=False)

    return matrix_df, realism_df


def run_ensemble_method_comparison(
    *,
    test_data: dict[str, pd.DataFrame],
    realism_profile: str,
) -> pd.DataFrame:
    benchmark = build_benchmark_nav(test_data)
    rows: list[dict[str, Any]] = []
    for method in ["mean", "voting", "weighted", "dynamic_weighted", "imca"]:
        episode_df, trades_count, meta = run_backtest(
            test_data=test_data,
            method=method,
            pipeline="rl_only",
            realism_profile=realism_profile,
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
        _print_metrics(f"rl_only/{realism_profile}/{method}", metrics)
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS_DIR / "backtest_ensemble_method_comparison.csv", index=False)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Run backtest with Kronos/TradingAgents fusion and realism controls.")
    parser.add_argument(
        "--method",
        default=ENSEMBLE_METHOD,
        choices=["mean", "voting", "weighted", "dynamic_weighted", "imca"],
    )
    parser.add_argument("--pipeline", default="rl_full", choices=list(PIPELINES.keys()))
    parser.add_argument("--realism-profile", default="live_like", choices=list(REALISM.keys()))
    parser.add_argument("--run-matrix", action="store_true", help="Run all ablation pipelines for the selected realism profile.")
    parser.add_argument("--diagnose-realism", action="store_true", help="Run RL-only baseline and live_like profiles and save realism report.")
    parser.add_argument(
        "--compare-ensemble-methods",
        action="store_true",
        help="Run RL-only comparison across ensemble aggregation methods.",
    )
    args = parser.parse_args()

    test_data = load_test_data()
    benchmark = build_benchmark_nav(test_data)

    if args.run_matrix:
        matrix_df, _ = run_matrix(test_data=test_data, method=args.method, realism_profile=args.realism_profile)
        logger.info(f"Matrix saved with {len(matrix_df)} rows -> {RESULTS_DIR / 'backtest_matrix_metrics.csv'}")
        return

    if args.compare_ensemble_methods:
        comparison_df = run_ensemble_method_comparison(test_data=test_data, realism_profile=args.realism_profile)
        logger.info(
            f"Ensemble comparison saved with {len(comparison_df)} rows -> "
            f"{RESULTS_DIR / 'backtest_ensemble_method_comparison.csv'}"
        )
        return

    if args.diagnose_realism:
        rows = []
        for profile in ["baseline", "live_like"]:
            episode_df, trades_count, meta = run_backtest(
                test_data=test_data,
                method=args.method,
                pipeline="rl_only",
                realism_profile=profile,
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
            episode_df.to_parquet(RESULTS_DIR / f"backtest_episode_rl_only_{profile}.parquet")
            _print_metrics(f"rl_only/{profile}", metrics)

        realism_df = pd.DataFrame(rows)
        realism_df.to_csv(RESULTS_DIR / "backtest_realism_report.csv", index=False)
        logger.info(f"Realism report saved -> {RESULTS_DIR / 'backtest_realism_report.csv'}")
        return

    episode_df, trades_count, meta = run_backtest(
        test_data=test_data,
        method=args.method,
        pipeline=args.pipeline,
        realism_profile=args.realism_profile,
    )
    metrics = compute_metrics(
        episode_df["portfolio_value"],
        initial_capital=INITIAL_CAPITAL,
        benchmark_nav=benchmark,
        trades_count=trades_count,
    )
    _print_metrics(f"{args.pipeline}/{args.realism_profile}", metrics)

    episode_path = RESULTS_DIR / "backtest_episode.parquet"
    episode_df.to_parquet(episode_path)
    pd.Series(metrics).to_csv(RESULTS_DIR / "backtest_metrics.csv", header=["value"])
    plot_equity_curve(episode_df["portfolio_value"], benchmark_nav=benchmark, save_path=RESULTS_DIR / "equity_curve.png")
    plot_kpi_radar(metrics, save_path=RESULTS_DIR / "kpi_target_radar.png")

    logger.info(f"Episode saved -> {episode_path}")
    logger.info(f"Meta: {meta}")


if __name__ == "__main__":
    main()
