# Corrected Clock RL Training And Evaluation

Date: 2026-07-21

## Outcome

Implemented the first reliability-critical slice from the RL/LLM evidence plan: fixed the environment clock so a new action earns the next unseen candle return, added a regression test for that invariant, trained fresh PPO/SAC challengers under the corrected clock, and evaluated them with a live-like `rl_only` backtest.

Decision: do not promote this model as a reliable LLM-agent source yet. The corrected challenger is directionally useful as a risk-contained candidate, but its statistical evidence is too thin and its validation/backtest performance is modest.

## Code Changes

- `environment/trading_env.py`: `_get_returns()` now returns `returns_array[step_idx]`, matching the causal contract where the observation window ends at `step_idx - 1` and the new action earns the next close-to-close return.
- `tests/test_audit_hotfixes.py`: added a direct clock regression test and updated kill-switch/trailing-stop tests to inject returns at the next unseen candle.
- `train.py`: added `--models-dir` plumbing for train, resume, checkpoint, and post-training backtest paths.
- `tests/test_train_hygiene.py`: verifies the post-training backtest command passes the exact model directory.
- `backtest.py`: added a circular block-bootstrap statistical report for normal backtest runs, including strategy confidence intervals and probability of improvement versus cash, BTC buy-and-hold, ETH buy-and-hold, and equal-weight rebalanced baselines.
- `tests/test_backtest_session_outputs.py`: verifies bootstrap interval generation, baseline improvement probabilities, tiny-series handling, and JSON artifact writing.
- `tradingbot/analyst/rl_evidence.py` and `scripts/build_rl_evidence.py`: added optional statistical-report ingestion so analyst LLM envelopes can expose safe uncertainty summaries while remaining fail-closed.
- `tests/test_rl_evidence.py`: verifies the envelope includes bootstrap intervals and probability-of-improvement fields without exposing executable trading instructions.

## Verification

Focused tests passed:

```text
python -m pytest tests\test_audit_hotfixes.py tests\test_train_hygiene.py tests\test_backtest_session_outputs.py -q
32 passed, 1 warning
```

After adding the RL evidence envelope, the repository-owned test suite passed:

```text
python -m pytest tests -q
195 passed, 1 warning, 17 subtests passed
```

The warning came from `pandas_ta`/Pandas compatibility and did not affect the checked invariants.

An unrestricted `pytest -q` still collects `external/Kronos` tests and a binary `test_out.txt` file; that collection path is not currently usable in this workspace without external Kronos dependencies and test discovery cleanup.

## Training Run

Run directory:

- `../../../results/daily/2026-07-21/corrected_clock_model_1/`

Command:

```text
train.py --algo ALL --timesteps 50000 --device cpu --seed 42 --validation-fraction 0.2 --models-dir "K:\BTC-ETH Trading\results\daily\2026-07-21\corrected_clock_model_1\models" --skip-backtest
```

Notes:

- Training used CPU because the repo `.venv` points at a missing Python install. Evaluation used the runnable Anaconda `trading_bot` environment after aligning NumPy to 2.x for checkpoint compatibility.
- PPO requested 50k steps but SB3 rollout sizing completed at 65,536 timesteps.
- Validation episodes still show `+/- 0.00`, confirming the existing evaluation callback repeats the same deterministic path. Treat these as smoke validation only, not statistical promotion evidence.

Validation trace:

| Model | Checkpoint evals | Selected checkpoint |
| --- | ---: | --- |
| PPO | 20k `-415.59`, 40k `-415.45`, 60k `-420.42` | `models/PPO/ppo_best.zip` |
| SAC | 10k `-422.87`, 20k `-401.59`, 30k `-409.51`, 40k `-428.17`, 50k `-423.80` | `models/SAC/sac_best.zip` from 20k |

## Backtest Evaluation

Backtest output directory:

- `../../../results/daily/2026-07-21/2/`

Command:

```text
backtest.py --pipeline rl_only --realism-profile live_like --method dynamic_weighted --model-dir "K:\BTC-ETH Trading\results\daily\2026-07-21\corrected_clock_model_1\models" --autosave-profit-threshold 999999
```

Key metrics:

| Metric | Value |
| --- | ---: |
| Total return | 4.02% |
| Annualized return | 1.64% |
| Sharpe | 0.2759 |
| Sortino | 0.0413 |
| Max drawdown | -6.67% |
| Profit factor | 1.09 |
| Total trades | 37 |
| Time in market | 0.735% |

Simple same-window baselines, compounded from processed `log_return_1h` after the lookback warmup:

| Baseline | Total return | Sharpe | Max drawdown |
| --- | ---: | ---: | ---: |
| Cash | 0.00% | 0.0000 | 0.00% |
| BTC buy-and-hold | 40.99% | 0.2944 | -50.65% |
| ETH buy-and-hold | -25.52% | -0.1803 | -65.28% |
| 50/50 hourly rebalanced before costs | 7.43% | 0.0544 | -56.91% |

Same-path circular block-bootstrap uncertainty artifact:

| Bootstrap diagnostic | Value |
| --- | ---: |
| Strategy total-return 95% interval | -6.97% to 25.30% |
| Strategy Sharpe 95% interval | -0.7905 to 1.1010 |
| Strategy max-drawdown 95% interval | -14.12% to 0.00% |
| Probability of beating cash on total return | 55.8% |
| Probability of beating BTC buy-and-hold on total return | 30.8% |
| Probability of beating ETH buy-and-hold on total return | 63.2% |
| Probability of beating 50/50 hourly rebalanced on total return | 48.0% |

Interpretation:

- The challenger dramatically reduces drawdown versus raw crypto exposure.
- It trails the simple 50/50 total return and Sharpe, but with much lower drawdown.
- It trails BTC buy-and-hold return and Sharpe, while using far less market exposure.
- The final episode state is 100% cash after risk exit/reentry lock, so the apparent stability comes partly from governance rather than pure alpha.
- The bootstrap report is useful as a same-path uncertainty check, but it is not promotion evidence by itself; the total-return interval crosses zero and the model is not more likely than not to beat the simple 50/50 baseline on total return.

## Reliability Status

Not agent-trustworthy yet. This run satisfies the first corrected-clock training/evaluation milestone, but not the broader reliability plan.

Implemented after the backtest:

- added a typed, non-executable RL evidence envelope for analyst LLM context;
- integrated it into analyst prompts with explicit `ABSTAIN` handling;
- added a generator that converts backtest metrics into fail-closed evidence JSON;
- generated today's envelope at `../../../results/daily/2026-07-21/corrected_clock_model_1/rl_evidence.json`.
- added automatic backtest reliability artifacts for simple baselines and reproducibility provenance;
- added an append-only daily trial registry for backtest comparisons;
- added a partial statistical uncertainty artifact with circular block-bootstrap intervals and baseline probability-of-improvement estimates;
- generated the current run's `../../../results/daily/2026-07-21/2/backtest_baselines.csv`, `../../../results/daily/2026-07-21/2/backtest_provenance.json`, and `../../../results/daily/2026-07-21/backtest_trial_registry.csv` without rerunning the model.
- backfilled `../../../results/daily/2026-07-21/2/backtest_statistical_report.json` for the corrected-clock evaluation episode.
- regenerated `../../../results/daily/2026-07-21/corrected_clock_model_1/rl_evidence.json` with the bootstrap uncertainty summary included. It still reports `ABSTAIN`.

Today's envelope status is `ABSTAIN`, with reasons: missing promotion status, promotion expiry, full causal-integrity gate, statistical gates, calibration gate, and prospective shadow gate.

Remaining gates before LLM agents should cite or act on RL output:

- randomized or rolling validation windows instead of duplicate deterministic eval episodes;
- multi-seed training and variance reporting;
- purged/embargoed walk-forward evaluation;
- DSR/PSR/PBO style overfit diagnostics and cost/slippage sensitivity beyond the same-path bootstrap artifact;
- an explicit typed evidence envelope for LLM agents, including horizon, calibration, confidence, uncertainty, drawdown state, and "do not act" flags;
- quarantine of pre-fix leaked checkpoints from any agent-facing source.

## Artifacts

- Training stdout: `../../../results/daily/2026-07-21/corrected_clock_model_1/training_stdout_2.log`
- Training stderr: `../../../results/daily/2026-07-21/corrected_clock_model_1/training_stderr_2.log`
- Model folder: `../../../results/daily/2026-07-21/corrected_clock_model_1/models/`
- Backtest metrics: `../../../results/daily/2026-07-21/2/backtest_metrics.csv`
- Backtest baselines: `../../../results/daily/2026-07-21/2/backtest_baselines.csv`
- Backtest provenance: `../../../results/daily/2026-07-21/2/backtest_provenance.json`
- Backtest statistical report: `../../../results/daily/2026-07-21/2/backtest_statistical_report.json`
- Trial registry: `../../../results/daily/2026-07-21/backtest_trial_registry.csv`
- Episode parquet: `../../../results/daily/2026-07-21/2/backtest_episode_rl_only_live_like_dynamic_weighted.parquet`
- Trade decisions: `../../../results/daily/2026-07-21/2/trade_decisions_rl_only_live_like_dynamic_weighted.csv`
- Equity curve: `../../../results/daily/2026-07-21/2/equity_curve.png`
- KPI radar: `../../../results/daily/2026-07-21/2/kpi_target_radar.png`
- RL evidence envelope: `../../../results/daily/2026-07-21/corrected_clock_model_1/rl_evidence.json`
