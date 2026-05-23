"""
Canonical live execution runner (OKX-first, CCXT, fusion-enabled).
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters import KronosAdapter, TradingAgentsAdapter
from agents.ensemble_agent import EnsembleAgent, load_ensemble
from agents.meta_fusion_agent import MetaFusionAgent
from config import (
    ENABLE_KRONOS,
    ENABLE_TRADINGAGENTS,
    ENSEMBLE_METHOD,
    KRONOS_FORECAST_HORIZON,
    KRONOS_MODEL_ID,
    KRONOS_TOKENIZER_ID,
    LIVE_KILL_SWITCH_MAX_TURNOVER,
    LIVE_MAX_DATA_STALENESS_SECS,
    LIVE_REQUIRE_NATIVE_KRONOS,
    LIVE_REQUIRE_NATIVE_TRADINGAGENTS,
    LOGS_DIR,
    MAX_ASSET_WEIGHT,
    MAX_PORTFOLIO_TURNOVER,
    MAX_TILT_PER_SIGNAL,
    MODELS_DIR,
    TRADINGAGENTS_CALL_TIMEOUT_SECS,
    TRADINGAGENTS_LIVE_CADENCE,
    TRADINGAGENTS_CHECKPOINT_ENABLED,
    PRIMARY_EXCHANGE,
    REBALANCE_INTERVAL_SECS,
    SYMBOLS,
    TRADINGAGENTS_DECISION_LOG_PATH,
    TRADINGAGENTS_MAX_RETRIES,
    TRADINGAGENTS_PROVIDER_FALLBACKS,
    TRADINGAGENTS_RETRY_BACKOFF_SECS,
    MIN_CASH_FLOOR,
)
from data.live_feed import CCXTExchangeGateway
from environment.trading_env import BinanceSpotEnv

load_dotenv()


def compute_portfolio_weights(
    balances: dict[str, float],
    prices: dict[str, float],
) -> tuple[np.ndarray, float]:
    asset_values = []
    for symbol in SYMBOLS:
        asset = symbol.replace("USDT", "")
        asset_values.append(balances.get(asset, 0.0) * prices.get(symbol, 0.0))
    cash = balances.get("USDT", 0.0)
    nav = float(cash + sum(asset_values))
    if nav <= 1e-9:
        return np.array([0.0, 0.0, 1.0], dtype=np.float32), 0.0
    weights = np.array([asset_values[0] / nav, asset_values[1] / nav, cash / nav], dtype=np.float32)
    return weights, nav


def _build_obs(
    feature_state: dict[str, pd.DataFrame],
    current_weights: np.ndarray,
    obs_dim: int,
) -> np.ndarray:
    obs_arrays = [feature_state[sym].values.flatten() for sym in SYMBOLS]
    obs = np.concatenate(obs_arrays + [current_weights]).astype(np.float32)
    if len(obs) < obs_dim:
        obs = np.pad(obs, (0, obs_dim - len(obs)))
    elif len(obs) > obs_dim:
        obs = obs[:obs_dim]
    return obs


def latest_market_timestamp(state: dict[str, pd.DataFrame] | None) -> pd.Timestamp | None:
    if not state:
        return None
    latest: pd.Timestamp | None = None
    for frame in state.values():
        if frame is None or frame.empty:
            continue
        ts = pd.Timestamp(frame.index[-1])
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        if latest is None or ts > latest:
            latest = ts
    return latest


def compute_turnover(current_weights: np.ndarray, target_weights: np.ndarray) -> float:
    current = np.asarray(current_weights, dtype=np.float32)
    target = np.asarray(target_weights, dtype=np.float32)
    return float(np.abs(target[:-1] - current[:-1]).sum())


def evaluate_safety_gates(
    *,
    now_utc: pd.Timestamp,
    raw_state: dict[str, pd.DataFrame] | None,
    current_weights: np.ndarray,
    target_weights: np.ndarray,
    enable_kronos: bool,
    kronos_signals: dict[str, Any] | None,
    enable_tradingagents: bool,
    trading_signal: Any | None,
    max_data_staleness_secs: int,
    max_turnover: float,
    require_native_kronos: bool,
    require_native_tradingagents: bool,
) -> list[str]:
    reasons: list[str] = []

    latest_ts = latest_market_timestamp(raw_state)
    if latest_ts is None:
        reasons.append("market data timestamp unavailable")
    else:
        now = pd.Timestamp(now_utc)
        if now.tzinfo is None:
            now = now.tz_localize("UTC")
        else:
            now = now.tz_convert("UTC")
        staleness = max(0.0, float((now - latest_ts).total_seconds()))
        if staleness > max_data_staleness_secs:
            reasons.append(
                f"market data stale by {staleness:.0f}s "
                f"(limit={max_data_staleness_secs}s, latest={latest_ts.isoformat()})"
            )

    turnover = compute_turnover(current_weights, target_weights)
    if turnover > max_turnover:
        reasons.append(f"turnover kill-switch triggered ({turnover:.3f} > {max_turnover:.3f})")

    if enable_kronos and require_native_kronos:
        if not kronos_signals:
            reasons.append("kronos signals unavailable")
        elif any(getattr(sig, "source", "") != "kronos" for sig in kronos_signals.values()):
            reasons.append("kronos non-native signal active")

    if enable_tradingagents and require_native_tradingagents:
        if trading_signal is None:
            reasons.append("tradingagents signal unavailable")
        elif not str(getattr(trading_signal, "source", "")).startswith("tradingagents:"):
            reasons.append("tradingagents non-native signal active")

    return reasons


def main() -> None:
    parser = argparse.ArgumentParser(description="Run live trading with RL + optional Kronos + TradingAgents fusion.")
    parser.add_argument("--exchange", default=PRIMARY_EXCHANGE, choices=["okx", "binance"])
    parser.add_argument("--mode", default="testnet", choices=["testnet", "live"])
    parser.add_argument(
        "--method",
        default=ENSEMBLE_METHOD,
        choices=["mean", "voting", "weighted", "dynamic_weighted", "imca"],
    )
    parser.add_argument("--dry-run", action="store_true", help="Compute and log orders without submitting.")
    parser.add_argument("--enable-kronos", dest="enable_kronos", action="store_true")
    parser.add_argument("--disable-kronos", dest="enable_kronos", action="store_false")
    parser.add_argument("--enable-tradingagents", dest="enable_ta", action="store_true")
    parser.add_argument("--disable-tradingagents", dest="enable_ta", action="store_false")
    parser.set_defaults(enable_kronos=ENABLE_KRONOS, enable_ta=ENABLE_TRADINGAGENTS)
    args = parser.parse_args()

    log_file = LOGS_DIR / f"run_{args.exchange}_{args.mode}.log"
    logger.add(log_file, rotation="10 MB", retention="30 days")
    logger.info(
        f"Live start | exchange={args.exchange.upper()} mode={args.mode.upper()} "
        f"dry_run={args.dry_run} method={args.method} kronos={args.enable_kronos} ta={args.enable_ta}"
    )

    gateway = CCXTExchangeGateway(exchange_id=args.exchange, mode=args.mode, symbols=SYMBOLS)
    ensemble = load_ensemble(MODELS_DIR)
    rl_agent = EnsembleAgent(ensemble, method=args.method)

    kronos = KronosAdapter(
        enabled=args.enable_kronos,
        model_id=KRONOS_MODEL_ID,
        tokenizer_id=KRONOS_TOKENIZER_ID,
        forecast_horizon=KRONOS_FORECAST_HORIZON,
    )
    ta_adapter = TradingAgentsAdapter(
        enabled=args.enable_ta,
        provider=TRADINGAGENTS_PROVIDER_FALLBACKS,
        decision_log_path=TRADINGAGENTS_DECISION_LOG_PATH,
        max_retries=TRADINGAGENTS_MAX_RETRIES,
        retry_backoff_secs=TRADINGAGENTS_RETRY_BACKOFF_SECS,
        call_timeout_secs=TRADINGAGENTS_CALL_TIMEOUT_SECS,
        checkpoint_enabled=TRADINGAGENTS_CHECKPOINT_ENABLED,
        cadence=TRADINGAGENTS_LIVE_CADENCE,
    )
    fusion = MetaFusionAgent(
        symbols=SYMBOLS,
        max_tilt_per_signal=MAX_TILT_PER_SIGNAL,
        max_portfolio_turnover=MAX_PORTFOLIO_TURNOVER,
        max_asset_weight=MAX_ASSET_WEIGHT,
        min_cash_floor=MIN_CASH_FLOOR,
    )

    local_data = {s: pd.read_parquet(Path("data/processed") / f"{s}_test.parquet") for s in SYMBOLS}
    ref_env = BinanceSpotEnv(local_data, mode="eval")
    obs_dim = ref_env.observation_space.shape[0]
    ref_env.close()

    csv_log_path = LOGS_DIR / f"live_trades_{args.exchange}.csv"
    csv_log_path.parent.mkdir(parents=True, exist_ok=True)

    cycle = 0
    initial_nav: float | None = None

    while True:
        cycle += 1
        ts = datetime.now(timezone.utc)
        logger.info(f"\n[Cycle {cycle}] {ts.isoformat()}")

        try:
            balances, prices = gateway.fetch_balances_and_prices()
            current_weights, nav = compute_portfolio_weights(balances, prices)
            if initial_nav is None:
                initial_nav = nav
        except Exception as exc:
            logger.error(f"Balance/price fetch failed: {exc}")
            time.sleep(REBALANCE_INTERVAL_SECS)
            continue

        feature_state = gateway.fetch_feature_state()
        raw_state = gateway.fetch_raw_ohlcv()
        if feature_state is None or raw_state is None:
            logger.error("Market state unavailable; skipping cycle.")
            time.sleep(REBALANCE_INTERVAL_SECS)
            continue

        obs = _build_obs(feature_state, current_weights, obs_dim)
        rl_weights = rl_agent.predict(obs)

        kronos_signals = kronos.predict_batch(raw_state, timestamp=ts) if args.enable_kronos else None
        ta_signal = (
            ta_adapter.evaluate(
                ticker=SYMBOLS[0],
                asof=pd.Timestamp(ts),
                market_snapshot=raw_state.get(SYMBOLS[0]),
            )
            if args.enable_ta
            else None
        )

        target_weights, diagnostics = fusion.fuse(
            rl_weights=rl_weights,
            current_weights=current_weights,
            kronos_signals=kronos_signals,
            trading_signal=ta_signal,
        )
        safety_reasons = evaluate_safety_gates(
            now_utc=pd.Timestamp(ts),
            raw_state=raw_state,
            current_weights=current_weights,
            target_weights=target_weights,
            enable_kronos=args.enable_kronos,
            kronos_signals=kronos_signals,
            enable_tradingagents=args.enable_ta,
            trading_signal=ta_signal,
            max_data_staleness_secs=LIVE_MAX_DATA_STALENESS_SECS,
            max_turnover=LIVE_KILL_SWITCH_MAX_TURNOVER,
            require_native_kronos=LIVE_REQUIRE_NATIVE_KRONOS,
            require_native_tradingagents=LIVE_REQUIRE_NATIVE_TRADINGAGENTS,
        )
        if safety_reasons:
            for reason in safety_reasons:
                logger.warning(f"SAFETY_GATE {reason}")
            row = {
                "timestamp_utc": ts.isoformat(),
                "cycle": cycle,
                "exchange": args.exchange,
                "mode": args.mode,
                "nav": nav,
                "pnl_usd": nav - (initial_nav or nav),
                "pnl_pct": ((nav - initial_nav) / initial_nav * 100.0) if (initial_nav and initial_nav > 0) else 0.0,
                "btc_weight": float(target_weights[0]),
                "eth_weight": float(target_weights[1]),
                "cash_weight": float(target_weights[2]),
                "orders": "[]",
                "rl_base_weights": str(diagnostics.rl_base),
                "post_risk_weights": str(diagnostics.post_risk),
                "kronos_signal_count": len(kronos_signals or {}),
                "tradingagents_source": getattr(ta_signal, "source", ""),
                "status": "blocked",
                "safety_gate_reasons": " | ".join(safety_reasons),
            }
            pd.DataFrame([row]).to_csv(csv_log_path, mode="a", header=not csv_log_path.exists(), index=False)
            time.sleep(REBALANCE_INTERVAL_SECS)
            continue
        logger.info(
            f"Target weights -> BTC={target_weights[0]:.3f} ETH={target_weights[1]:.3f} USDT={target_weights[2]:.3f}"
        )

        orders = gateway.build_rebalance_orders(
            target_weights=target_weights.tolist(),
            balances=balances,
            prices=prices,
        )
        for order in orders:
            logger.info(f"ORDER {order['side'].upper()} {order['amount']} {order['symbol']}")
            if args.dry_run:
                continue
            try:
                result = gateway.create_market_order(order["symbol"], order["side"], order["amount"])
                logger.success(f"Filled order id={result.get('id')}")
            except Exception as exc:
                logger.error(f"Order failed for {order['symbol']} {order['side']}: {exc}")

        pnl_usd = nav - (initial_nav or nav)
        pnl_pct = (pnl_usd / initial_nav * 100.0) if (initial_nav and initial_nav > 0) else 0.0
        logger.info(f"NAV=${nav:,.2f} | Session PnL=${pnl_usd:,.2f} ({pnl_pct:.2f}%)")

        row = {
            "timestamp_utc": ts.isoformat(),
            "cycle": cycle,
            "exchange": args.exchange,
            "mode": args.mode,
            "nav": nav,
            "pnl_usd": pnl_usd,
            "pnl_pct": pnl_pct,
            "btc_weight": float(target_weights[0]),
            "eth_weight": float(target_weights[1]),
            "cash_weight": float(target_weights[2]),
            "orders": str(orders),
            "rl_base_weights": str(diagnostics.rl_base),
            "post_risk_weights": str(diagnostics.post_risk),
            "kronos_signal_count": len(kronos_signals or {}),
            "tradingagents_source": getattr(ta_signal, "source", ""),
            "status": "ok",
            "safety_gate_reasons": "",
        }
        pd.DataFrame([row]).to_csv(csv_log_path, mode="a", header=not csv_log_path.exists(), index=False)
        time.sleep(REBALANCE_INTERVAL_SECS)


if __name__ == "__main__":
    main()
