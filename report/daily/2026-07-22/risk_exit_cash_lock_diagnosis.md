# Risk-Exit Cash-Lock Diagnosis

Date: 2026-07-22

## Outcome

Diagnosed and fixed a stale hard-risk-exit state bug that made recent RL backtests mostly evaluate a permanent cash lock instead of the trained policy.

Decision: the rolling-validation challenger is now materially more promising under the corrected risk-state semantics, but it is still not promoted as an LLM-agent-trustworthy source. The backtest period is already research history, the max drawdown is high, and statistical/promotion gates remain incomplete.

## Diagnosis

The corrected-clock and rolling-validation challengers were both proposing high risk-on targets, but the execution layer kept realized exposure near zero after an early drawdown exit.

Pre-fix behavior comparison:

| Run | Return | Sharpe | Mean realized risk-on | Mean target risk-on | Risk-exit rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| Corrected-clock challenger | 4.02% | 0.2759 | 1.05% | 93.35% | 98.80% |
| Rolling-validation challenger | -5.92% | -1.0027 | 0.37% | 90.80% | 99.81% |

Root cause:

- `SemiAutoRiskController` treated hard drawdown exits as level-triggered rules.
- Once session drawdown crossed `-6%`, the controller capped risk and locked re-entry.
- Because the portfolio was then nearly all cash, NAV could not recover above the drawdown threshold.
- The same stale `session_drawdown<=-6%` condition fired every subsequent bar, even when backtest execution simulated human approval.

Correct hypothesis: hard exits need state/hysteresis. The first drawdown exit should fire, but the same stale drawdown level should not keep re-firing forever; a materially worse drawdown or a recovered-and-recrossed threshold should be required.

## Fix

Changed `risk/semi_auto.py` so the risk controller remembers the last drawdown-triggered exit tier/value and only re-triggers drawdown exits after:

- a higher-severity tier is reached;
- drawdown worsens by the configured hysteresis buffer;
- or drawdown recovers enough to reset the exit memory and later crosses again.

Hard exits are still enforced. The fix prevents repeated firing from one stale drawdown state.

Regression coverage:

- `tests/test_risk_first_semiauto.py`: verifies stale warning drawdown does not repeatedly block approved re-entry, while materially worse drawdown still re-triggers the warning exit.
- `tests/test_risk_first_semiauto.py`: verifies `SpotPortfolioEnv.step_weights()` can re-enter after a stale warning drawdown once unrelated execution cooldown is removed from the test.

Reusable diagnosis tooling:

- `tradingbot/reports/rl_behavior.py`
- `scripts/diagnose_rl_behavior.py`
- `tests/test_rl_behavior_report.py`

## Verification

Focused tests first failed on the stale-exit behavior, then passed after the fix.

Full repository-owned tests passed:

```text
python -m pytest tests -q
202 passed, 1 warning, 17 subtests passed
```

The warning came from `pandas_ta`/Pandas compatibility and did not affect the checked invariants.

The code/tooling commit used before the post-fix backtest:

```text
b3d04f8 Fix stale risk-exit cash lock
```

## Post-Fix Backtest

Model evaluated:

- `../../../results/daily/2026-07-21/rolling_validation_model_1/models/`

Backtest output directory:

- `../../../results/daily/2026-07-22/2/`

Command:

```text
backtest.py --pipeline rl_only --realism-profile live_like --method dynamic_weighted --model-dir "K:\BTC-ETH Trading\results\daily\2026-07-21\rolling_validation_model_1\models" --autosave-profit-threshold 999999
```

Key metrics:

| Metric | Value |
| --- | ---: |
| Total return | 178.95% |
| Annualized return | 52.71% |
| Sharpe | 1.1658 |
| Sortino | 1.6333 |
| Max drawdown | -31.90% |
| Profit factor | 1.0438 |
| Total trades | 2,392 |
| Trade count | 56 |
| Trade profit factor | 2.4039 |

Post-fix behavior comparison for the rolling-validation challenger:

| Run | Return | Sharpe | Max DD | Mean realized risk-on | Mean target risk-on | Risk-exit rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Before fix | -5.92% | -1.0027 | -7.36% | 0.37% | 90.80% | 99.81% |
| After fix | 178.95% | 1.1658 | -31.90% | 71.02% | 90.81% | 0.50% |

Same-path circular block-bootstrap diagnostics:

| Bootstrap diagnostic | Value |
| --- | ---: |
| Strategy total-return 95% interval | -9.07% to 811.16% |
| Strategy Sharpe 95% interval | -0.1060 to 2.5182 |
| Strategy max-drawdown 95% interval | -55.01% to -20.48% |
| Probability of beating cash on total return | 96.6% |
| Probability of beating BTC buy-and-hold on total return | 97.0% |
| Probability of beating 50/50 hourly rebalanced on total return | 99.4% |

Interpretation:

- The previous negative rolling-validation result was not a valid policy-performance read; it was dominated by a stale execution-state lock.
- After the fix, the model actually trades throughout the test and beats simple baselines on this research backtest.
- Drawdown is still too high for promotion, especially with a `-55.01%` lower bootstrap drawdown bound.
- The total-return interval is wide and crosses below zero, which reinforces that this is still research evidence, not deployment evidence.

## Reliability Status

The post-fix evidence envelope is still `ABSTAIN`:

- `../../../results/daily/2026-07-21/rolling_validation_model_1/rl_evidence_after_risk_exit_fix.json`

Remaining gates before LLM agents should use RL as a reliable source:

- multi-seed training and evaluation;
- rolling-origin/time-split evaluation under the fixed risk-state semantics;
- DSR/PBO-style overfit adjustment using the append-only trial registry;
- cost/slippage sensitivity;
- calibration/prospective shadow evidence;
- explicit promotion metadata with expiry.

## Recommended Next Slice

Do not immediately promote or tune on this one strong post-fix backtest. Next:

1. re-evaluate the prior corrected-clock challenger under the same fixed risk-state semantics for apples-to-apples comparison;
2. add a small multi-seed experiment runner using the rolling validation callback;
3. run a cheap 3-seed screen before longer training;
4. only consider promotion if the fixed semantics hold across seeds, folds, and cost stress.

## Artifacts

- Pre-fix behavior summary: `../../../results/daily/2026-07-22/risk_exit_cash_lock_diagnosis/rl_behavior_summary.csv`
- Pre-fix monthly behavior: `../../../results/daily/2026-07-22/risk_exit_cash_lock_diagnosis/rl_behavior_monthly.csv`
- Post-fix behavior summary: `../../../results/daily/2026-07-22/risk_exit_cash_lock_diagnosis/post_fix_comparison/rl_behavior_summary.csv`
- Post-fix monthly behavior: `../../../results/daily/2026-07-22/risk_exit_cash_lock_diagnosis/post_fix_comparison/rl_behavior_monthly.csv`
- Post-fix metrics: `../../../results/daily/2026-07-22/2/backtest_metrics.csv`
- Post-fix baselines: `../../../results/daily/2026-07-22/2/backtest_baselines.csv`
- Post-fix provenance: `../../../results/daily/2026-07-22/2/backtest_provenance.json`
- Post-fix statistical report: `../../../results/daily/2026-07-22/2/backtest_statistical_report.json`
- Post-fix episode parquet: `../../../results/daily/2026-07-22/2/backtest_episode_rl_only_live_like_dynamic_weighted.parquet`
- Post-fix trade decisions: `../../../results/daily/2026-07-22/2/trade_decisions_rl_only_live_like_dynamic_weighted.csv`
- Post-fix equity curve: `../../../results/daily/2026-07-22/2/equity_curve.png`
- Post-fix KPI radar: `../../../results/daily/2026-07-22/2/kpi_target_radar.png`
- Post-fix evidence envelope: `../../../results/daily/2026-07-21/rolling_validation_model_1/rl_evidence_after_risk_exit_fix.json`
