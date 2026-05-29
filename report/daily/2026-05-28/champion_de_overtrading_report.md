# Champion De-Overtrading Report

## Summary

This pass kept the preserved champion checkpoint as the trading brain and applied only execution-layer anti-churn controls in backtest.

Result: the execution-only pass solved the overtrading problem well enough that retraining is **not needed yet**.

Best variant:
- Session: `results/daily/2026-05-28/13/`
- Controls: adaptive threshold + cooldown + reversal hysteresis + delayed position-reset reset
- Performance: `159.47%` total return, `1.0911` Sharpe, `-31.20%` max drawdown, `1,560` trades
- Autosaved snapshot: `models/best/2026-05-28/5/`

Reference baseline from the preserved champion snapshot:
- Session: `results/daily/2026-05-28/9/`
- Performance: `107.34%` total return, `0.8507` Sharpe, `-36.70%` max drawdown, `14,652` trades

## What Changed

Implemented in code:
- Regime-aware rebalance thresholds
- Minimum-hold / cooldown gating
- Reversal hysteresis for weak flip-flops
- Delayed high-water reset after tiny de-risk moves
- Richer execution diagnostics in backtest trade logs
- Trade-diagnostics summary CSV outputs per run

Files touched in this pass:
- `config.py`
- `environment/trading_env.py`
- `backtest.py`
- `tests/test_audit_hotfixes.py`
- `tests/test_backtest_session_outputs.py`

## Variant Results

See full comparison CSV:
- [champion_de_overtrading_variant_comparison.csv](../../../results/daily/2026-05-28/champion_de_overtrading_variant_comparison.csv)

Headline comparison:

| Variant | Session | Return | Sharpe | Max DD | Trades |
|---|---:|---:|---:|---:|---:|
| baseline | 9 | 107.34% | 0.8507 | -36.70% | 14,652 |
| adaptive_threshold | 10 | 157.66% | 1.0719 | -33.77% | 1,685 |
| cooldown_only | 11 | 152.57% | 1.0572 | -32.88% | 1,753 |
| threshold_plus_cooldown | 12 | 152.17% | 1.0581 | -32.98% | 1,609 |
| threshold_cooldown_stop_hysteresis | 13 | 159.47% | 1.0911 | -31.20% | 1,560 |

## Why The Best Variant Won

The strongest variant combined four effects well:
- stress/crisis regimes required larger allocation changes before rebalancing
- a `4`-bar hold window blocked immediate whipsaw reversals
- reversal hysteresis filtered weak direction flips after recent material trades
- delayed position-reset logic reduced churn around tiny residual holdings

Best-variant diagnostics from session `13`:
- change-rate fell from `83.71%` to `7.45%`
- mean turnover fell from `0.02524` to `0.02074`
- deadband blocks: `4,402`
- cooldown blocks: `465`
- hysteresis blocks: `1,255`
- trailing-stop liquidations stayed stable: baseline `498`, best variant `499`

Interpretation:
- We reduced discretionary rebalancing dramatically without disabling the hard risk exits.
- The trailing stop remained active, so the improvement did not come from ignoring downside risk.
- The largest gain came from suppressing low-conviction target churn during stress and crisis states.

## Monthly Behavior Check

Quick monthly comparison against the baseline shows the promoted variant was not uniformly better every month.
- Best variant underperformed baseline in `11` of `29` months.
- Despite that, the cumulative result improved materially because the anti-churn controls captured much better net behavior during noisy/stress periods.

This means the result is not a pure “up every month” upgrade, but it is still strong enough to promote because return, Sharpe, drawdown, and trade count all improved together.

## Promotion Decision

Promote session `13` as the current best execution profile for the preserved champion checkpoint.

Promoted settings:
- `REBALANCE_THRESHOLD_NORMAL=0.03`
- `REBALANCE_THRESHOLD_STRESS=0.05`
- `REBALANCE_THRESHOLD_CRISIS=0.08`
- `MIN_HOLD_BARS=4`
- `MATERIAL_TRADE_THRESHOLD=0.05`
- `REVERSAL_HYSTERESIS_MULT=1.5`
- `POSITION_RESET_WEIGHT_THRESHOLD=0.05`
- `POSITION_RESET_PERSIST_BARS=2`

## Verification

- `python -m unittest discover -s tests`
- Result: `70` tests passed

## Notes

- This pass validated the controls in backtest only.
- The live runner has not yet been refactored onto the same shared execution controller, so apply these settings to live only after that parity pass is done.
