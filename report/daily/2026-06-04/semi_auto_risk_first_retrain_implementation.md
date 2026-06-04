# Semi-Auto Risk-First Retrain Implementation

## Summary

Implemented the risk-first semi-auto foundation requested after the June BTC plunge:

- refreshed OKX BTC/ETH 1h, 4h, and 1d raw data through `2026-06-04`
- regenerated processed train/test datasets; test data now reaches `2026-06-04 16:00 UTC`
- added named backtest replay window `--backtest-window june_plunge` for `2026-06-03` through `2026-06-04`
- added hard risk exits in both live and backtest execution paths
- added semi-auto recommendation semantics for live entries/re-entries
- added trade-level metrics and risk-first promotion gates to the KPI experiment runner

## Risk-First Behavior

Hard exits now apply before normal deadband/cooldown blocking:

- session drawdown `<= -6%`: cap risk-on exposure at `35%`
- session drawdown `<= -9%` or BTC 24h return `<= -8%`: cap risk-on exposure at `15%`
- session drawdown `<= -12%`: cap risk-on exposure at `5%`

Live mode now uses semi-auto entry approval by default:

- entries and re-entries become recommendations
- reductions and hard exits can execute automatically
- hard exits lock re-entry until human approval

UI/report payloads now label zero-order rows as `no_order` and expose `position_state` separately, so passive risk-on exposure is not hidden behind a generic hold label.

## Baseline Replay Results

Commands run:

```powershell
python -m data.download_historical --exchange okx --end 2026-06-04 --intervals 1h 4h 1d
python -m data.preprocess
python backtest.py --pipeline rl_only --realism-profile live_like --method dynamic_weighted --backtest-window june_plunge --initial-capital 100 --position-cap-mode smooth_nav --trade-profile mild
python backtest.py --pipeline rl_only --realism-profile live_like --method dynamic_weighted --initial-capital 100 --position-cap-mode smooth_nav --trade-profile mild
```

Results:

| Run | Result Dir | Return | Max DD | Sharpe | Trade Win Rate | Notes |
|---|---|---:|---:|---:|---:|---|
| June plunge replay | [results/daily/2026-06-04/1](../../../results/daily/2026-06-04/1/) | `-0.37%` | `-1.97%` | `-5.7542` | `0.00%` | Safety layer contained drawdown but did not produce a profitable trade. |
| Refreshed full test | [results/daily/2026-06-04/2](../../../results/daily/2026-06-04/2/) | `1.27%` | `-6.35%` | `0.1116` | `100.00%` | Hard exits made the baseline very conservative and kept it mostly in cash after early risk events. |

## Promotion Gates

The KPI experiment runner now ranks candidates by risk-first metrics:

- trade win rate
- trade profit factor
- Sortino
- Calmar
- Sharpe
- max drawdown
- total return only as final tie-breaker

Promotion fails closed unless all gates pass:

- trade win rate `>= 60%`
- trade profit factor `>= 1.25`
- Sharpe `>= 1.5`
- Sortino `>= 1.8`
- Calmar `>= 2.0`
- max drawdown `>= -15%`
- June plunge max drawdown `>= -6%`

The current baseline is not promoted as an improved model. It is safer during the replay, but full-test risk-adjusted performance is too weak. Use the updated experiment runner for candidate retraining and keep current model promotion blocked until a candidate clears the gates.

## Verification

Focused tests and dry-runs were executed:

```powershell
python -m unittest tests.test_risk_first_semiauto tests.test_ui_services tests.test_performance_tail_metrics -v
python -m unittest tests.test_kpi_experiment_runner -v
python -m unittest tests.test_backtest_session_outputs -v
python scripts\run_kpi_improvement_experiment.py --phase phase2-quick --dry-run --methods dynamic_weighted --seeds 42 --poll-seconds 1 --command-timeout-minutes 1
```

No secrets, credentials, virtual environments, or external source clones were added to report/result folders.
