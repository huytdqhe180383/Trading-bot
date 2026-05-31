# Live Unrealized PnL Labeling And Backtest Correction

## Summary

Two follow-ups were completed:

- corrected the earlier backtest reference by re-checking
  `results/daily/2026-05-30/`
- changed live/UI PnL wording to explicitly mean unrealized mark-to-market PnL

## Corrected Backtest Record

`results/daily/2026-05-30/` contains several `rl_only + live_like + dynamic_weighted`
backtests on `models/live_baseline` with `initial_capital = 100.0`.

Headline sessions:

- session `1`: `163.65%`
- session `2`: `204.91%`
- session `3`: `167.48%`
- session `4`: `163.81%`
- session `5`: `165.30%`

Important detail:

- session `2` already used the promoted anti-churn thresholds:
  - `rebalance_threshold_normal = 0.03`
  - `rebalance_threshold_stress = 0.05`
  - `rebalance_threshold_crisis = 0.08`
  - `material_trade_threshold = 0.05`
  - `min_hold_bars = 4`
- session `5` used a slightly more permissive profile:
  - `rebalance_threshold_normal = 0.02`
  - `rebalance_threshold_stress = 0.04`
  - `rebalance_threshold_crisis = 0.07`
  - `material_trade_threshold = 0.04`

Conclusion:

- the stronger `204.91%` result is real
- it is not explained by the live bot using the wrong model directory
- the current live quietness is more likely a live-window / requested-delta issue
  than a deployment mismatch

## Live/UI Labeling Change

Updated behavior:

- live session rows now write:
  - `unrealized_pnl_usd`
  - `unrealized_pnl_pct`
- legacy `pnl_usd` / `pnl_pct` remain as compatibility aliases
- UI dashboard and reports now say `Unrealized PnL`
- live process log line now says `Session Unrealized PnL`

Files changed:

- `scripts/run_live.py`
- `scripts/live_daily_report.py`
- `ui/templates/dashboard.html`
- `ui/templates/reports.html`

## Verification

- `python -m unittest tests.test_live_daily_report tests.test_ui_services tests.test_ui_app tests.test_run_live_safety`
- `python -m unittest discover -s tests`

Result:

- `111` tests passed in the full suite
