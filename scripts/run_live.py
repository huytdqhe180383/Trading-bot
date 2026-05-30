"""
Canonical live execution runner (OKX-first, CCXT, fusion-enabled).
"""

from __future__ import annotations

import argparse
import json
import os
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
    LIVE_BASELINE_MODEL_DIR,
    LIVE_KILL_SWITCH_MAX_TURNOVER,
    LIVE_MAX_DATA_STALENESS_SECS,
    LIVE_REQUIRE_NATIVE_KRONOS,
    LIVE_REQUIRE_NATIVE_TRADINGAGENTS,
    LOGS_DIR,
    MAX_ASSET_WEIGHT,
    MAX_PORTFOLIO_TURNOVER,
    MAX_TILT_PER_SIGNAL,
    MATERIAL_TRADE_THRESHOLD,
    MIN_HOLD_BARS,
    MODELS_DIR,
    POSITION_RESET_PERSIST_BARS,
    POSITION_RESET_WEIGHT_THRESHOLD,
    RESULTS_DIR,
    TRADINGAGENTS_CALL_TIMEOUT_SECS,
    TRADINGAGENTS_LIVE_CADENCE,
    TRADINGAGENTS_CHECKPOINT_ENABLED,
    PRIMARY_EXCHANGE,
    REBALANCE_INTERVAL_SECS,
    REBALANCE_THRESHOLD_CRISIS,
    REBALANCE_THRESHOLD_NORMAL,
    REBALANCE_THRESHOLD_STRESS,
    REVERSAL_HYSTERESIS_MULT,
    RISK_GOVERNOR_CRISIS_CASH_FLOOR,
    RISK_GOVERNOR_CRISIS_DRAWDOWN_THRESHOLD,
    RISK_GOVERNOR_CRISIS_MAX_RISK_ON,
    RISK_GOVERNOR_DRAWDOWN_THRESHOLD,
    RISK_GOVERNOR_ENABLED,
    RISK_GOVERNOR_STRESS_CASH_FLOOR,
    RISK_GOVERNOR_STRESS_MAX_RISK_ON,
    RISK_GOVERNOR_VOL_Z_THRESHOLD,
    SYMBOLS,
    TRADINGAGENTS_DECISION_LOG_PATH,
    TRADINGAGENTS_MAX_RETRIES,
    TRADINGAGENTS_PROVIDER_FALLBACKS,
    TRADINGAGENTS_RETRY_BACKOFF_SECS,
    MIN_CASH_FLOOR,
)
from data.live_feed import CCXTExchangeGateway
from risk.risk_constraints import apply_stress_risk_governor

load_dotenv()


def create_live_session_dir(results_dir: Path = RESULTS_DIR, *, run_date: str | None = None) -> Path:
    day = run_date or datetime.now().strftime("%Y-%m-%d")
    daily_dir = Path(results_dir) / "daily" / day
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


def write_live_session_metadata(session_dir: Path, metadata: dict[str, Any]) -> None:
    serializable = {
        key: str(value) if isinstance(value, Path) else value
        for key, value in metadata.items()
    }
    (session_dir / "live_session_metadata.json").write_text(
        json.dumps(serializable, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def append_live_session_row(session_csv_path: Path, row: dict[str, Any]) -> None:
    session_csv_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([row]).to_csv(
        session_csv_path,
        mode="a",
        header=not session_csv_path.exists(),
        index=False,
    )


def write_live_session_summary(session_dir: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    df = pd.DataFrame(rows)
    summary = {
        "rows": int(len(df)),
        "ok_rows": int((df.get("status", pd.Series(dtype=str)) == "ok").sum()) if "status" in df else 0,
        "blocked_rows": int((df.get("status", pd.Series(dtype=str)) == "blocked").sum()) if "status" in df else 0,
        "orders_submitted": int(df.get("orders_submitted", pd.Series(dtype=float)).fillna(0).sum()) if "orders_submitted" in df else 0,
        "orders_filled": int(df.get("orders_filled", pd.Series(dtype=float)).fillna(0).sum()) if "orders_filled" in df else 0,
        "max_nav": float(df.get("nav", pd.Series(dtype=float)).max()) if "nav" in df else 0.0,
        "min_nav": float(df.get("nav", pd.Series(dtype=float)).min()) if "nav" in df else 0.0,
        "last_nav": float(df.get("nav", pd.Series(dtype=float)).iloc[-1]) if "nav" in df and len(df) else 0.0,
        "last_status": str(df.get("status", pd.Series(dtype=str)).iloc[-1]) if "status" in df and len(df) else "",
    }
    (session_dir / "live_session_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )


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


def resolve_live_model_dir(model_dir: Path | None = None) -> Path:
    candidate = Path(model_dir) if model_dir is not None else LIVE_BASELINE_MODEL_DIR
    if (candidate / "PPO" / "ppo_best.zip").exists() and (candidate / "SAC" / "sac_best.zip").exists():
        return candidate
    return MODELS_DIR


def infer_obs_dim_from_ensemble(ensemble: dict[str, Any]) -> int:
    if not ensemble:
        raise ValueError("Cannot infer observation dimension from an empty ensemble.")
    for model in ensemble.values():
        obs_space = getattr(model, "observation_space", None)
        shape = getattr(obs_space, "shape", None)
        if shape and len(shape) == 1 and int(shape[0]) > 0:
            return int(shape[0])
    raise ValueError("Unable to infer observation dimension from loaded models.")


def has_exchange_credentials(exchange_id: str, mode: str) -> bool:
    prefix = exchange_id.upper()
    if mode.lower() == "testnet":
        prefix = f"{prefix}_TESTNET"
    required = [f"{prefix}_API_KEY", f"{prefix}_SECRET_KEY"]
    if exchange_id.lower() == "okx":
        required.append(f"{prefix}_PASSPHRASE")
    return all(bool(str(os.getenv(name, "")).strip()) for name in required)


def infer_market_regime(feature_state: dict[str, pd.DataFrame], *, nav: float, peak_nav: float) -> dict[str, float | str]:
    frame = feature_state.get(SYMBOLS[0])
    if frame is None or frame.empty:
        return {"volatility_z": 0.0, "atr_z": 0.0, "drawdown": 0.0, "label": "normal"}
    last = frame.iloc[-1]
    volatility_z = float(last.get("bb_width", 0.0))
    atr_z = float(last.get("atr_14", 0.0))
    drawdown = float((nav - peak_nav) / (peak_nav + 1e-9))
    if drawdown <= float(RISK_GOVERNOR_CRISIS_DRAWDOWN_THRESHOLD):
        label = "crisis"
    elif volatility_z >= float(RISK_GOVERNOR_VOL_Z_THRESHOLD) or drawdown <= float(RISK_GOVERNOR_DRAWDOWN_THRESHOLD):
        label = "stress"
    else:
        label = "normal"
    return {
        "volatility_z": volatility_z,
        "atr_z": atr_z,
        "drawdown": drawdown,
        "label": label,
    }


class LiveExecutionController:
    def __init__(self) -> None:
        self.bars_since_last_material_trade = max(int(MIN_HOLD_BARS), 0)
        self.last_material_trade_direction = np.zeros(len(SYMBOLS), dtype=np.float32)
        self.asset_highest_prices = np.zeros(len(SYMBOLS), dtype=np.float32)
        self.below_threshold_bars = np.zeros(len(SYMBOLS), dtype=np.int32)
        self.peak_nav: float | None = None

    @staticmethod
    def _normalize_weights(weights: np.ndarray) -> np.ndarray:
        normalized = np.asarray(weights, dtype=np.float32).copy()
        normalized[:-1] = np.clip(normalized[:-1], 0.0, 1.0)
        total_assets = float(normalized[:-1].sum())
        if total_assets > 1.0:
            normalized[:-1] /= total_assets
            total_assets = 1.0
        normalized[-1] = max(0.0, 1.0 - total_assets)
        return normalized.astype(np.float32)

    def apply(
        self,
        *,
        target_weights: np.ndarray,
        current_weights: np.ndarray,
        prices: dict[str, float],
        feature_state: dict[str, pd.DataFrame],
        nav: float,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        self.peak_nav = nav if self.peak_nav is None else max(self.peak_nav, nav)
        regime = infer_market_regime(feature_state, nav=nav, peak_nav=self.peak_nav)
        requested = self._normalize_weights(target_weights)

        governed, governor_diag = apply_stress_risk_governor(
            weights=requested,
            n_assets=len(SYMBOLS),
            volatility_z=float(regime["volatility_z"]),
            drawdown=float(regime["drawdown"]),
            vol_z_threshold=RISK_GOVERNOR_VOL_Z_THRESHOLD,
            drawdown_threshold=RISK_GOVERNOR_DRAWDOWN_THRESHOLD,
            crisis_drawdown_threshold=RISK_GOVERNOR_CRISIS_DRAWDOWN_THRESHOLD,
            stress_cash_floor=RISK_GOVERNOR_STRESS_CASH_FLOOR,
            crisis_cash_floor=RISK_GOVERNOR_CRISIS_CASH_FLOOR,
            stress_max_risk_on=RISK_GOVERNOR_STRESS_MAX_RISK_ON,
            crisis_max_risk_on=RISK_GOVERNOR_CRISIS_MAX_RISK_ON,
            enabled=RISK_GOVERNOR_ENABLED,
        )
        governor_forced = float(np.abs(governed[:-1] - requested[:-1]).sum()) > 1e-9

        regime_label = str(regime["label"])
        if regime_label == "crisis":
            threshold = float(REBALANCE_THRESHOLD_CRISIS)
        elif regime_label == "stress":
            threshold = float(REBALANCE_THRESHOLD_STRESS)
        else:
            threshold = float(REBALANCE_THRESHOLD_NORMAL)

        candidate = governed.astype(np.float32)
        per_asset_floor = min(float(MATERIAL_TRADE_THRESHOLD), max(threshold, 1e-6))
        blocked_by_hysteresis = False
        for idx in range(len(SYMBOLS)):
            if abs(float(candidate[idx] - current_weights[idx])) < per_asset_floor:
                candidate[idx] = current_weights[idx]
        candidate = self._normalize_weights(candidate)

        hysteresis_threshold = float(MATERIAL_TRADE_THRESHOLD) * max(float(REVERSAL_HYSTERESIS_MULT), 1.0)
        for idx in range(len(SYMBOLS)):
            delta = float(candidate[idx] - current_weights[idx])
            last_direction = float(self.last_material_trade_direction[idx])
            if abs(delta) <= 1e-9 or last_direction == 0.0:
                continue
            if np.sign(delta) != np.sign(last_direction) and abs(delta) < hysteresis_threshold:
                candidate[idx] = current_weights[idx]
                blocked_by_hysteresis = True
        candidate = self._normalize_weights(candidate)

        requested_delta = compute_turnover(current_weights, requested)
        candidate_delta = compute_turnover(current_weights, candidate)
        blocked_by_deadband = False
        blocked_by_cooldown = False
        if not governor_forced and candidate_delta <= threshold:
            blocked_by_deadband = True
            candidate = current_weights.copy()
        elif (
            not governor_forced
            and int(MIN_HOLD_BARS) > 0
            and requested_delta >= float(MATERIAL_TRADE_THRESHOLD)
            and self.bars_since_last_material_trade < int(MIN_HOLD_BARS)
        ):
            blocked_by_cooldown = True
            candidate = current_weights.copy()

        adjusted = candidate.copy()
        trailing_stop_assets: list[str] = []
        position_reset_triggered = False
        position_reset_reason: list[str] = []
        for idx, symbol in enumerate(SYMBOLS):
            price = float(prices.get(symbol, 0.0))
            if price <= 0.0:
                continue
            if self.asset_highest_prices[idx] <= 0.0:
                self.asset_highest_prices[idx] = price
            if current_weights[idx] > float(POSITION_RESET_WEIGHT_THRESHOLD):
                self.asset_highest_prices[idx] = max(self.asset_highest_prices[idx], price)
                self.below_threshold_bars[idx] = 0
            else:
                persist_bars = max(int(POSITION_RESET_PERSIST_BARS), 0)
                if persist_bars <= 0:
                    triggered = abs(float(self.asset_highest_prices[idx] - price)) > 1e-9
                    self.asset_highest_prices[idx] = price
                    if triggered:
                        position_reset_triggered = True
                        position_reset_reason.append(f"{symbol}:below_threshold_immediate")
                else:
                    self.below_threshold_bars[idx] += 1
                    if self.below_threshold_bars[idx] >= persist_bars:
                        triggered = abs(float(self.asset_highest_prices[idx] - price)) > 1e-9
                        self.asset_highest_prices[idx] = price
                        if triggered:
                            position_reset_triggered = True
                            position_reset_reason.append(f"{symbol}:below_threshold_persist")
            atr_z = float(regime["atr_z"])
            dynamic_stop_pct = float(np.clip(0.04 + (atr_z * 0.01), 0.01, 0.10))
            dd_from_peak = (self.asset_highest_prices[idx] - price) / max(self.asset_highest_prices[idx], 1e-9)
            if dd_from_peak >= dynamic_stop_pct and adjusted[idx] > 0:
                adjusted[-1] += adjusted[idx]
                adjusted[idx] = 0.0
                self.asset_highest_prices[idx] = price
                trailing_stop_assets.append(symbol)
        adjusted = self._normalize_weights(adjusted)

        executed_delta = compute_turnover(current_weights, adjusted)
        material_trade_executed = executed_delta >= float(MATERIAL_TRADE_THRESHOLD)
        if material_trade_executed:
            self.last_material_trade_direction = np.sign(adjusted[:-1] - current_weights[:-1]).astype(np.float32)
            self.bars_since_last_material_trade = 0
        else:
            self.bars_since_last_material_trade += 1

        diag = {
            "requested_weight_delta": requested_delta,
            "executed_weight_delta": executed_delta,
            "rebalance_threshold": threshold,
            "execution_regime_label": regime_label,
            "rebalance_blocked_by_deadband": blocked_by_deadband,
            "rebalance_blocked_by_cooldown": blocked_by_cooldown,
            "rebalance_blocked_by_hysteresis": blocked_by_hysteresis,
            "rebalance_forced_by_governor": bool(governor_forced),
            "rebalance_forced_by_trailing_stop": bool(trailing_stop_assets),
            "trailing_stop_liquidation_count": len(trailing_stop_assets),
            "trailing_stop_liquidation_assets": ",".join(trailing_stop_assets),
            "position_reset_triggered": position_reset_triggered,
            "position_reset_reason": ",".join(position_reset_reason),
            "bars_since_last_material_trade": self.bars_since_last_material_trade,
            "material_trade_executed": material_trade_executed,
            "risk_governor_active": bool(governor_diag.get("active", False)),
            "risk_governor_reason": str(governor_diag.get("reason", "")),
            "risk_governor_cash_floor": float(governor_diag.get("cash_floor", 0.0)),
            "risk_governor_max_risk_on": float(governor_diag.get("max_risk_on", 0.0)),
        }
        return adjusted.astype(np.float32), diag


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
    parser.add_argument("--model-dir", type=Path, default=LIVE_BASELINE_MODEL_DIR)
    parser.add_argument(
        "--method",
        default=ENSEMBLE_METHOD,
        choices=["mean", "voting", "weighted", "dynamic_weighted", "regime_weighted", "imca"],
    )
    parser.add_argument("--dry-run", action="store_true", help="Compute and log orders without submitting.")
    parser.add_argument("--max-cycles", type=int, default=0, help="Stop after N cycles. 0 means run forever.")
    parser.add_argument("--session-date", type=str, default=None, help="Optional YYYY-MM-DD override for artifact session folder.")
    parser.add_argument("--bootstrap-usdt", type=float, default=10_000.0)
    parser.add_argument("--bootstrap-btc", type=float, default=0.0)
    parser.add_argument("--bootstrap-eth", type=float, default=0.0)
    parser.add_argument("--enable-kronos", dest="enable_kronos", action="store_true")
    parser.add_argument("--disable-kronos", dest="enable_kronos", action="store_false")
    parser.add_argument("--enable-tradingagents", dest="enable_ta", action="store_true")
    parser.add_argument("--disable-tradingagents", dest="enable_ta", action="store_false")
    parser.set_defaults(enable_kronos=ENABLE_KRONOS, enable_ta=ENABLE_TRADINGAGENTS)
    args = parser.parse_args()
    args.model_dir = resolve_live_model_dir(args.model_dir)

    log_file = LOGS_DIR / f"run_{args.exchange}_{args.mode}.log"
    logger.add(log_file, rotation="10 MB", retention="30 days")
    session_dir = create_live_session_dir(RESULTS_DIR, run_date=args.session_date)
    session_csv_path = session_dir / f"live_trade_decisions_{args.exchange}_{args.mode}.csv"
    write_live_session_metadata(
        session_dir,
        {
            "created_at": datetime.now().isoformat(),
            "exchange": args.exchange,
            "mode": args.mode,
            "model_dir": args.model_dir,
            "method": args.method,
            "dry_run": args.dry_run,
            "max_cycles": args.max_cycles,
            "enable_kronos": args.enable_kronos,
            "enable_tradingagents": args.enable_ta,
            "bootstrap_usdt": args.bootstrap_usdt,
            "bootstrap_btc": args.bootstrap_btc,
            "bootstrap_eth": args.bootstrap_eth,
        },
    )
    logger.info(
        f"Live start | exchange={args.exchange.upper()} mode={args.mode.upper()} "
        f"dry_run={args.dry_run} method={args.method} kronos={args.enable_kronos} "
        f"ta={args.enable_ta} model_dir={args.model_dir} session_dir={session_dir}"
    )
    credentials_present = has_exchange_credentials(args.exchange, args.mode)
    if not credentials_present:
        logger.warning(f"Missing {args.exchange.upper()} {args.mode.upper()} private credentials.")
        if not args.dry_run:
            raise RuntimeError("Live/testnet execution requires exchange credentials. Use --dry-run or populate .env.")

    gateway = CCXTExchangeGateway(exchange_id=args.exchange, mode=args.mode, symbols=SYMBOLS)
    ensemble = load_ensemble(args.model_dir)
    rl_agent = EnsembleAgent(ensemble, method=args.method)
    execution_controller = LiveExecutionController()

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

    obs_dim = infer_obs_dim_from_ensemble(ensemble)

    csv_log_path = LOGS_DIR / f"live_trades_{args.exchange}.csv"
    csv_log_path.parent.mkdir(parents=True, exist_ok=True)

    cycle = 0
    initial_nav: float | None = None
    session_rows: list[dict[str, Any]] = []

    while True:
        cycle += 1
        ts = datetime.now(timezone.utc)
        logger.info(f"\n[Cycle {cycle}] {ts.isoformat()}")

        try:
            if credentials_present:
                balances, prices = gateway.fetch_balances_and_prices()
            elif args.dry_run:
                logger.warning("Using bootstrap dry-run balances because exchange credentials are missing.")
                raw_state = gateway.fetch_raw_ohlcv()
                if raw_state is None:
                    raise RuntimeError("public OHLCV unavailable for bootstrap dry-run")
                prices = {symbol: float(raw_state[symbol]['close'].iloc[-1]) for symbol in SYMBOLS}
                balances = {
                    "BTC": float(args.bootstrap_btc),
                    "ETH": float(args.bootstrap_eth),
                    "USDT": float(args.bootstrap_usdt),
                }
            else:
                raise RuntimeError("private credentials missing")
            current_weights, nav = compute_portfolio_weights(balances, prices)
            if initial_nav is None:
                initial_nav = nav
        except Exception as exc:
            logger.error(f"Balance/price fetch failed: {exc}")
            if args.max_cycles and cycle >= args.max_cycles:
                break
            time.sleep(REBALANCE_INTERVAL_SECS)
            continue

        feature_state = gateway.fetch_feature_state()
        raw_state = gateway.fetch_raw_ohlcv()
        if feature_state is None or raw_state is None:
            logger.error("Market state unavailable; skipping cycle.")
            if args.max_cycles and cycle >= args.max_cycles:
                break
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
        exec_weights, execution_diag = execution_controller.apply(
            target_weights=target_weights,
            current_weights=current_weights,
            prices=prices,
            feature_state=feature_state,
            nav=nav,
        )
        safety_reasons = evaluate_safety_gates(
            now_utc=pd.Timestamp(ts),
            raw_state=raw_state,
            current_weights=current_weights,
            target_weights=exec_weights,
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
                "btc_weight": float(exec_weights[0]),
                "eth_weight": float(exec_weights[1]),
                "cash_weight": float(exec_weights[2]),
                "orders": "[]",
                "rl_base_weights": str(diagnostics.rl_base),
                "post_risk_weights": str(diagnostics.post_risk),
                "execution_weights": str(exec_weights.tolist()),
                "execution_diag": str(execution_diag),
                "kronos_signal_count": len(kronos_signals or {}),
                "tradingagents_source": getattr(ta_signal, "source", ""),
                "orders_submitted": 0,
                "orders_filled": 0,
                "status": "blocked",
                "safety_gate_reasons": " | ".join(safety_reasons),
            }
            append_live_session_row(csv_log_path, row)
            append_live_session_row(session_csv_path, row)
            session_rows.append(row)
            write_live_session_summary(session_dir, session_rows)
            if args.max_cycles and cycle >= args.max_cycles:
                break
            time.sleep(REBALANCE_INTERVAL_SECS)
            continue
        logger.info(
            f"Target weights -> BTC={exec_weights[0]:.3f} ETH={exec_weights[1]:.3f} USDT={exec_weights[2]:.3f}"
        )

        orders = gateway.build_rebalance_orders(
            target_weights=exec_weights.tolist(),
            balances=balances,
            prices=prices,
        )
        filled_count = 0
        for order in orders:
            logger.info(f"ORDER {order['side'].upper()} {order['amount']} {order['symbol']}")
            if args.dry_run:
                continue
            try:
                result = gateway.create_market_order(order["symbol"], order["side"], order["amount"])
                logger.success(f"Filled order id={result.get('id')}")
                filled_count += 1
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
            "btc_weight": float(exec_weights[0]),
            "eth_weight": float(exec_weights[1]),
            "cash_weight": float(exec_weights[2]),
            "orders": str(orders),
            "rl_base_weights": str(diagnostics.rl_base),
            "post_risk_weights": str(diagnostics.post_risk),
            "execution_weights": str(exec_weights.tolist()),
            "execution_diag": str(execution_diag),
            "kronos_signal_count": len(kronos_signals or {}),
            "tradingagents_source": getattr(ta_signal, "source", ""),
            "orders_submitted": int(len(orders)),
            "orders_filled": int(filled_count if not args.dry_run else len(orders)),
            "status": "ok",
            "safety_gate_reasons": "",
        }
        append_live_session_row(csv_log_path, row)
        append_live_session_row(session_csv_path, row)
        session_rows.append(row)
        write_live_session_summary(session_dir, session_rows)
        if args.max_cycles and cycle >= args.max_cycles:
            break
        time.sleep(REBALANCE_INTERVAL_SECS)


if __name__ == "__main__":
    main()
