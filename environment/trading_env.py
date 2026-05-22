"""
Strategy Layer – FinRL-X Trading Environment
=============================================
A Gymnasium-compatible environment implementing a multi-asset
spot portfolio for BTC and ETH on Binance.

Key design decisions:
  • Weight-centric action space (FinRL-X convention):
      action = [w_BTC, w_ETH] ∈ [-1, 1]² (softmax-normalised internally)
      Remaining allocation goes to USDT (cash).
  • Observation = flattened lookback window of preprocessed features
    for all symbols + portfolio state.
  • Reward = log portfolio return over one step, penalised by
    proportional transaction cost.
  • Binance Spot – no shorting allowed (weights clipped to [0, 1]).
"""

import sys
from pathlib import Path
from typing import Any

import gymnasium as gym
import numpy as np
import pandas as pd
from gymnasium import spaces
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import (
    SYMBOLS, INITIAL_CAPITAL, BINANCE_SPOT_FEE,
    LOOKBACK_WINDOW, N_ASSETS, SLIPPAGE, REWARD_WEIGHTS,
    MIN_ORDER_USDT, REBALANCE_THRESHOLD,   # Fix 3-D, 3-F
)


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

class BinanceSpotEnv(gym.Env):
    """
    Multi-asset Spot trading environment for BTC/ETH.

    Observation space
    -----------------
    Flattened array of shape:
        (LOOKBACK_WINDOW × n_features_per_symbol × N_ASSETS)
        + portfolio features [current weights + cash ratio + total_portfolio_norm]

    Action space
    ------------
    Box([-1, -1], [1, 1]) – raw logits fed to a softmax that
    maps to (w_BTC, w_ETH, w_USDT).  Spot-only → weights clipped ≥ 0.

    Reward
    ------
    log(portfolio_t / portfolio_{t-1}) − transaction_cost
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

        # ── Align dataframes to a common index ──────────────────────────
        self._frames: dict[str, pd.DataFrame] = data
        common_idx = sorted(
            set.intersection(*[set(df.index) for df in data.values()])
        )
        self._index = pd.DatetimeIndex(common_idx)
        self._aligned: dict[str, pd.DataFrame] = {
            sym: df.loc[self._index] for sym, df in data.items()
        }
        self._n_features = next(iter(self._aligned.values())).shape[1]

        # ── Pre-compute NumPy arrays for extreme speedup ─────────────────
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
            self._macro_trend_array = self._aligned[self.symbols[0]]["raw_dist_sma_200_1d"].values
        for i, sym in enumerate(self.symbols):
            if "log_return_1h" in self._aligned[sym].columns:
                self._returns_array[:, i] = np.exp(self._aligned[sym]["log_return_1h"].values)

        # Cache feature indices for trailing stop and missed opportunity logic
        sample_df = self._aligned[self.symbols[0]]
        self._atr_idx = sample_df.columns.get_loc('atr_14') if 'atr_14' in sample_df.columns else 0
        self._bb_width_idx = sample_df.columns.get_loc('bb_width') if 'bb_width' in sample_df.columns else 0
        self._macd_1d_idx = sample_df.columns.get_loc('macd_1d') if 'macd_1d' in sample_df.columns else 0

        # ── Observation / Action spaces ──────────────────────────────────
        obs_size = self.lookback * self._n_features * self.n_assets + (self.n_assets + 1)
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_size,), dtype=np.float32
        )
        # Raw logits – normalised internally
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
            "macro_trend": self._macro_trend_array[self._step_idx]
        }

    # ────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ────────────────────────────────────────────────────────────────────

    def _reset_state(self):
        from collections import deque
        self._step_idx   = self.lookback          # start after warm-up
        self._portfolio  = self.capital           # scalar USD value
        self._weights    = np.zeros(self.n_assets + 1, dtype=np.float32)
        self._weights[-1] = 1.0                   # start 100% in USDT/cash
        self._max_portfolio = self.capital        # High-Water Mark for Absolute Drawdown
        self._rolling_window = deque([self.capital], maxlen=100) # For Rolling Drawdown
        
        # Continuous Action Smoothing tracking
        self._last_raw_action = np.zeros(self.n_assets, dtype=np.float32)
        
        # Synthetic price tracking for Hardcoded ATR Trailing Stop
        self._asset_synthetic_prices = np.ones(self.n_assets, dtype=np.float32)
        self._asset_highest_prices = np.ones(self.n_assets, dtype=np.float32)

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

    def _compute_transaction_cost(
        self, old_weights: np.ndarray, new_weights: np.ndarray
    ) -> float:
        """
        Proportional transaction cost + simulated slippage (Fix 3-D).

        Improvements over the original:
          • Fee is applied only where the USDT notional traded for an asset
            meets or exceeds MIN_ORDER_USDT (Binance rejects dust orders).
          • Old code applied fees on weight *fractions* without checking
            whether the underlying notional was tradeable; this caused
            backtest to over-penalise tiny rebalances that Binance ignores.
        """
        delta = np.abs(new_weights[:-1] - old_weights[:-1])
        # Notional traded per asset in USDT
        notional = delta * self._portfolio
        # Suppress fee on dust trades that Binance would reject
        tradeable = (notional >= MIN_ORDER_USDT).astype(np.float32)
        effective_delta = delta * tradeable
        return float(effective_delta.sum() * (self.fee + self.slippage))

    # ────────────────────────────────────────────────────────────────────
    # Gymnasium API
    # ────────────────────────────────────────────────────────────────────

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

        # ── 1. Action Smoothing (Temporal Decay) ─────────────────────────
        alpha = 0.2
        smoothed_action = (1.0 - alpha) * self._last_raw_action + alpha * action
        self._last_raw_action = smoothed_action

        planned_weights = self._softmax_weights(smoothed_action)
        
        # ── Deadband Filter / Rebalancing Threshold (Fix 3-F) ───────────────
        # REBALANCE_THRESHOLD is now loaded from config.py (was a hard-coded local).
        weight_diff = np.abs(planned_weights[:-1] - self._weights[:-1]).sum()
        
        if weight_diff > REBALANCE_THRESHOLD:
            new_weights = planned_weights.copy()
        else:
            new_weights = self._weights.copy()
            
        old_weights = self._weights.copy()

        # Price change at this step for each asset
        returns = self._get_returns()   # ratio (e.g. 1.002 means +0.2%)

        # ── 2. Dynamic ATR Trailing Stops ────────────────────────────────
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

        # ── 3. Balanced Multi-Objective Reward & Opportunity Cost ────────
        step_log_return = float(np.log(max(net_return, 1e-6)))

        # SORTINO / WIN RATE SHAPING:
        # Asymmetric Return Shaping (Penalize downside volatility 2.5x more than upside reward)
        if step_log_return < 0:
            step_log_return *= 2.5 

        # Define reward weights from config if available or use defaults        
        w_profit = 1.0
        w_drawdown = 2.0
        w_turnover = 0.5
        w_opportunity = 1.5

        # Components
        profit_t = step_log_return
        
        # OMEGA / CVaR PROXY:
        # Exponential Drawdown Penalty (Barrier Function to crush Max DD tails)
        # Squaring the drawdown converts linear penalty to a curved barrier, 
        # ignoring minor noise but sharply penalizing -15%+ drawdowns.
        drawdown_t = (abs(rolling_drawdown) ** 2) * 10.0
        turnover_t = tc

        # Curing Turtling: Missed Opportunity Cost
        # If distance > 2% (0.02) we are in a confirmed daily uptrend.
        macro_dist = self._macro_trend_array[self._step_idx]
        cash_weight = new_weights[-1]
        opportunity_cost = 0.0
        
        if macro_dist > 0.02 and cash_weight > 0.5:
            # Scaled penalty: the more cash held above 50% during an uptrend, the harsher the penalty.
            # Multiplied by macro_dist so a stronger trend means a harsher penalty for missing it.
            opportunity_cost = (cash_weight - 0.5) * macro_dist * 5.0 

        # Linear combination
        reward = (w_profit * profit_t) - (w_drawdown * drawdown_t) - (w_turnover * turnover_t) - (w_opportunity * opportunity_cost)

        terminated = self._step_idx >= len(self._index) - 1

        # Terminal Penalty / Kill-switch at 15% Absolute Drawdown
        if abs_drawdown <= -0.15:
            if self.mode == "train":
                reward -= 5.0   # Large explicit terminal penalty
                terminated = True

        info = {
            "portfolio_value": self._portfolio,
            "weights": new_weights,
            "transaction_cost": tc,
            "step": self._step_idx,
            "timestamp": self._index[self._step_idx],
        }

        self._step_idx += 1
        obs = self._get_obs()

        return obs, reward, terminated, False, info

    def render(self):
        pass   # no rendering in headless training; use metrics.py for analysis

    # ────────────────────────────────────────────────────────────────────
    # Production / Backtest execution path (Fix 3-E)
    # ────────────────────────────────────────────────────────────────────

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

        # ── Deadband filter (same threshold as step()) ───────────────────
        weight_diff = np.abs(target_weights[:-1] - self._weights[:-1]).sum()
        if weight_diff > REBALANCE_THRESHOLD:
            new_weights = target_weights.copy().astype(np.float32)
        else:
            new_weights = self._weights.copy()

        old_weights = self._weights.copy()
        returns = self._get_returns()  # already patched to step_idx - 1

        # ── Dynamic ATR Trailing Stops (identical to step()) ─────────────
        for i, sym in enumerate(self.symbols):
            self._asset_synthetic_prices[i] *= returns[i]
            if old_weights[i] > 0.01:
                self._asset_highest_prices[i] = max(
                    self._asset_highest_prices[i], self._asset_synthetic_prices[i]
                )
            else:
                self._asset_highest_prices[i] = self._asset_synthetic_prices[i]

            atr_z = self._obs_arrays[sym][self._step_idx - 1, self._atr_idx]
            dynamic_stop_pct = np.clip(0.04 + (atr_z * 0.01), 0.01, 0.10)
            dd_from_peak = (
                (self._asset_highest_prices[i] - self._asset_synthetic_prices[i])
                / self._asset_highest_prices[i]
            )
            if dd_from_peak >= dynamic_stop_pct:
                if new_weights[i] > 0:
                    new_weights[-1] += new_weights[i]
                    new_weights[i] = 0.0
                self._asset_highest_prices[i] = self._asset_synthetic_prices[i]

        tc = self._compute_transaction_cost(old_weights, new_weights)

        asset_pnl   = float(np.dot(new_weights[:-1], returns - 1.0))
        gross_return = 1.0 + asset_pnl
        net_return   = gross_return * (1.0 - tc)

        self._portfolio *= max(net_return, 1e-6)
        self._weights    = new_weights

        self._max_portfolio = max(self._max_portfolio, self._portfolio)
        abs_drawdown = (self._portfolio - self._max_portfolio) / (self._max_portfolio + 1e-9)

        self._rolling_window.append(self._portfolio)
        rolling_max     = max(self._rolling_window)
        rolling_drawdown = (self._portfolio - rolling_max) / (rolling_max + 1e-9)

        step_log_return = float(np.log(max(net_return, 1e-6)))
        if step_log_return < 0:
            step_log_return *= 2.5

        w_profit, w_drawdown, w_turnover, w_opportunity = 1.0, 2.0, 0.5, 1.5
        drawdown_t    = (abs(rolling_drawdown) ** 2) * 10.0
        macro_dist    = self._macro_trend_array[self._step_idx]
        cash_weight   = new_weights[-1]
        opportunity_cost = 0.0
        if macro_dist > 0.02 and cash_weight > 0.5:
            opportunity_cost = (cash_weight - 0.5) * macro_dist * 5.0

        reward = (
            (w_profit * step_log_return)
            - (w_drawdown * drawdown_t)
            - (w_turnover * tc)
            - (w_opportunity * opportunity_cost)
        )

        terminated = self._step_idx >= len(self._index) - 1
        if abs_drawdown <= -0.15 and self.mode == "train":
            reward -= 5.0
            terminated = True

        info = {
            "portfolio_value": self._portfolio,
            "weights":         new_weights,
            "transaction_cost": tc,
            "step":            self._step_idx,
            "timestamp":       self._index[self._step_idx],
        }

        self._step_idx += 1
        obs = self._get_obs()
        return obs, reward, terminated, False, info
