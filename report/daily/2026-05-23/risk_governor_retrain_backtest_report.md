# Risk Governor Retrain And Backtest Report

Date: 2026-05-23

## Summary

Implemented the RL improvement pass, refreshed OKX BTC/ETH data through the current date, retrained PPO/SAC from scratch, and ran live-like backtests on the newly trained models.

The clean retrain was required because the refreshed processed feature matrix changed the SB3 observation shape from `2523` to `2703`, making old checkpoints incompatible for resume.

## Implemented Changes

- Added a configurable stress risk governor that raises cash and caps risk-on exposure during high-volatility or drawdown regimes.
- Wired the risk governor into both `step()` and `step_weights()` so training and backtest/live execution use the same risk limits.
- Replaced hardcoded environment reward weights with `config.REWARD_WEIGHTS`.
- Added nonzero turnover penalty and a CVaR-style tail-loss reward penalty.
- Added CVaR 95/99 metrics to performance output.
- Made `dynamic_weighted` model scoring more risk-aware by penalizing rolling model drawdown and tail loss, not only recent Sharpe.
- Updated `BACKTEST_END` to `2026-05-23`.
- Added unit tests for the stress risk governor and tail-risk metrics.

## Data Refresh

Processed split after refresh:

| Split | Rows | Start | End | Features |
|---|---:|---|---|---:|
| BTC train | 29,965 | 2020-07-31 11:00 UTC | 2023-12-31 23:00 UTC | 48 |
| BTC test | 20,964 | 2024-01-01 00:00 UTC | 2026-05-23 11:00 UTC | 48 |
| ETH train | 29,965 | 2020-07-31 11:00 UTC | 2023-12-31 23:00 UTC | 48 |
| ETH test | 20,964 | 2024-01-01 00:00 UTC | 2026-05-23 11:00 UTC | 48 |

Commands:

```powershell
.\.venv\Scripts\python.exe -m data.download_historical --exchange okx --end 2026-05-23
.\.venv\Scripts\python.exe -m data.preprocess
```

## Training

Initial resumed training failed safely:

```text
ValueError: Observation spaces do not match: Box(-inf, inf, (2523,), float32) != Box(-inf, inf, (2703,), float32)
```

Baseline archive: `archive/pre_risk_governor_retrain_20260523_182032/`

Clean retrain command:

```powershell
.\.venv\Scripts\python.exe train.py --algo ALL --device auto --seed 42 --validation-fraction 0.2 --skip-backtest
```

Training result:

| Algo | Budget | Fit rows | Validation rows | Best model |
|---|---:|---:|---:|---|
| PPO | 200,000 | 23,972 | 5,993 | `models/PPO/ppo_best.zip` |
| SAC | 50,000 | 23,972 | 5,993 | `models/SAC/sac_best.zip` |

Notes:

- PPO completed at 212,992 timesteps due rollout granularity.
- SAC completed at 50,000 timesteps.
- Training completed at 2026-05-23 18:41:09.
- ROCm version warnings appeared but did not block training.

## Backtest Results

Primary run:

```powershell
.\.venv\Scripts\python.exe backtest.py --pipeline rl_only --realism-profile live_like --method dynamic_weighted
```

Primary result:

| Metric | Value |
|---|---:|
| Total return | 107.06% |
| Annualized return | 35.60% |
| Sharpe | 0.8492 |
| Sortino | 1.1450 |
| Max drawdown | -36.78% |
| CVaR 95 | -0.9151% |
| CVaR 99 | -1.5084% |
| Trades | 14,660 |
| Mean cash weight | 32.05% |
| Mean risk-on weight | 67.95% |
| Risk governor active rate | 79.77% |
| Cost drag | -79.44% |

Previous reference result was about `13.05%` return / `0.1153` Sharpe / `-55.72%` max drawdown. The new pass materially improved return, Sharpe, and drawdown, but cost drag and turnover remain too high.

## Ablation Matrix

Command:

```powershell
.\.venv\Scripts\python.exe backtest.py --run-matrix --realism-profile live_like --method dynamic_weighted
```

| Pipeline | Return | Sharpe | Max DD | Trades | Mean cash | Risk governor active | Cost drag |
|---|---:|---:|---:|---:|---:|---:|---:|
| rl_only | 107.06% | 0.8492 | -36.78% | 14,660 | 32.05% | 79.77% | -79.44% |
| rl_kronos | 107.06% | 0.8492 | -36.78% | 14,660 | 32.05% | 79.77% | -79.44% |
| rl_tradingagents | 107.06% | 0.8492 | -36.78% | 14,660 | 32.05% | 79.77% | -79.44% |
| rl_full | 107.06% | 0.8492 | -36.78% | 14,660 | 32.05% | 79.77% | -79.44% |

Overlay finding:

- Kronos initialized but produced no usable signal because native backend/window OHLCV requirements were unavailable in the processed state windows.
- Ollama TradingAgents attempted provider calls and timed out after 5 retries, then correctly returned unavailable/no signal.
- Because overlays were unavailable, all pipelines matched RL-only behavior. This is expected under the no-heuristic-fallback rule.

## Ensemble Method Comparison

Command:

```powershell
.\.venv\Scripts\python.exe backtest.py --compare-ensemble-methods --realism-profile live_like
```

| Method | Return | Sharpe | Max DD | Trades | Mean cash | Risk governor active | Cost drag |
|---|---:|---:|---:|---:|---:|---:|---:|
| mean | 108.89% | 0.8538 | -36.66% | 14,450 | 31.47% | 78.33% | -79.62% |
| weighted | 108.89% | 0.8538 | -36.66% | 14,450 | 31.47% | 78.33% | -79.62% |
| dynamic_weighted | 107.06% | 0.8492 | -36.78% | 14,660 | 32.05% | 79.77% | -79.44% |
| imca | 90.00% | 0.7540 | -36.91% | 15,336 | 32.68% | 79.88% | -81.26% |
| voting | -97.64% | -5.2230 | -97.65% | 3,127 | 44.38% | 99.31% | -99.38% |

`mean` and `weighted` slightly beat `dynamic_weighted` on this run. `voting` remains unsuitable and should stay excluded from serious evaluation until redesigned.

## Preserved Artifacts

Results snapshot:

- `results/daily/2026-05-23/risk_governor_retrain_backtest/backtest_metrics.csv`
- `results/daily/2026-05-23/risk_governor_retrain_backtest/backtest_matrix_metrics.csv`
- `results/daily/2026-05-23/risk_governor_retrain_backtest/backtest_rl_diagnostics.csv`
- `results/daily/2026-05-23/risk_governor_retrain_backtest/backtest_ensemble_method_comparison.csv`
- `results/daily/2026-05-23/risk_governor_retrain_backtest/backtest_ensemble_method_comparison.png`
- `results/daily/2026-05-23/risk_governor_retrain_backtest/equity_curve.png`
- `results/daily/2026-05-23/risk_governor_retrain_backtest/kpi_target_radar.png`

Logs:

- `report/daily/2026-05-23/risk_governor_retrain/train_20260523_181920_risk_governor_stderr.log`
- `report/daily/2026-05-23/risk_governor_retrain/train_20260523_182039_risk_governor_clean_stderr.log`
- `report/daily/2026-05-23/risk_governor_retrain/train_20260523_182039_risk_governor_clean_stdout.log`

## Remaining Issues

- Cost drag is still structurally high at about `-79%`; the system improved despite this, not because this is solved.
- Trade count remains high at roughly 14.5k to 14.7k trades over the test window.
- Drawdown improved sharply but still violates the `-30%` target.
- Ollama TradingAgents timeout makes the overlay no-op in matrix backtests; this is safe, but not useful yet.
- Kronos needs raw OHLCV-compatible windows or an adapter-side reconstruction path before it can contribute.

## Recommended Next Pass

1. Add a direct turnover budget in `step_weights()` or ensemble target smoothing, not just a reward penalty.
2. Tune risk governor thresholds to target max drawdown below `-30%` without crushing upside.
3. Keep `mean` or `weighted` as the current serious evaluation default until `dynamic_weighted` demonstrates a durable edge again.
4. Fix TradingAgents/Ollama latency by reducing prompt/context size or shortening the backtest cadence.
5. Feed Kronos raw OHLCV windows instead of processed feature windows.
