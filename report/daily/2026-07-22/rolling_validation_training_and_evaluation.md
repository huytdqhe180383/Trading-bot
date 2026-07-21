# Rolling Validation RL Training And Evaluation

Date: 2026-07-22

## Outcome

Implemented rolling-window validation for RL training, trained a fresh PPO/SAC challenger with that validation path, and evaluated it with the live-like `rl_only` backtest.

Decision: do not promote this challenger. The validation procedure is materially better because it no longer repeats one deterministic validation path, but the resulting model underperformed the earlier corrected-clock challenger on the out-of-sample live-like backtest.

## Code Change

- `train.py`: replaced the single deterministic `EvalCallback` path with a rolling validation callback that evaluates distinct chronological validation windows and saves the best checkpoint by mean reward across windows.
- `train.py`: added `--validation-windows` with default `5`.
- `tests/test_train_hygiene.py`: verifies rolling windows are distinct, chronological, and fall back safely when data is too short.

The validation-code commit used before training/backtest:

```text
2b314a4 Add rolling-window RL validation
```

## Verification

Repository-owned tests passed before training:

```text
python -m pytest tests -q
198 passed, 1 warning, 17 subtests passed
```

The warning came from `pandas_ta`/Pandas compatibility and did not affect the checked invariants.

## Training Run

Model run directory:

- `../../../results/daily/2026-07-21/rolling_validation_model_1/`

Command:

```text
train.py --algo ALL --timesteps 50000 --device cpu --seed 43 --validation-fraction 0.2 --validation-windows 5 --models-dir "K:\BTC-ETH Trading\results\daily\2026-07-21\rolling_validation_model_1\models" --skip-backtest
```

The rolling validation split used five distinct windows from `2023-04-26 07:00:00+00:00` through `2023-12-31 23:00:00+00:00`, with 1,198-1,199 rows per window.

Validation trace:

| Model | Rolling validation evals | Selected checkpoint |
| --- | ---: | --- |
| PPO | 20k `-88.09 +/- 19.00`, 40k `-88.44 +/- 18.73`, 60k `-88.46 +/- 17.66` | `models/PPO/ppo_best.zip` from 20k |
| SAC | 10k `-88.39 +/- 19.29`, 20k `-81.45 +/- 24.06`, 30k `-91.49 +/- 19.04`, 40k `-93.44 +/- 19.60`, 50k `-95.81 +/- 20.56` | `models/SAC/sac_best.zip` from 20k |

Important lesson: the old `+/- 0.00` validation symptom is fixed. The new values show real cross-window dispersion, so checkpoint selection is less likely to overfit to a duplicated validation episode.

## Backtest Evaluation

Backtest output directory:

- `../../../results/daily/2026-07-22/1/`

The backtest session landed under `2026-07-22` because local wall time crossed midnight during the run.

Command:

```text
backtest.py --pipeline rl_only --realism-profile live_like --method dynamic_weighted --model-dir "K:\BTC-ETH Trading\results\daily\2026-07-21\rolling_validation_model_1\models" --autosave-profit-threshold 999999
```

Key metrics:

| Metric | Value |
| --- | ---: |
| Total return | -5.92% |
| Annualized return | -2.49% |
| Sharpe | -1.0027 |
| Sortino | -0.0985 |
| Max drawdown | -7.36% |
| Profit factor | 0.6890 |
| Total trades | 22 |
| Time in market | 0.457% |

Same-window simple baselines:

| Baseline | Total return | Sharpe | Max drawdown |
| --- | ---: | ---: | ---: |
| Cash | 0.00% | 0.0000 | 0.00% |
| BTC buy-and-hold | 40.99% | 0.2944 | -50.65% |
| ETH buy-and-hold | -25.52% | -0.1803 | -65.28% |
| 50/50 hourly rebalanced before costs | 7.43% | 0.0544 | -56.91% |

Same-path circular block-bootstrap diagnostics:

| Bootstrap diagnostic | Value |
| --- | ---: |
| Strategy total-return 95% interval | -16.85% to 0.03% |
| Strategy Sharpe 95% interval | -1.8219 to 0.0102 |
| Strategy max-drawdown 95% interval | -18.02% to 0.00% |
| Probability of beating cash on total return | 3.2% |
| Probability of beating BTC buy-and-hold on total return | 25.8% |
| Probability of beating 50/50 hourly rebalanced on total return | 43.2% |

Interpretation:

- Rolling validation fixed a reliability measurement problem, but it did not produce a better deployable policy in this run.
- The challenger lost money on the live-like out-of-sample backtest and has strongly negative Sharpe.
- The bootstrap interval is almost entirely negative and the probability of beating cash is only 3.2%.
- The model still reduces drawdown versus raw crypto exposure, but mostly by remaining nearly all cash; that is not enough to make it useful as an LLM-agent signal.

## Reliability Status

The regenerated RL evidence envelope reports `ABSTAIN`.

Reasons:

- promotion status missing;
- promotion expiry missing;
- full causal-integrity gate missing;
- statistical gates missing;
- calibration gate missing;
- prospective shadow gate missing.

This challenger should not be exposed as an agent-trustworthy RL opinion. It is useful as evidence that rolling validation has been implemented and as a negative training result to guide the next improvement cycle.

Recommended next slice:

- keep rolling validation as the default;
- run a reward/behavior diagnosis comparing action exposure, risk-governor state, and cash lock behavior between the corrected-clock positive-return challenger and this rolling-validation challenger;
- add a small multi-seed experiment runner so one seed cannot dominate conclusions;
- only then spend more budget on longer training.

## Artifacts

- Training stdout: `../../../results/daily/2026-07-21/rolling_validation_model_1/training_stdout_2.log`
- Training stderr: `../../../results/daily/2026-07-21/rolling_validation_model_1/training_stderr_2.log`
- Model folder: `../../../results/daily/2026-07-21/rolling_validation_model_1/models/`
- PPO rolling validation metrics: `../../../results/daily/2026-07-21/rolling_validation_model_1/ppo_rolling_validation_metrics.csv`
- SAC rolling validation metrics: `../../../results/daily/2026-07-21/rolling_validation_model_1/sac_rolling_validation_metrics.csv`
- Backtest metrics: `../../../results/daily/2026-07-22/1/backtest_metrics.csv`
- Backtest baselines: `../../../results/daily/2026-07-22/1/backtest_baselines.csv`
- Backtest provenance: `../../../results/daily/2026-07-22/1/backtest_provenance.json`
- Backtest statistical report: `../../../results/daily/2026-07-22/1/backtest_statistical_report.json`
- Trial registry: `../../../results/daily/2026-07-22/backtest_trial_registry.csv`
- Episode parquet: `../../../results/daily/2026-07-22/1/backtest_episode_rl_only_live_like_dynamic_weighted.parquet`
- Trade decisions: `../../../results/daily/2026-07-22/1/trade_decisions_rl_only_live_like_dynamic_weighted.csv`
- Equity curve: `../../../results/daily/2026-07-22/1/equity_curve.png`
- KPI radar: `../../../results/daily/2026-07-22/1/kpi_target_radar.png`
- RL evidence envelope: `../../../results/daily/2026-07-21/rolling_validation_model_1/rl_evidence.json`
