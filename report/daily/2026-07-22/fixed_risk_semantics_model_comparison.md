# Fixed Risk-Semantics Model Comparison

Date: 2026-07-22

## Outcome

Re-evaluated the earlier corrected-clock challenger under the same fixed hard-risk-exit semantics used for the rolling-validation challenger, then compared both models apples-to-apples.

Decision: keep the rolling-validation challenger as the current research leader, but do not promote either model as an LLM-agent-trustworthy RL source yet.

## Why This Was Needed

The stale risk-exit cash-lock bug changed the meaning of earlier backtests. Before the fix, the execution layer repeatedly fired stale `session_drawdown<=-6%` exits, causing long backtests to become mostly 100% cash after the first drawdown event.

After fixing that state machine, the rolling-validation challenger improved from `-5.92%` to `178.95%`. That meant the previous corrected-clock challenger also needed to be re-evaluated under the same semantics before choosing the next training path.

## Backtest Commands

Rolling-validation challenger, already evaluated post-fix:

```text
backtest.py --pipeline rl_only --realism-profile live_like --method dynamic_weighted --model-dir "K:\BTC-ETH Trading\results\daily\2026-07-21\rolling_validation_model_1\models" --autosave-profit-threshold 999999
```

Corrected-clock challenger, re-evaluated this session:

```text
backtest.py --pipeline rl_only --realism-profile live_like --method dynamic_weighted --model-dir "K:\BTC-ETH Trading\results\daily\2026-07-21\corrected_clock_model_1\models" --autosave-profit-threshold 999999
```

Code state for the corrected-clock fixed-semantics re-evaluation included:

```text
9c0178b Report risk-exit cash-lock diagnosis
```

## Point-Metric Comparison

| Metric | Rolling-validation fixed | Corrected-clock fixed |
| --- | ---: | ---: |
| Total return | 178.95% | 170.63% |
| Annualized return | 52.71% | 50.81% |
| Sharpe | 1.1658 | 1.1397 |
| Sortino | 1.6333 | 1.5830 |
| Max drawdown | -31.90% | -32.03% |
| Profit factor | 1.0438 | 1.0430 |
| Total trades | 2,392 | 2,548 |
| Trade count | 56 | 59 |
| Trade profit factor | 2.4039 | 2.3662 |

## Behavior Comparison

| Behavior diagnostic | Rolling-validation fixed | Corrected-clock fixed |
| --- | ---: | ---: |
| Mean cash weight | 28.98% | 29.74% |
| Mean realized risk-on | 71.02% | 70.26% |
| Mean target risk-on | 90.81% | 93.36% |
| Mean risk tracking gap | 20.62% | 23.69% |
| Risk-exit applied rate | 0.50% | 0.41% |

Interpretation:

- Both models now trade through the full backtest instead of becoming cash-locked.
- Rolling validation is slightly ahead on return, Sharpe, drawdown, trade count, and policy/execution tracking gap.
- The difference is not large enough to treat one seed as a promotion winner.

## Bootstrap Diagnostics

| Bootstrap diagnostic | Rolling-validation fixed | Corrected-clock fixed |
| --- | ---: | ---: |
| Strategy total-return 95% interval | -9.07% to 811.16% | -7.86% to 799.46% |
| Strategy Sharpe 95% interval | -0.1060 to 2.5182 | -0.0936 to 2.4573 |
| Strategy max-drawdown 95% interval | -55.01% to -20.48% | -55.06% to -20.19% |
| Probability of beating BTC buy-and-hold on total return | 97.0% | 95.6% |
| Probability of beating 50/50 hourly rebalanced on total return | 99.4% | 99.8% |
| Probability of beating BTC buy-and-hold on Sharpe | 99.4% | 99.0% |

Interpretation:

- Both models look promising against same-window baselines under fixed execution semantics.
- Both total-return intervals are very wide and include negative outcomes.
- Both drawdown intervals are too severe for promotion without further risk constraints or robustness evidence.

## Reliability Status

Both post-fix evidence envelopes remain `ABSTAIN`.

Rolling-validation post-fix envelope:

- `../../../results/daily/2026-07-21/rolling_validation_model_1/rl_evidence_after_risk_exit_fix.json`

Corrected-clock post-fix envelope:

- `../../../results/daily/2026-07-21/corrected_clock_model_1/rl_evidence_after_risk_exit_fix.json`

Reasons remain:

- promotion status missing;
- promotion expiry missing;
- full causal-integrity gate missing;
- statistical gates missing;
- calibration gate missing;
- prospective shadow gate missing.

## Current Research Leader

Use the rolling-validation challenger as the current research leader because:

- it was selected with distinct rolling validation windows instead of duplicated deterministic eval episodes;
- it has slightly better fixed-semantics point metrics;
- it has fewer trades and a smaller policy/execution tracking gap.

Do not promote it to agent-trustworthy status yet.

## Next Required Slice

The next aligned implementation step is a small multi-seed experiment runner using the fixed execution semantics and rolling-validation callback.

Minimum useful screen:

- seeds: `41`, `42`, `43`;
- algorithm set: PPO + SAC;
- training: same 50k quick budget;
- evaluation: fixed-semantics `rl_only/live_like/dynamic_weighted`;
- outputs: one append-only trial row per seed, behavior diagnostics, bootstrap report, and an aggregate seed summary.

Promotion should only be considered after seed/fold/cost robustness, DSR/PBO adjustment, and prospective shadow evidence.

## Artifacts

- Rolling-validation fixed backtest: `../../../results/daily/2026-07-22/2/`
- Corrected-clock fixed backtest: `../../../results/daily/2026-07-22/3/`
- Fixed-semantics behavior summary: `../../../results/daily/2026-07-22/fixed_risk_semantics_model_comparison/rl_behavior_summary.csv`
- Fixed-semantics monthly behavior: `../../../results/daily/2026-07-22/fixed_risk_semantics_model_comparison/rl_behavior_monthly.csv`
- Corrected-clock fixed metrics: `../../../results/daily/2026-07-22/3/backtest_metrics.csv`
- Corrected-clock fixed baselines: `../../../results/daily/2026-07-22/3/backtest_baselines.csv`
- Corrected-clock fixed provenance: `../../../results/daily/2026-07-22/3/backtest_provenance.json`
- Corrected-clock fixed statistical report: `../../../results/daily/2026-07-22/3/backtest_statistical_report.json`
- Corrected-clock fixed episode: `../../../results/daily/2026-07-22/3/backtest_episode_rl_only_live_like_dynamic_weighted.parquet`
- Corrected-clock fixed trade decisions: `../../../results/daily/2026-07-22/3/trade_decisions_rl_only_live_like_dynamic_weighted.csv`
- Corrected-clock fixed equity curve: `../../../results/daily/2026-07-22/3/equity_curve.png`
- Corrected-clock fixed KPI radar: `../../../results/daily/2026-07-22/3/kpi_target_radar.png`
- Corrected-clock fixed evidence envelope: `../../../results/daily/2026-07-21/corrected_clock_model_1/rl_evidence_after_risk_exit_fix.json`
