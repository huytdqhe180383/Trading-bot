# Phase 0 Integrity Hotfix Baseline

## Scope

Implemented the mandatory audit gate before retraining:

- Macro trend access in environment regime/reward now uses the completed bar (`step_idx - 1`).
- Live higher-timeframe feature build shifts non-base timeframe OHLCV by one bar before indicator generation.
- Volatility-scaled slippage, eval kill switch, and step turnover-cap controls are available but default to backward-compatible behavior.
- Backtest diagnostics now preserve effective slippage and turnover-cap fields per step.

## Verification

- `python -m unittest tests.test_audit_hotfixes`: passed, 5 tests.
- `python -m unittest discover -s tests`: passed, 50 tests.

## Clean Baseline

Current best checkpoints were restored from `results/important/model_backups/2026-05-24_107pct_baseline/` before the backtest.

Backtest command:

```powershell
.\.venv\Scripts\python.exe backtest.py --pipeline rl_only --realism-profile live_like --method dynamic_weighted
```

Output session: `results/daily/2026-05-25/1/`

| Metric | Value |
|---|---:|
| Total return | 107.0577% |
| Sharpe | 0.8492 |
| Sortino | 1.1450 |
| Calmar | 0.9680 |
| Max drawdown | -36.7789% |
| Recovery factor | 2.9108 |
| Profit factor | 1.0335 |
| Trades | 14660 |

## Interpretation

The Phase 0 clean baseline matches the protected 107% model result after the leakage/realism hotfixes with backward-compatible realism defaults. This is the gate baseline for Phase 1 and Phase 2 promotion comparisons.
