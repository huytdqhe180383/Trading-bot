"""
Backtesting Layer – backtest.py
================================
Runs the Ensemble agent over the out-of-sample test split and
generates a comprehensive performance report.

Usage:
    python backtest.py [--method mean|voting|weighted]
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (
    SYMBOLS, PROCESSED_DATA_DIR, MODELS_DIR, RESULTS_DIR,
    INITIAL_CAPITAL, ENSEMBLE_METHOD,
)
from agents.ensemble_agent import load_ensemble, EnsembleAgent
from environment.trading_env import BinanceSpotEnv, _softmax_weights
from metrics.performance import (
    compute_metrics, plot_equity_curve,
    plot_kpi_radar
)

def print_metrics_report(metrics: dict):
    from loguru import logger
    logger.info("\n" + "="*52 + "\n  BTC/ETH ENSEMBLE – PERFORMANCE REPORT\n" + "="*52)
    logger.info(f"  TOTAL RETURN: {metrics.get('total_return_pct', 0):.2f}%")
    logger.info(f"  WIN RATE:     {metrics.get('win_rate_pct', 0):.2f}%")
    logger.info(f"  PROFIT FACTOR:{metrics.get('profit_factor', 0):.4f}")
    logger.info(f"  MAX DRAWDOWN: {metrics.get('max_drawdown_pct', 0):.2f}%")
    logger.info(f"  SHARPE RATIO: {metrics.get('sharpe_ratio', 0):.4f}")
    logger.info(f"  CALMAR RATIO: {metrics.get('calmar_ratio', 0):.4f}")
    logger.info(f"  TRADE COUNT:  {metrics.get('total_trades_count', 0)}")
    logger.info("="*52)

def run_backtest(test_data: dict, method: str = "dynamic_weighted") -> pd.DataFrame:
    """
    Step through the test environment deterministically using the
    Ensemble agent and collect episode data.

    Returns
    -------
    pd.DataFrame
        Timestep-level DataFrame with columns:
        timestamp, portfolio_value, btc_weight, eth_weight, cash_weight,
        transaction_cost, action_btc, action_eth
    """
    # ── Load data & environment ──────────────────────────────────────────
    env = BinanceSpotEnv(test_data, initial_capital=INITIAL_CAPITAL, mode="eval")

    # ── Load ensemble ────────────────────────────────────────────────────
    ensemble = load_ensemble(MODELS_DIR)

    # Optionally load per-agent validation Sharpe for weighted mode
    agent_sharpes = None
    sharpes_path = RESULTS_DIR / "agent_sharpes.csv"
    if sharpes_path.exists() and method == "weighted":
        sdf = pd.read_csv(sharpes_path, index_col=0)
        agent_sharpes = sdf["sharpe"].to_dict()
        logger.info(f"Loaded per-agent Sharpe scores for weighted ensemble: {agent_sharpes}")

    agent = EnsembleAgent(ensemble, method=method, agent_sharpes=agent_sharpes)

    # For dynamic weighting
    virtual_portfolios = {algo: INITIAL_CAPITAL for algo in ensemble.keys()}
    virtual_weights = {algo: np.zeros(env.n_assets + 1) for algo in ensemble.keys()}
    for algo in virtual_weights: virtual_weights[algo][-1] = 1.0 # cash

    # ── Simulation loop ──────────────────────────────────────────────────
    obs, _ = env.reset()
    records = []
    done = False
    
    from collections import deque
    returns_history = {algo: deque(maxlen=24*7) for algo in ensemble.keys()} # 1 week rolling (assuming 1H)

    while not done:
        # Dynamic Weighting Updates
        if method == "dynamic_weighted":
            current_weights = {}
            for algo in ensemble.keys():
                hist = returns_history[algo]
                if len(hist) > 10:
                    algo_returns = np.array(hist)
                    mean_ret = np.mean(algo_returns)
                    std_ret = np.std(algo_returns) + 1e-9
                    sharpe = (mean_ret / std_ret) * np.sqrt(24 * 365) # annualized
                    current_weights[algo] = max(sharpe, 0.1) # Minimum weight
                else:
                    current_weights[algo] = 1.0
            agent._sharpes = current_weights
            
        elif method == "imca":
            regime = env.get_market_regime()
            # Iterative Model Combining Algorithm (IMCA)
            # High volatility (sideways/whipsaw) -> shift to SAC
            # Strong macro trend + Low volatility -> shift to PPO
            vol_z = regime["volatility_z"]
            macro_trend = regime["macro_trend"]
            
            # Simple sigmoid scaling based on volatility z-score
            # vol_z typically ranges from -3 to +3
            # If vol_z > 1.0 (high vol), sac_weight approaches 0.8-0.9
            # If vol_z < 0 (low vol compression), ppo_weight dominates
            sac_weight = 1.0 / (1.0 + np.exp(-vol_z))
            
            # If there's a strong macro trend, shift slightly back to PPO (trend-follower)
            if macro_trend > 0.05:
                sac_weight *= 0.5
                
            ppo_weight = 1.0 - sac_weight
            
            agent._sharpes = {
                "PPO": ppo_weight,
                "SAC": sac_weight
            }

        # To track individual virtual portfolios for next step
        proposals = {}
        for algo, model in ensemble.items():
            raw_action, _ = model.predict(obs, deterministic=True)
            w = _softmax_weights(raw_action)
            proposals[algo] = w

        # Ensemble logic: predict() returns softmax weights [0,1] summing to 1
        weights = agent.predict(obs)   # shape: (n_assets + 1,)

        # Record market returns *before* env.step_weights advances time.
        # _get_returns() now returns step_idx-1 (patched Fix 3-A), so this
        # snapshot is the same return that step_weights() will apply.
        market_returns = env._get_returns()

        # Update virtual portfolios using the *previous* weights and current market returns
        for algo in ensemble.keys():
            old_w = virtual_weights[algo]
            tc = env._compute_transaction_cost(old_w, proposals[algo])
            asset_pnl = float(np.dot(proposals[algo][:-1], market_returns - 1.0))
            net_return = (1.0 + asset_pnl) * (1.0 - tc)
            virtual_portfolios[algo] *= max(net_return, 1e-6)
            returns_history[algo].append(net_return - 1.0)
            virtual_weights[algo] = proposals[algo]

        # Fix 3-E: pass softmax weights directly — no spurious *2-1 inverse.
        obs, reward, terminated, truncated, info = env.step_weights(weights)
        done = terminated or truncated

        records.append({
            "timestamp":       info["timestamp"],
            "portfolio_value": info["portfolio_value"],
            "btc_weight":      info["weights"][0],
            "eth_weight":      info["weights"][1],
            "cash_weight":     info["weights"][2],
            "transaction_cost": info["transaction_cost"],
            "step_reward":     reward,
        })

    env.close()
    df = pd.DataFrame(records).set_index("timestamp")
    
    # Calculate trade count (number of times transaction cost > 0)
    trades_count = int((df['transaction_cost'] > 0).sum())
    
    logger.info(f"Backtest complete: {len(df)} steps | Final NAV: ${df['portfolio_value'].iloc[-1]:,.2f} | Trades: {trades_count}")
    return df, trades_count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--method", default=ENSEMBLE_METHOD,
                        choices=["mean", "voting", "weighted", "dynamic_weighted", "imca"])
    args = parser.parse_args()

    logger.info(f"Running backtest | Ensemble method: {args.method}")
    
    # Needs to be extracted so it's accessible for plotting
    test_data = {
        sym: pd.read_parquet(PROCESSED_DATA_DIR / f"{sym}_test.parquet")
        for sym in SYMBOLS
    }

    episode_df, trades_count = run_backtest(test_data, method=args.method)

    # Save raw episode log
    episode_path = RESULTS_DIR / "backtest_episode.parquet"
    episode_df.to_parquet(episode_path)
    logger.info(f"Episode log saved → {episode_path}")

    # ── Plot Visualisations ───────────────────────────────────────────────
    # Calculate a simple 50/50 static hold benchmark based on initial test data open prices
    first_prices = {sym: test_data[sym]["close"].iloc[0] if "close" in test_data[sym] else 1.0 for sym in SYMBOLS}
    # Since we dropped raw prices in preprocess, we will rely on cumulative exp of log returns
    # as a pure relative performance metric for the benchmark tracking!
    benchmark_returns = np.mean([np.exp(test_data[sym]["log_return_1h"].cumsum()) for sym in SYMBOLS], axis=0) * INITIAL_CAPITAL
    benchmark_series = pd.Series(benchmark_returns, index=test_data[SYMBOLS[0]].index, name="benchmark_nav")

    # ── Metrics ──────────────────────────────────────────────────────────
    metrics = compute_metrics(
        episode_df["portfolio_value"], 
        initial_capital=INITIAL_CAPITAL,
        benchmark_nav=benchmark_series,
        trades_count=trades_count
    )
    print_metrics_report(metrics)

    # ── Save metrics ──────────────────────────────────────────────────────
    metrics_path = RESULTS_DIR / "backtest_metrics.csv"
    pd.Series(metrics).to_csv(metrics_path, header=["value"])
    logger.info(f"Metrics saved → {metrics_path}")
    
    chart_path = RESULTS_DIR / "equity_curve.png"
    plot_equity_curve(episode_df["portfolio_value"], benchmark_nav=benchmark_series, save_path=chart_path)
    
    radar_path = RESULTS_DIR / "kpi_target_radar.png"
    plot_kpi_radar(metrics, save_path=radar_path)


if __name__ == "__main__":
    main()
