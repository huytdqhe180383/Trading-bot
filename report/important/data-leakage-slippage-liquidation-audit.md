# Audit: Data Leakage, Survivorship Bias, Transaction Costs, Slippage, Liquidation

**Date:** 2026-05-24
**Scope:** Full codebase audit of five risk dimensions

---

## 1. Data Leakage

### 1.1 What's Already Fixed ✅

| Fix | File | Description |
|-----|------|-------------|
| Off-by-one returns | `environment/trading_env.py:212` | `_get_returns()` uses `self._step_idx - 1` (completed candle) not `step_idx` (future candle) |
| OBV forward shift | `data/preprocess.py:82` | `obvs.shift(1)` before rolling stats so OBV confirmed through `close_{t-1}` |
| Rolling z-score min_periods | `data/preprocess.py:108` | `min_periods=window` prevents unstable early-window normalization |
| MACD named columns | `data/preprocess.py:42-44` | Uses `get("MACD_12_26_9")` not positional `iloc` |
| Backtest softmax round-trip | `environment/trading_env.py:393` | `step_weights()` bypasses EMA smoothing, eliminating train/backtest allocation drift |
| Higher-TF shift (backtest) | `data/preprocess.py:194` | Higher timeframes shifted by 1 bar before `merge_asof` |

### 1.2 Remaining Gaps — 2 Issues

#### Gap 1: `get_market_regime()` reads 1 bar ahead (minor)
**File:** `environment/trading_env.py:168`
```python
"macro_trend": self._macro_trend_array[self._step_idx]  # ← should be step_idx - 1
```
**Impact:** Only affects `imca` ensemble method (not default). Default `dynamic_weighted` is clean.
**Fix:** Change to `self._macro_trend_array[self._step_idx - 1]`

#### Gap 2: `live_feed.py` missing higher-timeframe shift
**File:** `data/live_feed.py:112-133`
**Problem:** `fetch_feature_state()` calls `_add_indicators()` on raw OHLCV without replicating the `df.shift(1)` that `preprocess.py:194` applies to 4H/1D timeframes.
**Impact:** In live trading, higher-timeframe indicators (4H, 1D) are visible before their bar completes.
**Fix:** Add `df = df.shift(1)` for higher timeframes in `fetch_feature_state()`.

---

## 2. Survivorship Bias

### 2.1 Assessment ✅ (Documented, No Code Change)

The strategy uses only `BTCUSDT` and `ETHUSDT` — the two longest-surviving crypto assets. This is structurally unavoidable for a BTC/ETH spot strategy. Training 2020-2023, test 2024-2026. Both assets existed throughout. The benchmark is equally survivorship-biased (mean of BTC+ETH returns), so relative metrics are internally consistent. Mitigations: `MAX_ASSET_WEIGHT = 0.80`, `MIN_CASH_FLOOR = 0.05`.

**Verdict:** Low priority for the current two-asset scope.

---

## 3. Transaction Costs

### 3.1 What's Working ✅

| Feature | Implementation | File |
|---------|---------------|------|
| Dust trade suppression | `MIN_ORDER_USDT = 10.0` gate | `trading_env.py:233` |
| Two realism profiles | baseline (0.1% + 0.1%) vs live_like (0.12% + 0.18%) | `config.py:207-218` |
| Proportional cost | Cost = notional × weight_delta × (fee + slippage) | `trading_env.py:237` |
| Cost deducted from return | `net_return = gross_return * (1.0 - tc)` | `trading_env.py:467` |

### 3.2 Gaps

| Gap | Severity | Notes |
|-----|----------|-------|
| No maker/taker fee distinction | Low | Uniform fee overestimates costs (conservative). Current live_like 0.12% is a safe overestimate. |
| No volume-tier discounts | Low | Conservative to ignore. |
| Fee + slippage summed additively | Medium | Real slippage is multiplicative with price movement. See §4. |

**Verdict:** Conservative model, acceptable for now.

---

## 4. Slippage — **Highest-Impact Gap** ⚠️

### 4.1 Current Model

```python
# environment/trading_env.py:237
return float(effective_delta.sum() * (self.fee + self.slippage))
```

Slippage is a **flat additive constant** (0.1% baseline, 0.18% live_like) applied uniformly regardless of trade size, volatility, or latency.

### 4.2 Specific Gaps

| Gap | Severity | Description |
|-----|----------|-------------|
| **No volume-dependent slippage** | High | Same 0.18% for $50K trade as $500 trade. |
| **No volatility-dependent slippage** | **High** | ATR/BB-width measured but not fed into cost model. Trailing stops scale with volatility but slippage doesn't — inconsistency. |
| **No latency-dependent slippage** | Medium | live_like delays execution by 1 candle but doesn't model price movement during delay as slippage. |
| **Flat vs. directional** | Medium | Real slippage can be favorable/unfavorable. Current model always charges flat regardless. |

### 4.3 Recommended Fix

Volatility-scaled slippage:
```python
volatility_proxy = abs(returns).mean()  # or atr_z from existing computation
slippage_bps = base_slippage * (1.0 + vol_scalar * volatility_proxy)
```

---

## 5. Liquidation Mechanics

### 5.1 Three Independent Layers

| Layer | Trigger | Action | File |
|-------|---------|--------|------|
| **ATR Trailing Stop** | Per-asset drawdown ≥ 4% + atr_z×1% (capped 1-10%) | Force position to 0, move to cash | `trading_env.py:247-268` |
| **15% Kill Switch** | Portfolio abs_drawdown ≤ -15% | Terminate in train mode; **ignored** in eval/backtest | `trading_env.py:489-492` |
| **Risk Governor** | vol_z ≥ 1.0 OR drawdown ≤ -8% (stress) / ≤ -15% (crisis) | Cash floor 25%/45%, risk-on cap 75%/55% | `risk/risk_constraints.py:94-150` |

### 5.2 Gaps

| Gap | Severity | Description |
|-----|----------|-------------|
| **Trailing stop resets on re-entry** | Medium | High-water mark resets when weight < 1%. Whipsaw risk. |
| **Kill switch only in train mode** | Medium | Backtests run past -15% drawdown. |
| **Risk governor never forces full liquidation** | Low | Crisis keeps 55% at risk. |
| **Layers operate independently** | Medium | Trailing stop and risk governor don't coordinate. |
| **No circuit breaker for single-bar extremes** | Low | Flash crash triggers stop after the fact. |

---

## Summary

| Priority | Issue | Effort |
|----------|-------|--------|
| 🔴 P0 | Volatility-dependent slippage | Medium |
| 🟠 P1 | `get_market_regime()` 1-bar look-ahead | Trivial |
| 🟠 P1 | `live_feed.py` missing higher-TF shift | Small |
| 🟡 P2 | Kill switch in eval mode | Small |
| 🟡 P2 | Trailing stop / risk governor coordination | Medium |
| 🟡 P2 | Trailing stop hysteresis | Small |
| 🟢 P3 | Latency-dependent slippage | Medium |
| 🟢 P3 | Survivorship bias documentation | Trivial |
| 🟢 P3 | Maker/taker fee distinction | Small |
