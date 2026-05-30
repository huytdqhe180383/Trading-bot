"""
Strategy Layer â€“ FinRL-X Trading Environment
=============================================
A Gymnasium-compatible environment implementing a multi-asset
spot portfolio for BTC and ETH with a cash sleeve.

Key design decisions:
  â€¢ Weight-centric action space (FinRL-X convention):
      action = [w_BTC, w_ETH] âˆˆ [-1, 1]Â² (softmax-normalised internally)
      Remaining allocation goes to USDT (cash).
  â€¢ Observation = flattened lookback window of preprocessed features
    for all symbols + portfolio state.
  â€¢ Reward = log portfolio return over one step, penalised by
    proportional transaction cost.
  â€¢ Spot-only portfolio â€“ no shorting allowed (weights clipped to [0, 1]).
"""

import sys
from collections import deque
from pathlib import Path
from typing import Any

import gymnasium as gym
import numpy as np
import pandas as pd
from gymnasium import spaces

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import (
    SYMBOLS, INITIAL_CAPITAL, BINANCE_SPOT_FEE,
    LOOKBACK_WINDOW, N_ASSETS, SLIPPAGE,
    MIN_ORDER_USDT, REBALANCE_THRESHOLD,   # Fix 3-D, 3-F
    REBALANCE_THRESHOLD_NORMAL, REBALANCE_THRESHOLD_STRESS, REBALANCE_THRESHOLD_CRISIS,
    MIN_HOLD_BARS, MATERIAL_TRADE_THRESHOLD, REVERSAL_HYSTERESIS_MULT,
    POSITION_RESET_WEIGHT_THRESHOLD, POSITION_RESET_PERSIST_BARS,
    SLIPPAGE_MODEL, SLIPPAGE_VOL_WINDOW, SLIPPAGE_VOL_SCALAR, SLIPPAGE_VOL_CAP_MULT,
    KILL_SWITCH_ENABLED_EVAL, KILL_SWITCH_DRAWDOWN_THRESHOLD,
    STEP_TURNOVER_CAP_ENABLED, STEP_TURNOVER_CAP_NORMAL, STEP_TURNOVER_CAP_STRESS,
    STEP_TURNOVER_CAP_CRISIS,
    REWARD_WEIGHTS, TAIL_RISK_ALPHA, TAIL_RISK_WINDOW,
    REWARD_ACTION_DELTA_WEIGHT, REWARD_ACTION_DELTA_DEADBAND, REWARD_ACTION_DELTA_SCALE,
    RISK_GOVERNOR_ENABLED, RISK_GOVERNOR_VOL_Z_THRESHOLD,
    RISK_GOVERNOR_DRAWDOWN_THRESHOLD, RISK_GOVERNOR_CRISIS_DRAWDOWN_THRESHOLD,
    RISK_GOVERNOR_STRESS_CASH_FLOOR, RISK_GOVERNOR_CRISIS_CASH_FLOOR,
    RISK_GOVERNOR_STRESS_MAX_RISK_ON, RISK_GOVERNOR_CRISIS_MAX_RISK_ON,
    MAX_ASSET_WEIGHT, POSITION_CAP_MODE, NAV_SCALED_CAP_MIN_NAV,
    NAV_SCALED_CAP_MAX_NAV, NAV_SCALED_CAP_MIN_WEIGHT,
)
from risk.risk_constraints import apply_position_cap_mode, apply_stress_risk_governor


def _softmax_weights(action: np.ndarray) -> np.ndarray:
    """
    Convert raw action logits to portfolio weights matching the action space bounds.
    Action space is typically Box(-1.0, 1.0).
    Maps [-1.0, 1.0] to [0.0, 1.0], scaling appropriately so agent can securely 
    hold 100% Cash or 100% of an asset without asymptotic math bounds preventing it.
    """
    # 1. Map from [-1, 1] bounds from continuous space smoothly into [0, 1] target weights
    w = (np.clip(action, -1.0, 1.0) + 1.0) / 2.0 
    
    total_w = w.sum()
    if total_w > 1.0:
        # If agent attempts to allocate >100%, normalize relatively to requested proportions
        w = w / total_w
        cash_w = 0.0
    else:
        # Remaining proportion goes to holding Cash
        cash_w = 1.0 - total_w
        
    return np.append(w, cash_w).astype(np.float32)

class SpotPortfolioEnv(gym.Env):
    """
    Multi-asset Spot trading environment for BTC/ETH.

    Observation space
    -----------------
    Flattened array of shape:
        (LOOKBACK_WINDOW Ã— n_features_per_symbol Ã— N_ASSETS)
        + portfolio features [current weights + cash ratio + total_portfolio_norm]

    Action space
    ------------
    Box([-1, -1], [1, 1]) â€“ raw logits fed to a softmax that
    maps to (w_BTC, w_ETH, w_USDT).  Spot-only â†’ weights clipped â‰¥ 0.

    Reward
    ------
    log(portfolio_t / portfolio_{t-1}) âˆ’ transaction_cost
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        data: dict[str, pd.DataFrame],
        initial_capital: float = INITIAL_CAPITAL,
        trading_fee: float = BINANCE_SPOT_FEE,
        slippage: float = SLIPPAGE,
        lookback: int = LOOKBACK_WINDOW,
        mode: str = "train",   # "train" | "eval"
    ):
        super().__init__()

        self.symbols     = SYMBOLS
        self.n_assets    = N_ASSETS
        self.capital     = initial_capital
        self.fee         = trading_fee
        self.slippage    = slippage
        self.lookback    = lookback
        self.mode        = mode

        # â”€â”€ Align dataframes to a common index â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        self._frames: dict[str, pd.DataFrame] = data
        common_idx = sorted(
            set.intersection(*[set(df.index) for df in data.values()])
        )
        self._index = pd.DatetimeIndex(common_idx)
        self._aligned: dict[str, pd.DataFrame] = {
            sym: df.loc[self._index] for sym, df in data.items()
        }
        self._n_features = next(iter(self._aligned.values())).shape[1]

        # â”€â”€ Pre-compute NumPy arrays for extreme speedup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Separate logical arrays (like target returns & macro env logic) from neural network observation
        self._obs_columns = [
            c for c in next(iter(self._aligned.values())).columns 
            if not c.startswith("log_return") and not c.startswith("raw_")
        ]
        self._n_features = len(self._obs_columns)

        self._obs_arrays = {
            sym: self._aligned[sym][self._obs_columns].values.astype(np.float32)
            for sym in self.symbols
        }

        # Precompute returns (shape: n_steps x n_assets)
        self._returns_array = np.ones((len(self._index), self.n_assets), dtype=np.float32)
        
        # Precompute macro trends for Missed Opportunity Penalty (Using BTC as macro indicator)
        self._macro_trend_array = np.zeros(len(self._index), dtype=np.float32)
        if "raw_dist_sma_200_1d" in self._aligned[self.symbols[0]].columns:
            self._macro_trend_array = self._aligned[self.symbols[0]]["raw_dist_sma_200_1d"].values.copy()
        for i, sym in enumerate(self.symbols):
            if "log_return_1h" in self._aligned[sym].columns:
                self._returns_array[:, i] = np.exp(self._aligned[sym]["log_return_1h"].values)

        # Cache feature indices for trailing stop and missed opportunity logic
        self._atr_idx = self._obs_columns.index('atr_14') if 'atr_14' in self._obs_columns else 0
        self._bb_width_idx = self._obs_columns.index('bb_width') if 'bb_width' in self._obs_columns else 0
        self._macd_1d_idx = self._obs_columns.index('macd_1d') if 'macd_1d' in self._obs_columns else 0

        # â”€â”€ Observation / Action spaces â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        obs_size = self.lookback * self._n_features * self.n_assets + (self.n_assets + 1)
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_size,), dtype=np.float32
        )
        # Raw logits â€“ normalised internally
        self.action_space = spaces.Box(
            low=-1.0, high=1.0, shape=(self.n_assets,), dtype=np.float32
        )

        self._reset_state()

    def get_market_regime(self) -> dict:
        """Return the current market regime metrics for the IMCA ensemble agent."""
        # Using BTC (symbols[0]) as the proxy for the overall crypto market regime
        atr_z = self._obs_arrays[self.symbols[0]][self._step_idx - 1, self._atr_idx]
        bb_width_z = self._obs_arrays[self.symbols[0]][self._step_idx - 1, self._bb_width_idx]
        return {
            "volatility_z": bb_width_z, # Can also combine with atr_z
            "atr_z": atr_z,
            "macro_trend": self._macro_trend_array[self._step_idx - 1]
        }

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Internal helpers
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _reset_state(self):
        self._step_idx   = self.lookback          # start after warm-up
        self._portfolio  = self.capital           # scalar USD value
        self._weights    = np.zeros(self.n_assets + 1, dtype=np.float32)
        self._weights[-1] = 1.0                   # start 100% in USDT/cash
        self._max_portfolio = self.capital        # High-Water Mark for Absolute Drawdown
        self._rolling_window = deque([self.capital], maxlen=100) # For Rolling Drawdown
        self._recent_log_returns = deque(maxlen=TAIL_RISK_WINDOW)
        self._last_risk_governor_diag = {
            "active": False,
            "reason": "",
            "cash_floor": float(self._weights[-1]),
            "max_risk_on": float(self._weights[:-1].sum()),
        }
        self._last_turnover_cap_diag = {
            "applied": False,
            "limit": 0.0,
            "before": 0.0,
            "after": 0.0,
        }
        self._last_cost_diag = {
            "effective_slippage": float(self.slippage),
            "volatility_proxy": 0.0,
        }
        self._last_dynamic_max_asset_weight = float(MAX_ASSET_WEIGHT)
        self._bars_since_last_material_trade = max(int(MIN_HOLD_BARS), 0)
        self._last_material_trade_direction = np.zeros(self.n_assets, dtype=np.float32)
        self._position_reset_below_threshold_bars = np.zeros(self.n_assets, dtype=np.int32)
        self._last_execution_diag = {
            "requested_weight_delta": 0.0,
            "executed_weight_delta": 0.0,
            "rebalance_threshold": float(REBALANCE_THRESHOLD),
            "execution_regime_label": "normal",
            "rebalance_blocked_by_deadband": False,
            "rebalance_blocked_by_cooldown": False,
            "rebalance_blocked_by_hysteresis": False,
            "rebalance_forced_by_governor": False,
            "rebalance_forced_by_trailing_stop": False,
            "trailing_stop_liquidation_count": 0,
            "position_reset_triggered": False,
            "position_reset_reason": "",
            "bars_since_last_material_trade": 0,
            "material_trade_executed": False,
            "rebalance_blocked_by_min_notional": False,
            "min_notional_blocked_count": 0,
            "min_notional_blocked_assets": "",
            "dynamic_max_asset_weight": float(MAX_ASSET_WEIGHT),
        }
        
        # Continuous Action Smoothing tracking
        self._last_raw_action = np.zeros(self.n_assets, dtype=np.float32)
        
        # Synthetic price tracking for Hardcoded ATR Trailing Stop
        self._asset_synthetic_prices = np.ones(self.n_assets, dtype=np.float32)
        self._asset_highest_prices = np.ones(self.n_assets, dtype=np.float32)

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

    def _execution_regime_label(self) -> str:
        regime = self.get_market_regime()
        volatility_z = float(regime.get("volatility_z", 0.0))
        abs_drawdown = self._current_abs_drawdown()
        if abs_drawdown <= float(RISK_GOVERNOR_CRISIS_DRAWDOWN_THRESHOLD):
            return "crisis"
        if (
            volatility_z >= float(RISK_GOVERNOR_VOL_Z_THRESHOLD)
            or abs_drawdown <= float(RISK_GOVERNOR_DRAWDOWN_THRESHOLD)
        ):
            return "stress"
        return "normal"

    def _execution_rebalance_threshold(self) -> tuple[float, str]:
        regime_label = self._execution_regime_label()
        if regime_label == "crisis":
            return float(REBALANCE_THRESHOLD_CRISIS), regime_label
        if regime_label == "stress":
            return float(REBALANCE_THRESHOLD_STRESS), regime_label
        return float(REBALANCE_THRESHOLD_NORMAL), regime_label

    def _apply_execution_controls(
        self,
        target_weights: np.ndarray,
        *,
        current_weights: np.ndarray,
        governor_forced: bool,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        threshold, regime_label = self._execution_rebalance_threshold()
        requested = self._normalize_weights(target_weights)
        requested_delta = float(np.abs(requested[:-1] - current_weights[:-1]).sum())
        candidate = requested.copy()
        blocked_by_hysteresis = False

        per_asset_floor = min(float(MATERIAL_TRADE_THRESHOLD), max(threshold, 1e-6))
        for idx in range(self.n_assets):
            if abs(float(candidate[idx] - current_weights[idx])) < per_asset_floor:
                candidate[idx] = current_weights[idx]
        candidate = self._normalize_weights(candidate)

        hysteresis_threshold = float(MATERIAL_TRADE_THRESHOLD) * max(float(REVERSAL_HYSTERESIS_MULT), 1.0)
        for idx in range(self.n_assets):
            delta = float(candidate[idx] - current_weights[idx])
            last_direction = float(self._last_material_trade_direction[idx])
            if abs(delta) <= 1e-9 or last_direction == 0.0:
                continue
            if np.sign(delta) != np.sign(last_direction) and abs(delta) < hysteresis_threshold:
                candidate[idx] = current_weights[idx]
                blocked_by_hysteresis = True
        candidate = self._normalize_weights(candidate)

        candidate_delta = float(np.abs(candidate[:-1] - current_weights[:-1]).sum())
        blocked_by_deadband = False
        blocked_by_cooldown = False

        if not governor_forced and candidate_delta <= threshold:
            blocked_by_deadband = True
            candidate = current_weights.copy()
            candidate_delta = 0.0
        elif (
            not governor_forced
            and int(MIN_HOLD_BARS) > 0
            and requested_delta >= float(MATERIAL_TRADE_THRESHOLD)
            and self._bars_since_last_material_trade < int(MIN_HOLD_BARS)
        ):
            blocked_by_cooldown = True
            candidate = current_weights.copy()
            candidate_delta = 0.0

        diag = {
            "requested_weight_delta": requested_delta,
            "executed_weight_delta": candidate_delta,
            "rebalance_threshold": threshold,
            "execution_regime_label": regime_label,
            "rebalance_blocked_by_deadband": blocked_by_deadband,
            "rebalance_blocked_by_cooldown": blocked_by_cooldown,
            "rebalance_blocked_by_hysteresis": blocked_by_hysteresis,
            "rebalance_forced_by_governor": bool(governor_forced and candidate_delta > 0.0),
        }
        return candidate.astype(np.float32), diag

    def _apply_trailing_stop_and_position_reset(
        self,
        *,
        old_weights: np.ndarray,
        new_weights: np.ndarray,
        returns: np.ndarray,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        adjusted = new_weights.copy().astype(np.float32)
        trailing_stop_assets: list[str] = []
        reset_reasons: list[str] = []
        position_reset_triggered = False

        for i, sym in enumerate(self.symbols):
            self._asset_synthetic_prices[i] *= returns[i]

            if old_weights[i] > float(POSITION_RESET_WEIGHT_THRESHOLD):
                self._asset_highest_prices[i] = max(
                    self._asset_highest_prices[i], self._asset_synthetic_prices[i]
                )
                self._position_reset_below_threshold_bars[i] = 0
            else:
                persist_bars = max(int(POSITION_RESET_PERSIST_BARS), 0)
                if persist_bars <= 0:
                    triggered = abs(float(self._asset_highest_prices[i] - self._asset_synthetic_prices[i])) > 1e-9
                    self._asset_highest_prices[i] = self._asset_synthetic_prices[i]
                    position_reset_triggered = position_reset_triggered or triggered
                    if triggered:
                        reset_reasons.append(f"{sym}:below_threshold_immediate")
                else:
                    self._position_reset_below_threshold_bars[i] += 1
                    if self._position_reset_below_threshold_bars[i] >= persist_bars:
                        triggered = abs(float(self._asset_highest_prices[i] - self._asset_synthetic_prices[i])) > 1e-9
                        self._asset_highest_prices[i] = self._asset_synthetic_prices[i]
                        position_reset_triggered = position_reset_triggered or triggered
                        if triggered:
                            reset_reasons.append(f"{sym}:below_threshold_persist")

            atr_z = self._obs_arrays[sym][self._step_idx - 1, self._atr_idx]
            dynamic_stop_pct = np.clip(0.04 + (atr_z * 0.01), 0.01, 0.10)
            dd_from_peak = (
                (self._asset_highest_prices[i] - self._asset_synthetic_prices[i])
                / self._asset_highest_prices[i]
            )
            if dd_from_peak >= dynamic_stop_pct:
                if adjusted[i] > 0:
                    adjusted[-1] += adjusted[i]
                    adjusted[i] = 0.0
                    trailing_stop_assets.append(sym)
                self._asset_highest_prices[i] = self._asset_synthetic_prices[i]

        diag = {
            "rebalance_forced_by_trailing_stop": bool(trailing_stop_assets),
            "trailing_stop_liquidation_count": len(trailing_stop_assets),
            "trailing_stop_liquidation_assets": ",".join(trailing_stop_assets),
            "position_reset_triggered": position_reset_triggered,
            "position_reset_reason": ",".join(reset_reasons),
        }
        return self._normalize_weights(adjusted), diag

    def _apply_min_order_notional_filter(
        self,
        target_weights: np.ndarray,
        *,
        current_weights: np.ndarray,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        candidate = self._normalize_weights(target_weights)
        current = self._normalize_weights(current_weights)
        portfolio_value = float(max(self._portfolio, 0.0))
        if portfolio_value <= 1e-9:
            return candidate.astype(np.float32), {
                "rebalance_blocked_by_min_notional": False,
                "min_notional_blocked_count": 0,
                "min_notional_blocked_assets": "",
            }

        current_notional = current[:-1] * portfolio_value
        target_notional = candidate[:-1] * portfolio_value
        adjusted_notional = target_notional.copy()
        blocked_assets: list[str] = []

        for idx, sym in enumerate(self.symbols):
            delta_notional = abs(float(target_notional[idx] - current_notional[idx]))
            if 1e-9 < delta_notional < float(MIN_ORDER_USDT):
                adjusted_notional[idx] = current_notional[idx]
                blocked_assets.append(sym)

        cash_notional = max(portfolio_value - float(adjusted_notional.sum()), 0.0)
        adjusted_weights = np.append(adjusted_notional / portfolio_value, cash_notional / portfolio_value)
        adjusted = self._normalize_weights(adjusted_weights)
        return adjusted.astype(np.float32), {
            "rebalance_blocked_by_min_notional": bool(blocked_assets),
            "min_notional_blocked_count": len(blocked_assets),
            "min_notional_blocked_assets": ",".join(blocked_assets),
        }

    def _softmax_weights(self, action: np.ndarray) -> np.ndarray:
        return _softmax_weights(action)

    def _get_obs(self) -> np.ndarray:
        """Build the observation vector from cached NumPy arrays."""
        start = self._step_idx - self.lookback
        end   = self._step_idx

        feature_arrays = []
        for sym in self.symbols:
            window = self._obs_arrays[sym][start:end]  # (lookback, n_features)
            feature_arrays.append(window.flatten())

        portfolio_state = self._weights  # (n_assets + 1,) = weights + cash
        obs = np.concatenate(feature_arrays + [portfolio_state], axis=0)
        return obs.astype(np.float32)

    def _get_returns(self) -> np.ndarray:
        """
        Return the price-change ratio for the *just-completed* candle.

        Fix 3-A (audit Finding 1-F / 2-C):
        At decision time the agent's observation window covers
        [step_idx - lookback, step_idx), so the most recent bar in view
        is step_idx-1.  That bar's close-to-close return (log_return at
        index step_idx-1) is now fully realised; the agent's new weights
        are applied as if filled at that bar's close.

        Using step_idx (the *next* unseen bar) was the critical off-by-one
        that allowed the model to earn returns on prices it had not yet
        observed.
        """
        return self._returns_array[self._step_idx - 1]

    def _current_volatility_proxy(self) -> float:
        end = max(0, self._step_idx)
        start = max(0, end - int(SLIPPAGE_VOL_WINDOW))
        window = self._returns_array[start:end]
        if len(window) == 0:
            return 0.0
        return float(np.abs(window - 1.0).mean())

    def _effective_slippage(self) -> float:
        vol_proxy = self._current_volatility_proxy()
        if str(SLIPPAGE_MODEL).lower() == "vol_scaled":
            scaled = float(self.slippage) * (1.0 + float(SLIPPAGE_VOL_SCALAR) * vol_proxy)
            effective = min(scaled, float(self.slippage) * float(SLIPPAGE_VOL_CAP_MULT))
        else:
            effective = float(self.slippage)
        self._last_cost_diag = {
            "effective_slippage": effective,
            "volatility_proxy": vol_proxy,
        }
        return effective

    def _apply_position_cap(self, weights: np.ndarray) -> np.ndarray:
        capped, applied_cap = apply_position_cap_mode(
            weights=weights,
            n_assets=self.n_assets,
            nav=float(self._portfolio),
            position_cap_mode=POSITION_CAP_MODE,
            base_max_asset_weight=float(MAX_ASSET_WEIGHT),
            nav_scaled_cap_min_nav=float(NAV_SCALED_CAP_MIN_NAV),
            nav_scaled_cap_max_nav=float(NAV_SCALED_CAP_MAX_NAV),
            nav_scaled_cap_min_weight=float(NAV_SCALED_CAP_MIN_WEIGHT),
        )
        self._last_dynamic_max_asset_weight = float(applied_cap)
        return capped.astype(np.float32)

    def _compute_transaction_cost(
        self, old_weights: np.ndarray, new_weights: np.ndarray
    ) -> float:
        """
        Proportional transaction cost + simulated slippage (Fix 3-D).

        Improvements over the original:
          â€¢ Fee is applied only where the USDT notional traded for an asset
            meets or exceeds MIN_ORDER_USDT (the live exchange would reject dust orders).
          â€¢ Old code applied fees on weight *fractions* without checking
            whether the underlying notional was tradeable; this caused
            backtest to over-penalise tiny rebalances that the live venue would ignore.
        """
        delta = np.abs(new_weights[:-1] - old_weights[:-1])
        # Notional traded per asset in USDT
        notional = delta * self._portfolio
        # Suppress fee on dust trades that the live venue would reject
        tradeable = (notional >= MIN_ORDER_USDT).astype(np.float32)
        effective_delta = delta * tradeable
        return float(effective_delta.sum() * (self.fee + self._effective_slippage()))

    def _current_abs_drawdown(self) -> float:
        return float((self._portfolio - self._max_portfolio) / (self._max_portfolio + 1e-9))

    def _apply_stress_governor(self, weights: np.ndarray) -> np.ndarray:
        regime = self.get_market_regime()
        governed, diag = apply_stress_risk_governor(
            weights=weights,
            n_assets=self.n_assets,
            volatility_z=float(regime.get("volatility_z", 0.0)),
            drawdown=self._current_abs_drawdown(),
            vol_z_threshold=RISK_GOVERNOR_VOL_Z_THRESHOLD,
            drawdown_threshold=RISK_GOVERNOR_DRAWDOWN_THRESHOLD,
            crisis_drawdown_threshold=RISK_GOVERNOR_CRISIS_DRAWDOWN_THRESHOLD,
            stress_cash_floor=RISK_GOVERNOR_STRESS_CASH_FLOOR,
            crisis_cash_floor=RISK_GOVERNOR_CRISIS_CASH_FLOOR,
            stress_max_risk_on=RISK_GOVERNOR_STRESS_MAX_RISK_ON,
            crisis_max_risk_on=RISK_GOVERNOR_CRISIS_MAX_RISK_ON,
            enabled=RISK_GOVERNOR_ENABLED,
        )
        self._last_risk_governor_diag = diag
        return governed.astype(np.float32)

    def _turnover_cap_limit(self) -> float:
        if not STEP_TURNOVER_CAP_ENABLED:
            return 0.0
        reason = str(self._last_risk_governor_diag.get("reason", ""))
        if "crisis_drawdown" in reason:
            return float(STEP_TURNOVER_CAP_CRISIS)
        if bool(self._last_risk_governor_diag.get("active", False)):
            return float(STEP_TURNOVER_CAP_STRESS)
        return float(STEP_TURNOVER_CAP_NORMAL)

    def _apply_step_turnover_cap(self, target_weights: np.ndarray) -> np.ndarray:
        limit = self._turnover_cap_limit()
        before = float(np.abs(target_weights[:-1] - self._weights[:-1]).sum())
        if limit <= 0.0 or before <= limit or before <= 1e-9:
            self._last_turnover_cap_diag = {
                "applied": False,
                "limit": limit,
                "before": before,
                "after": before,
            }
            return target_weights.astype(np.float32)

        scale = float(limit / before)
        capped_assets = self._weights[:-1] + (target_weights[:-1] - self._weights[:-1]) * scale
        capped = np.append(capped_assets, 1.0 - float(capped_assets.sum())).astype(np.float32)
        after = float(np.abs(capped[:-1] - self._weights[:-1]).sum())
        self._last_turnover_cap_diag = {
            "applied": True,
            "limit": limit,
            "before": before,
            "after": after,
        }
        return capped

    def _compute_reward(
        self,
        *,
        net_return: float,
        transaction_cost: float,
        rolling_drawdown: float,
        old_weights: np.ndarray,
        new_weights: np.ndarray,
    ) -> tuple[float, dict[str, float]]:
        raw_log_return = float(np.log(max(net_return, 1e-6)))
        self._recent_log_returns.append(raw_log_return)

        profit_t = raw_log_return * (2.5 if raw_log_return < 0 else 1.0)
        drawdown_t = (abs(rolling_drawdown) ** 2) * 10.0
        turnover_t = float(transaction_cost)
        raw_action_delta = float(np.abs(new_weights[:-1] - old_weights[:-1]).sum())
        effective_action_delta = max(
            0.0,
            (raw_action_delta - float(REWARD_ACTION_DELTA_DEADBAND)) * float(REWARD_ACTION_DELTA_SCALE),
        )

        tail_loss_t = 0.0
        min_tail_samples = max(10, int(TAIL_RISK_WINDOW * 0.25))
        if len(self._recent_log_returns) >= min_tail_samples:
            returns = np.asarray(self._recent_log_returns, dtype=np.float32)
            threshold = float(np.quantile(returns, TAIL_RISK_ALPHA))
            tail = returns[returns <= threshold]
            if len(tail) > 0:
                tail_loss_t = max(0.0, -float(tail.mean()))

        macro_dist = float(self._macro_trend_array[self._step_idx - 1])
        cash_weight = float(new_weights[-1])
        opportunity_cost = 0.0
        if macro_dist > 0.02 and cash_weight > 0.5:
            opportunity_cost = (cash_weight - 0.5) * macro_dist * 5.0

        reward = (
            (float(REWARD_WEIGHTS.get("profit", 1.0)) * profit_t)
            - (float(REWARD_WEIGHTS.get("drawdown", 0.0)) * drawdown_t)
            - (float(REWARD_WEIGHTS.get("turnover", 0.0)) * turnover_t)
            - (float(REWARD_ACTION_DELTA_WEIGHT) * effective_action_delta)
            - (float(REWARD_WEIGHTS.get("missed_opportunity", 0.0)) * opportunity_cost)
            - (float(REWARD_WEIGHTS.get("tail_loss", 0.0)) * tail_loss_t)
        )
        components = {
            "raw_log_return": raw_log_return,
            "profit_component": profit_t,
            "drawdown_component": drawdown_t,
            "turnover_component": turnover_t,
            "raw_action_delta": raw_action_delta,
            "action_delta_component": effective_action_delta,
            "opportunity_component": opportunity_cost,
            "tail_loss_component": tail_loss_t,
        }
        return float(reward), components

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Gymnasium API
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def reset(
        self, *, seed: int | None = None, options: dict[str, Any] | None = None
    ) -> tuple[np.ndarray, dict]:
        super().reset(seed=seed)
        self._reset_state()
        return self._get_obs(), {}

    def step(
        self, action: np.ndarray
    ) -> tuple[np.ndarray, float, bool, bool, dict]:
        if self._step_idx >= len(self._index):
            # Episode finished
            return self._get_obs(), 0.0, True, False, {}

        # â”€â”€ 1. Action Smoothing (Temporal Decay) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        alpha = 0.2
        smoothed_action = (1.0 - alpha) * self._last_raw_action + alpha * action
        self._last_raw_action = smoothed_action

        planned_weights = self._softmax_weights(smoothed_action)
        
        # â”€â”€ Deadband Filter / Rebalancing Threshold (Fix 3-F) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # REBALANCE_THRESHOLD is now loaded from config.py (was a hard-coded local).
        weight_diff = np.abs(planned_weights[:-1] - self._weights[:-1]).sum()
        
        if weight_diff > REBALANCE_THRESHOLD:
            new_weights = planned_weights.copy()
        else:
            new_weights = self._weights.copy()
        new_weights = self._apply_position_cap(new_weights)
        new_weights = self._apply_stress_governor(new_weights)
        new_weights = self._apply_step_turnover_cap(new_weights)
            
        old_weights = self._weights.copy()

        # Price change at this step for each asset
        returns = self._get_returns()   # ratio (e.g. 1.002 means +0.2%)

        # â”€â”€ 2. Dynamic ATR Trailing Stops â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        for i, sym in enumerate(self.symbols):
            self._asset_synthetic_prices[i] *= returns[i]
            
            # Update high water mark if holding
            if old_weights[i] > 0.01:
                self._asset_highest_prices[i] = max(self._asset_highest_prices[i], self._asset_synthetic_prices[i])
            else:
                self._asset_highest_prices[i] = self._asset_synthetic_prices[i]

            # Fetch ATR z-score from state
            atr_z = self._obs_arrays[sym][self._step_idx - 1, self._atr_idx]
            
            # Base trailing stop 4%, widened by high volatility regimes
            dynamic_stop_pct = np.clip(0.04 + (atr_z * 0.01), 0.01, 0.10)
            
            dd_from_peak = (self._asset_highest_prices[i] - self._asset_synthetic_prices[i]) / self._asset_highest_prices[i]
            
            # Hardcoded Exit logic: Liquidate mathematically irrespective of agent choice 
            if dd_from_peak >= dynamic_stop_pct:
                if new_weights[i] > 0:
                    new_weights[-1] += new_weights[i]  # Send to cash
                    new_weights[i] = 0.0               # Force 0 position
                self._asset_highest_prices[i] = self._asset_synthetic_prices[i]

        new_weights, min_notional_diag = self._apply_min_order_notional_filter(
            new_weights,
            current_weights=old_weights,
        )

        # Transaction cost (proportional to rebalance amount)
        tc = self._compute_transaction_cost(old_weights, new_weights)

        # Portfolio return
        asset_pnl = float(np.dot(new_weights[:-1], returns - 1.0))
        gross_return = 1.0 + asset_pnl
        net_return   = gross_return * (1.0 - tc)

        self._portfolio *= max(net_return, 1e-6)
        self._weights    = new_weights
        
        # Track Drawdowns
        self._max_portfolio = max(self._max_portfolio, self._portfolio)
        abs_drawdown = (self._portfolio - self._max_portfolio) / (self._max_portfolio + 1e-9)
        
        self._rolling_window.append(self._portfolio)
        rolling_max = max(self._rolling_window)
        rolling_drawdown = (self._portfolio - rolling_max) / (rolling_max + 1e-9)

        # â”€â”€ 3. Balanced Multi-Objective Reward & Opportunity Cost â”€â”€â”€â”€â”€â”€â”€â”€
        reward, reward_components = self._compute_reward(
            net_return=net_return,
            transaction_cost=tc,
            rolling_drawdown=rolling_drawdown,
            old_weights=old_weights,
            new_weights=new_weights,
        )

        terminated = self._step_idx >= len(self._index) - 1

        # Terminal Penalty / Kill-switch at 15% Absolute Drawdown
        if abs_drawdown <= KILL_SWITCH_DRAWDOWN_THRESHOLD:
            if self.mode == "train":
                reward -= 5.0   # Large explicit terminal penalty
                terminated = True
            elif KILL_SWITCH_ENABLED_EVAL:
                terminated = True

        info = {
            "portfolio_value": self._portfolio,
            "weights": new_weights,
            "transaction_cost": tc,
            "step": self._step_idx,
            "timestamp": self._index[self._step_idx],
            "abs_drawdown": abs_drawdown,
            "rolling_drawdown": rolling_drawdown,
            "risk_governor": self._last_risk_governor_diag,
            "turnover_cap": self._last_turnover_cap_diag,
            "effective_slippage": self._last_cost_diag.get("effective_slippage", self.slippage),
            "slippage_volatility_proxy": self._last_cost_diag.get("volatility_proxy", 0.0),
            "dynamic_max_asset_weight": self._last_dynamic_max_asset_weight,
            "rebalance_blocked_by_min_notional": min_notional_diag["rebalance_blocked_by_min_notional"],
            "min_notional_blocked_count": min_notional_diag["min_notional_blocked_count"],
            "min_notional_blocked_assets": min_notional_diag["min_notional_blocked_assets"],
            **reward_components,
        }

        self._step_idx += 1
        obs = self._get_obs()

        return obs, reward, terminated, False, info

    def render(self):
        pass   # no rendering in headless training; use metrics.py for analysis

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Production / Backtest execution path (Fix 3-E)
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def step_weights(
        self, target_weights: np.ndarray
    ) -> tuple[np.ndarray, float, bool, bool, dict]:
        """
        Production-path step: accept pre-computed portfolio weights directly.

        Fix 3-E (audit Finding 2-E):
        During backtest/live trading the ensemble agent outputs softmax
        weights in [0, 1] that already sum to 1. The old backtest.py
        converted these back to [-1, 1] with `w * 2 - 1` and fed them
        into step(), which then re-applied action-smoothing EMA and a
        second softmax pass. That round-trip introduced systematic
        allocation drift that did not exist during training.

        This method bypasses action smoothing (a training-time
        regulariser, not a real-world execution constraint) and the
        softmax mapping entirely.  Use it from backtest.py and run_live.py.

        Parameters
        ----------
        target_weights : np.ndarray, shape (n_assets + 1,)
            Pre-computed portfolio weights [w_BTC, w_ETH, w_USDT]
            that sum to 1.0.
        """
        if self._step_idx >= len(self._index):
            return self._get_obs(), 0.0, True, False, {}

        assert len(target_weights) == self.n_assets + 1, (
            f"Expected {self.n_assets + 1} weights (including cash), "
            f"got {len(target_weights)}"
        )
        assert abs(target_weights.sum() - 1.0) < 1e-3, (
            f"Weights must sum to 1.0, got {target_weights.sum():.6f}"
        )

        old_weights = self._weights.copy()
        requested_weights = self._normalize_weights(target_weights)
        requested_weights = self._apply_position_cap(requested_weights)
        governed_weights = self._apply_stress_governor(requested_weights)
        governor_forced = float(np.abs(governed_weights[:-1] - requested_weights[:-1]).sum()) > 1e-9
        new_weights, execution_diag = self._apply_execution_controls(
            governed_weights,
            current_weights=old_weights,
            governor_forced=governor_forced,
        )
        new_weights = self._apply_step_turnover_cap(new_weights)

        returns = self._get_returns()
        new_weights, trailing_diag = self._apply_trailing_stop_and_position_reset(
            old_weights=old_weights,
            new_weights=new_weights,
            returns=returns,
        )

        new_weights, min_notional_diag = self._apply_min_order_notional_filter(
            new_weights,
            current_weights=old_weights,
        )

        tc = self._compute_transaction_cost(old_weights, new_weights)

        asset_pnl = float(np.dot(new_weights[:-1], returns - 1.0))
        gross_return = 1.0 + asset_pnl
        net_return = gross_return * (1.0 - tc)

        self._portfolio *= max(net_return, 1e-6)
        self._weights = new_weights
        executed_delta = float(np.abs(new_weights[:-1] - old_weights[:-1]).sum())
        material_trade_executed = executed_delta >= float(MATERIAL_TRADE_THRESHOLD)
        if material_trade_executed:
            self._last_material_trade_direction = np.sign(new_weights[:-1] - old_weights[:-1]).astype(np.float32)
            self._bars_since_last_material_trade = 0
        else:
            self._bars_since_last_material_trade += 1

        self._max_portfolio = max(self._max_portfolio, self._portfolio)
        abs_drawdown = (self._portfolio - self._max_portfolio) / (self._max_portfolio + 1e-9)

        self._rolling_window.append(self._portfolio)
        rolling_max = max(self._rolling_window)
        rolling_drawdown = (self._portfolio - rolling_max) / (rolling_max + 1e-9)

        reward, reward_components = self._compute_reward(
            net_return=net_return,
            transaction_cost=tc,
            rolling_drawdown=rolling_drawdown,
            old_weights=old_weights,
            new_weights=new_weights,
        )

        terminated = self._step_idx >= len(self._index) - 1
        if abs_drawdown <= KILL_SWITCH_DRAWDOWN_THRESHOLD:
            if self.mode == "train":
                reward -= 5.0
                terminated = True
            elif KILL_SWITCH_ENABLED_EVAL:
                terminated = True

        info = {
            "portfolio_value": self._portfolio,
            "weights": new_weights,
            "transaction_cost": tc,
            "step": self._step_idx,
            "timestamp": self._index[self._step_idx],
            "abs_drawdown": abs_drawdown,
            "rolling_drawdown": rolling_drawdown,
            "risk_governor": self._last_risk_governor_diag,
            "turnover_cap": self._last_turnover_cap_diag,
            "effective_slippage": self._last_cost_diag.get("effective_slippage", self.slippage),
            "slippage_volatility_proxy": self._last_cost_diag.get("volatility_proxy", 0.0),
            "dynamic_max_asset_weight": self._last_dynamic_max_asset_weight,
            "requested_weight_delta": execution_diag["requested_weight_delta"],
            "executed_weight_delta": executed_delta,
            "rebalance_threshold": execution_diag["rebalance_threshold"],
            "execution_regime_label": execution_diag["execution_regime_label"],
            "rebalance_blocked_by_deadband": execution_diag["rebalance_blocked_by_deadband"],
            "rebalance_blocked_by_cooldown": execution_diag["rebalance_blocked_by_cooldown"],
            "rebalance_blocked_by_hysteresis": execution_diag["rebalance_blocked_by_hysteresis"],
            "rebalance_forced_by_governor": execution_diag["rebalance_forced_by_governor"],
            "rebalance_forced_by_trailing_stop": trailing_diag["rebalance_forced_by_trailing_stop"],
            "trailing_stop_liquidation_count": trailing_diag["trailing_stop_liquidation_count"],
            "trailing_stop_liquidation_assets": trailing_diag["trailing_stop_liquidation_assets"],
            "position_reset_triggered": trailing_diag["position_reset_triggered"],
            "position_reset_reason": trailing_diag["position_reset_reason"],
            "bars_since_last_material_trade": self._bars_since_last_material_trade,
            "material_trade_executed": material_trade_executed,
            "rebalance_blocked_by_min_notional": min_notional_diag["rebalance_blocked_by_min_notional"],
            "min_notional_blocked_count": min_notional_diag["min_notional_blocked_count"],
            "min_notional_blocked_assets": min_notional_diag["min_notional_blocked_assets"],
            **reward_components,
        }
        self._last_execution_diag = {
            **execution_diag,
            "executed_weight_delta": executed_delta,
            "rebalance_forced_by_trailing_stop": trailing_diag["rebalance_forced_by_trailing_stop"],
            "trailing_stop_liquidation_count": trailing_diag["trailing_stop_liquidation_count"],
            "position_reset_triggered": trailing_diag["position_reset_triggered"],
            "position_reset_reason": trailing_diag["position_reset_reason"],
            "bars_since_last_material_trade": self._bars_since_last_material_trade,
            "material_trade_executed": material_trade_executed,
            "rebalance_blocked_by_min_notional": min_notional_diag["rebalance_blocked_by_min_notional"],
            "min_notional_blocked_count": min_notional_diag["min_notional_blocked_count"],
            "min_notional_blocked_assets": min_notional_diag["min_notional_blocked_assets"],
        }

        self._step_idx += 1
        obs = self._get_obs()
        return obs, reward, terminated, False, info


BinanceSpotEnv = SpotPortfolioEnv
