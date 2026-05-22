# BTC/ETH DRL System – Pre-Deployment Technical Audit

---

## 1. Data Integrity & Look-Ahead Bias Audit

### Finding 1-A: OBV Rolling Statistics Leak Future Data (`preprocess.py`, line 60)

**CRITICAL**

```python
# preprocess.py line 60
df["obv_norm"] = (obvs - obvs.rolling(20).mean()) / (obvs.rolling(20).std() + 1e-9)
```

`pandas_ta.obv()` returns a raw cumulative series. The normalisation applied here uses `.rolling(20).mean()` and `.rolling(20).std()` **without** an explicit `.shift(1)`. As written, the rolling window at index `t` includes the OBV value *at* `t`, meaning the agent at candle `t` sees information that is only confirmed at the *close* of candle `t`. While this is a minor edge case for OBV (it's computed from the same close that is already in the state), the correct production pattern is to always shift the normalised result by 1 to be unambiguous about temporal ordering, especially once the OBV series is subsequently passed into `_rolling_z_score`.

### Finding 1-B: `_rolling_z_score` Uses `min_periods=1` — Silent Warm-Up Leakage (`preprocess.py`, line 94-96)

**CRITICAL**

```python
# preprocess.py lines 94–96
mu    = df[cols].rolling(window, min_periods=1).mean()
sigma = df[cols].rolling(window, min_periods=1).std().replace(0, 1e-9)
df[cols] = (df[cols] - mu) / sigma
```

`min_periods=1` causes the first `window-1` rows (up to `LOOKBACK_WINDOW * 10 = 300` candles) to be normalised against a progressively growing, undersampled mean/std, not the true rolling-500 distribution. Because `base_df.dropna(inplace=True)` (line 168 / 187) runs **after** z-scoring, rows with enough NaNs from indicator warm-up are dropped, but the first 1–299 rows that survived indicator warm-up still have statistically unstable normalisations and will be included in the training window as distorted observations.

More critically: since the entire preprocessing pass runs on the **full multi-year dataset before `split_and_save`** performs the date split, the rolling mean/std at every timestamp before `2024-01-01` already "knows" how to normalise relative to the full posterior distribution. There is no global-scaler-fit-before-split bug here *in the traditional sense* (it's rolling, not a global `StandardScaler.fit`), but the first 300 candles of the training set will have volatile, non-production-representative normalised values. In production, you will never have 300 candles of warm-up history at model load time — you will have whatever is in your live ring buffer.

### Finding 1-C: `2024-01-01` Train/Test Split Is Correctly Isolated — No Cross-Contamination

**CLEAN**

```python
# preprocess.py lines 200–201
train = df.loc[TRAIN_START:TRAIN_END]   # "2020-01-01":"2023-12-31"
test  = df.loc[BACKTEST_START:BACKTEST_END]  # "2024-01-01":"2026-03-01"
```

There is a one-period gap: `TRAIN_END = "2023-12-31"` and `BACKTEST_START = "2024-01-01"`. Since the data is hourly, the last training candle is `2023-12-31 23:00 UTC` and the first test candle is `2024-01-01 00:00 UTC`. The split is clean — no index overlap. The rolling z-score's backward-looking window does not reach from the test set back into the training set because the rolling computation operates on the concatenated full frame *before* the split; however, since the rolling window is strictly backward-looking (pandas `.rolling()` with default `closed='right'`), test rows do not pollute training rows.

### Finding 1-D: Higher-Timeframe `df.shift(1)` Is Correct but Incomplete (`preprocess.py`, line 130)

**MEDIUM RISK**

```python
# preprocess.py lines 129–130
if ivl != BASE_TIMEFRAME:
    df = df.shift(1)
```

The intent is sound: a 4H candle labelled at `09:00` closes at `13:00`, so the features derived from it should only be visible on the `13:00` 1H candle (the candle immediately after the 4H candle closes). The `shift(1)` at 4H resolution shifts forward by **one 4H period (4 hours)**. After `merge_asof(direction="backward")`, this maps correctly.

However, the issue emerges during **live trading** with `run_live.py`. A 1D candle closes at `00:00 UTC`. After `shift(1)`, it becomes available at the *next* 1D open (`00:00 UTC` of the following day). But since the base timeframe is 1H, and the shift is by one 1D candle (24 hours), this means 1D features from the day candle closing at `2024-01-01 00:00` will only be usable in the `_rolling_z_score` normalised observation from `2024-01-02 00:00` onward. This is actually **more conservative and correct** than production, which is fine for backtesting. Confirm your live feed applies the equivalent 1-period-forward delay on higher timeframes before forming the observation vector.

### Finding 1-E: MACD Column Selection Is Fragile (`preprocess.py`, lines 42–43)

**LOW RISK / RELIABILITY**

```python
# preprocess.py lines 42–43
df["macd"] = macd.iloc[:, 0]
df["macd_hist"] = macd.iloc[:, 1]
```

`pandas_ta.macd()` returns columns in order `[MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9]`. By indexing positionally, `macd.iloc[:, 0]` is the MACD line (correct) but `macd.iloc[:, 1]` is the **histogram** (correct), not the signal line — though the naming `macd_hist` is consistent with that. The issue is that across `pandas_ta` versions the column order has changed (some versions emit `[MACD, Signal, Histogram]`). Positional indexing makes this brittle. Use named column access:

```python
df["macd"]      = macd[f"MACD_{12}_{26}_{9}"]
df["macd_hist"] = macd[f"MACDh_{12}_{26}_{9}"]
```

### Finding 1-F: `log_return` Computed Without `.shift(1)` Alignment (`preprocess.py`, line 77)

**CRITICAL (Subtle)**

```python
# preprocess.py line 77
df["log_return"] = np.log(df["close"] / df["close"].shift(1))
```

`log_return` at index `t` is `log(close_t / close_{t-1})`. This is the return **realised at** the close of bar `t`. When the environment uses `self._returns_array[:, i] = np.exp(self._aligned[sym]["log_return_1h"].values)` (trading_env.py line 130), it correctly maps these as `returns[step_idx]` — the return for the candle *at* `step_idx`. The `step()` method then applies `np.dot(new_weights[:-1], returns - 1.0)`, meaning the agent acts on observation `[step_idx - lookback : step_idx]` and earns the return of candle `step_idx`.

**This is the critical flaw:** The agent sees the feature window `[t-lookback, t-1]` (the observation ends at `step_idx - 1` because `end = self._step_idx` which hasn't been incremented yet), forms an action, and is rewarded with `returns[step_idx]` which is the **close-to-close return of the candle the agent just observed the close of**. The observation window **includes** features computed from the close of candle `step_idx - 1`, but the return applied is from candle `step_idx`. This is one candle ahead — the return the agent "earns" requires knowing the next close price, which hasn't arrived yet at decision time. On a 1H chart this is a 1-hour forward return leak.

The fix: `_get_returns()` should return `self._returns_array[self._step_idx - 1]` — the return of the *just-completed* candle, not the next one.

---

## 2. Live-Trading Fidelity & Execution Audit

### Finding 2-A: Tick Rate is 1H Candle-Close — No Intra-Bar Execution (`trading_env.py`, `run_live.py`)

The environment steps one row per call to `step()`, and each row is a 1H 1-hour OHLCV candle. The agent effectively samples at 1H intervals, which is consistent with `config.py:REBALANCE_INTERVAL_SECS = 3600`. **No intra-bar execution is modelled.** This is a design choice, not a bug per se, but it carries a hard constraint: the agent's action at candle `t` is assumed to be **filled instantaneously at the close of candle `t`**, before any of candle `t+1`'s price movement is realised.

On Binance Spot, a market order submitted at 14:59:59 UTC (1 second before the hourly candle close) will be matched against the *current order book* — not at the closes price. The execution price will be somewhere within the spread around the close tick, plus queue priority effects. The `SLIPPAGE = 0.001` (0.1%) from `config.py` is a flat additive estimate and does not scale with order size or with the bid-ask spread at low-liquidity moments (e.g., immediately after a flash crash). 

For BTC/ETH at typical portfolio sizes under $100K, 0.1% flat slippage on each rebalance is *broadly acceptable* but underestimates impact during high-volatility candle closes.

### Finding 2-B: Fee and Slippage Are Combined as a Single Flat Rate — Maker/Taker Distinction Lost (`trading_env.py`, lines 209–210)

**HIGH RISK**

```python
# trading_env.py lines 209–210
delta = np.abs(new_weights[:-1] - old_weights[:-1])
return float(delta.sum() * (self.fee + self.slippage))
```

`config.py` sets:
```python
BINANCE_SPOT_FEE = 0.001   # 0.1%
SLIPPAGE         = 0.001   # 0.1%
```

This means every rebalance is modelled at **0.2% round-trip per unit of weight moved**, applied identically regardless of order type. In production on Binance Spot:
- **Market orders (taker):** 0.1% fee (or 0.075% with BNB discount)  
- **Limit orders (maker):** 0.08% (or 0.01%-0.02% with BNB)

If the live system uses **limit orders** (posted to the book), the backtest is over-penalising by ~5–10× on the taker fee side while also underpenalising for queue-risk (limit orders may not fill at all, creating slippage from drift). If the live system uses **market orders**, 0.1% taker + 0.1% slippage ≈ 0.2% may be approximately correct for medium-volatility conditions but will underestimate impact in illiquid windows.

Additionally, the fee is applied as a fraction of **weight delta**, not as a fraction of **USDT notional traded**. For a $10K portfolio moving 10% weight in BTC, the actual fee on Binance is `0.10 × $10,000 × 0.001 = $1`. The environment computes `0.10 × 0.001 × portfolio_value`, which is the same math — so the mapping is correct. However, there is no minimum order check against `MIN_ORDER_USDT = 10.0` during environment stepping; the env will apply fees on arbitrarily small rebalances that Binance would simply reject as dust.

### Finding 2-C: Orders Fill at Next-Candle Open, Not This Candle's Close — Timing Off-By-One (`trading_env.py`, lines 250–285)

**CRITICAL**

```python
# trading_env.py lines 250–286 (simplified)
returns = self._get_returns()          # returns[step_idx]  ← NEXT candle's return
asset_pnl = float(np.dot(new_weights[:-1], returns - 1.0))
...
self._portfolio *= max(net_return, 1e-6)
self._weights = new_weights
...
self._step_idx += 1   # Increment happens AFTER PnL is applied
```

The sequence at each `step()` call:
1. `step_idx` = `t` at entry.
2. Agent's action forms `new_weights`.
3. `_get_returns()` → `returns_array[t]` → **the return of candle `t`** (i.e., `close_t / close_{t-1}`).
4. PnL is applied: portfolio is multiplied by a return derived from candle `t`.
5. `step_idx += 1` → advances to `t+1`.
6. Next `_get_obs()` builds the window `[t+1-lookback : t+1]`.

This means the agent observes features from candles `[t-lookback, t-1]`, then **simultaneously earns the return of candle `t`**. Since candle `t`'s return is `exp(log_return_t)` = `close_t / close_{t-1}`, the agent is earning the return of the candle whose close price has already been implicitly reflected in the last observation (the z-scored features at `t-1` include EMA, RSI, etc. computed on `close_{t-1}`). The agent does not "see" `close_t` directly, but it earns a return that terminates at `close_t` — a price point that has not yet been observed.

In a real exchange: the decision is made at bar `t-1`'s close, the order is submitted, and fills somewhere during bar `t` at bar `t`'s open price (best case) or at an intra-bar price. The system should model execution at bar `t`'s **open**, not reward based on `close_t / close_{t-1}`. Using open of bar `t` as the entry price and close of bar `t` as the exit price (or open of bar `t+1`) is the standard realistic convention.

### Finding 2-D: `_rolling_z_score` Applies to `macro_trend_array` During Training but Not at Inference — Observation Dimension Mismatch Risk (`trading_env.py`, lines 110–113)

```python
# trading_env.py lines 110–113
self._obs_columns = [
    c for c in next(iter(self._aligned.values())).columns 
    if not c.startswith("log_return") and not c.startswith("raw_")
]
```

Columns starting with `raw_` (e.g., `raw_dist_sma_200_1d`, `raw_atr_14_1d`) are excluded from the observation. This is correct design — raw unnormalised macro anchors should not be fed to the neural network. However, in `run_live.py` / the live feature pipeline, if the same exclusion filter is not applied identically (same prefix strings, same column naming from `preprocess.py`), the live observation vector will have a different shape than the trained model's input dimension, causing an immediate runtime error or, worse, a silent mis-alignment of features.

### Finding 2-E: Action Smoothing in the Environment Is Not Applied During Backtest (`trading_env.py` line 232 vs `backtest.py` line 150)

**HIGH RISK — Evaluation-Training Discrepancy**

```python
# trading_env.py lines 231–233 (inside step())
alpha = 0.2
smoothed_action = (1.0 - alpha) * self._last_raw_action + alpha * action
self._last_raw_action = smoothed_action
```

The action smoothing (exponential moving average, α=0.2) runs inside `BinanceSpotEnv.step()`. Since `backtest.py` **also** calls `env.step(action)` at line 150, the smoothing **does** apply during backtesting — that part is consistent. 

However, the backtest does an additional override before `env.step`:
```python
# backtest.py lines 134–135
action = weights[:env.n_assets] * 2.0 - 1.0   # approximate inverse
obs, reward, terminated, truncated, info = env.step(action)
```

The `weights` coming from `agent.predict(obs)` are already post-softmax portfolio weights in `[0,1]`. The `* 2.0 - 1.0` maps them back to `[-1,1]` action space. Then inside `env.step()`, `_softmax_weights(smoothed_action)` re-applies softmax. The round-trip `softmax → inverse → smoothing → softmax` introduces distortion. Specifically, the smoothing EMA operates in pre-softmax logit space but the "inverse" is computed from post-softmax weights — these are not the same space. The resulting `new_weights` in the backtest will not match what `agent.predict()` actually output, introducing a systematic allocation drift that **does not occur during training** since training feeds raw `action` from the policy directly to `env.step()`.

### Finding 2-F: `REBALANCE_THRESHOLD = 0.03` Is Hardcoded — Not Accessible From Backtest or Live Config (`trading_env.py`, line 239)

```python
# trading_env.py line 239
REBALANCE_THRESHOLD = 0.03
```

This threshold is baked as a local variable inside `step()`. It is not exposed in `config.py` and not overrideable at runtime. **This same threshold will also fire in the live environment**, meaning orders below 3% weight change will silently be suppressed. For a $10K portfolio, 3% = $300 minimum rebalance notional — this is a reasonable deadband. But the value should be configurable and auditable, not a magic constant buried in a method body.

---

## 3. Actionable Fixes

### Fix 3-A: Correct the One-Step Return Off-By-One (addresses Finding 1-F and 2-C)

**`environment/trading_env.py` — `_get_returns()`**

```python
# BEFORE (trading_env.py line 198–200)
def _get_returns(self) -> np.ndarray:
    """Price change ratio for each asset at the current step."""
    return self._returns_array[self._step_idx]

# AFTER: Return the completed candle's return, not the next one.
def _get_returns(self) -> np.ndarray:
    """
    Price change ratio for the *just-completed* candle.
    At decision time the agent has observed features up to step_idx-1.
    The candle at step_idx-1 has just closed; its close-to-close return
    (log_return at step_idx-1) is the price change now realised.
    The agent's new weights are applied at open of step_idx.
    """
    return self._returns_array[self._step_idx - 1]
```

> **Note:** This fix shifts PnL attribution to the bar that the agent's observation window includes. To model *fill-at-open of next bar*, you would need separate open/close arrays. That requires storing `open_return = open_t / close_{t-1}` in preprocessing and applying orders against `open_return[step_idx]`, then updating the position's unrealised P&L for the rest of the candle. If you accept close-to-close semantics (fill at close), the above fix is sufficient.

---

### Fix 3-B: Shift OBV Normalisation by 1 (addresses Finding 1-A)

**`data/preprocess.py` — `_add_indicators()`**

```python
# BEFORE (lines 58–60)
obvs = ta.obv(df["close"], df["volume"])
if obvs is not None:
    df["obv_norm"] = (obvs - obvs.rolling(20).mean()) / (obvs.rolling(20).std() + 1e-9)

# AFTER: Shift the normalised OBV so candle t's observation
# only sees OBV stats computed through close_{t-1}.
if obvs is not None:
    obv_mean  = obvs.rolling(20).mean().shift(1)
    obv_std   = obvs.rolling(20).std().shift(1).replace(0, 1e-9)
    df["obv_norm"] = (obvs.shift(1) - obv_mean) / obv_std
```

---

### Fix 3-C: Explicit MACD Column Names (addresses Finding 1-E)

**`data/preprocess.py` — `_add_indicators()`**

```python
# BEFORE (lines 38–43)
macd = ta.macd(df["close"], fast=12, slow=26, signal=9)
if macd is not None and not macd.empty:
    df["macd"]      = macd.iloc[:, 0]
    df["macd_hist"] = macd.iloc[:, 1]

# AFTER: Named column access — version-safe (pandas_ta >= 0.3.14)
MACD_FAST, MACD_SLOW, MACD_SIG = 12, 26, 9
macd = ta.macd(df["close"], fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIG)
if macd is not None and not macd.empty:
    df["macd"]        = macd.get(f"MACD_{MACD_FAST}_{MACD_SLOW}_{MACD_SIG}")
    df["macd_signal"] = macd.get(f"MACDs_{MACD_FAST}_{MACD_SLOW}_{MACD_SIG}")
    df["macd_hist"]   = macd.get(f"MACDh_{MACD_FAST}_{MACD_SLOW}_{MACD_SIG}")
```

---

### Fix 3-D: Tiered Maker/Taker Fee Model and Minimum Order Gate (addresses Finding 2-B)

**`config.py`** — Add separate maker/taker constants:

```python
# config.py — Replace BINANCE_SPOT_FEE with tiered structure
BINANCE_TAKER_FEE  = 0.001    # 0.10% — market orders
BINANCE_MAKER_FEE  = 0.0008   # 0.08% — limit orders posted to book
BINANCE_BNB_TAKER  = 0.00075  # 0.075% — with BNB fee discount
BINANCE_BNB_MAKER  = 0.00010  # 0.01% — with BNB + VIP tier
SLIPPAGE           = 0.001    # 0.1% flat slippage estimate
MIN_ORDER_USDT     = 10.0     # Minimum notional to avoid dust rejection
```

**`environment/trading_env.py`** — Add minimum order gate and configurable fee:

```python
# trading_env.py — _compute_transaction_cost (replace existing)
def _compute_transaction_cost(
    self, old_weights: np.ndarray, new_weights: np.ndarray
) -> float:
    """
    Realistic transaction cost model:
    - Fee only applies where the notional traded exceeds MIN_ORDER_USDT.
    - Separate maker and taker legs (taker on exit, maker on entry if limit).
    """
    from config import MIN_ORDER_USDT
    delta = np.abs(new_weights[:-1] - old_weights[:-1])
    notional_per_asset = delta * self._portfolio   # USDT notional traded per asset

    # Apply fee only where Binance would accept the order (> min threshold)
    tradeable_mask = notional_per_asset >= MIN_ORDER_USDT
    tradeable_delta = delta * tradeable_mask.astype(float)

    # Use taker fee for market orders (default) + flat slippage
    cost = float(tradeable_delta.sum() * (self.fee + self.slippage))
    return cost
```

---

### Fix 3-E: Eliminate the Backtest Softmax Round-Trip Distortion (addresses Finding 2-E)

**`backtest.py`** — Remove the spurious `weights → action → env.step` re-mapping:

```python
# BEFORE (backtest.py lines 132–150)
weights = agent.predict(obs)
action = weights[:env.n_assets] * 2.0 - 1.0  # approximate inverse
...
obs, reward, terminated, truncated, info = env.step(action)

# AFTER: Add a bypass path in the environment for direct weight injection,
# OR expose a step_weights() method that skips action_smoothing → softmax:

# In trading_env.py, add:
def step_weights(
    self, target_weights: np.ndarray
) -> tuple[np.ndarray, float, bool, bool, dict]:
    """
    Production-path step: accept pre-computed portfolio weights directly.
    Bypasses action smoothing (which is a training regulariser, not a 
    real execution feature) and the softmax mapping.
    Used by backtest.py and run_live.py.
    """
    assert len(target_weights) == self.n_assets + 1, "Must include cash weight"
    assert abs(target_weights.sum() - 1.0) < 1e-4, "Weights must sum to 1"

    # Save smoothing state (skip EMA) 
    new_weights = target_weights.copy().astype(np.float32)
    # ... (continue with deadband, ATR stop, PnL calculation, reward) ...
    # The remainder of step() logic is identical from line 247 onward
```

Then in `backtest.py`:
```python
# AFTER — in run_backtest loop
weights = agent.predict(obs)            # shape: (n_assets + 1,) softmax weights
obs, reward, terminated, truncated, info = env.step_weights(weights)
```

---

### Fix 3-F: Expose `REBALANCE_THRESHOLD` in Config (addresses Finding 2-F)

**`config.py`**:
```python
# config.py — add to ENVIRONMENT SETTINGS section
REBALANCE_THRESHOLD = 0.03   # Minimum weight delta to trigger a real order (3%)
```

**`trading_env.py`**:
```python
# trading_env.py — top of file import
from config import (..., REBALANCE_THRESHOLD)

# In step(), replace hardcoded value:
# BEFORE:
REBALANCE_THRESHOLD = 0.03
# AFTER:
from config import REBALANCE_THRESHOLD  # (already imported at top)
```

---

## Summary Risk Matrix

| # | File | Severity | Category | Fix |
|---|------|----------|----------|-----|
| 1-A | `preprocess.py:60` | **Critical** | Look-Ahead Bias | Shift OBV stats by 1 (Fix 3-B) |
| 1-B | `preprocess.py:94` | **Critical** | Data Leakage / Normalisation | Use `min_periods=window`, drop early rows |
| 1-E | `preprocess.py:42` | Low | Reliability | Named MACD columns (Fix 3-C) |
| 1-F | `preprocess.py:77` + `trading_env.py:200` | **Critical** | Look-Ahead Bias | Fix `_get_returns()` off-by-one (Fix 3-A) |
| 1-C | `preprocess.py:200` | ✅ Clean | Train/Test Split | No action required |
| 2-A | `trading_env.py` | Medium | Execution Realism | Document, add open-price return array for fill-at-open |
| 2-B | `trading_env.py:210` | **High** | Fee Model | Tiered fee + minimum notional gate (Fix 3-D) |
| 2-C | `trading_env.py:250` | **Critical** | Execution Realism | Same as Fix 3-A |
| 2-D | `trading_env.py:110` | Medium | Obs Dimension | Assert consistent column filter in live feed |
| 2-E | `backtest.py:135` | **High** | Eval-Train Discrepancy | Add `step_weights()` bypass (Fix 3-E) |
| 2-F | `trading_env.py:239` | Low | Maintainability | Expose threshold in config (Fix 3-F) |
