# RL Seed Screen: Seed 42 And Three-Seed Aggregate

Date: 2026-07-22

## Outcome

Trained and evaluated the remaining cheap screen seed (`42`) with the rolling-validation PPO/SAC runner, then compared seeds `41`, `42`, and `43` on the same fixed-semantics `rl_only/live_like/dynamic_weighted` backtest.

Decision: seed 41 remains the point-metric research leader, but the three-seed result is still **not promotion-grade**. All LLM-facing RL evidence envelopes remain `ABSTAIN`.

The three-seed screen is materially better than relying on one checkpoint:

- all three seeds produce strong same-path research backtests after the execution-semantics fixes;
- seed 41 leads on return and Sharpe;
- seed 42 leads on drawdown;
- return still ranges by `30.72` percentage points across only three seeds, so seed variance remains too large to call the RL source reliable.

## Seed 42 Command

Seed 42 output directory:

- [`../../../results/daily/2026-07-22/rl_seed_screen/manual_seed42/`](../../../results/daily/2026-07-22/rl_seed_screen/manual_seed42/)

Command:

```text
scripts/run_rl_seed_screen.py --seeds 42 --timesteps 50000 --device cpu --validation-fraction 0.2 --validation-windows 5 --output-dir "K:\BTC-ETH Trading\results\daily\2026-07-22\rl_seed_screen\manual_seed42"
```

The run used code commit:

```text
56f8cfc4e5ae99d7927668587149bd58534d199a
```

## Seed 42 Training Result

The rolling validation split used the same five chronological validation windows as the earlier seeds, covering `2023-04-26 07:00:00+00:00` through `2023-12-31 23:00:00+00:00`.

| Model | Rolling validation trace | Selected checkpoint |
| --- | --- | --- |
| PPO | 20k `-87.56 +/- 19.09`, 40k `-87.98 +/- 18.01`, 60k `-88.19 +/- 18.02` | 20k best, saved as `ppo_best.zip` |
| SAC | 10k `-89.01 +/- 19.42`, 20k `-80.49 +/- 19.56`, 30k `-91.02 +/- 24.41`, 40k `-93.53 +/- 18.88`, 50k `-90.85 +/- 20.56` | 20k best, saved as `sac_best.zip` |

Lesson: all three screened SAC runs peaked around the 20k validation checkpoint and degraded later. Keep rolling-validation checkpoint selection enabled; the final 50k checkpoint is not automatically the best model.

## Seed 42 Backtest Result

Backtest output directory:

- [`../../../results/daily/2026-07-22/5/`](../../../results/daily/2026-07-22/5/)

Key metrics:

| Metric | Seed 42 |
| --- | ---: |
| Total return | 170.64% |
| Annualized return | 50.81% |
| Sharpe | 1.1582 |
| Sortino | 1.6321 |
| Max drawdown | -28.20% |
| Profit factor | 1.0434 |
| Total cost-bearing steps | 2,517 |
| Material trade count | 57 |
| Trade win rate | 49.12% |
| Trade profit factor | 2.3739 |
| Trade expectancy | 2.4081% |

Same-path bootstrap diagnostics for seed 42:

| Diagnostic | Value |
| --- | ---: |
| Strategy total-return 95% interval | -7.08% to 816.89% |
| Strategy Sharpe 95% interval | -0.0859 to 2.5130 |
| Strategy max-drawdown 95% interval | -55.79% to -20.07% |
| Probability of beating cash on total return | 97.0% |
| Probability of beating BTC buy-and-hold on total return | 95.2% |
| Probability of beating equal-weight hourly rebalanced on total return | 99.0% |

Interpretation: seed 42 is a positive research result, but its same-path bootstrap return and Sharpe intervals still include weak/negative outcomes.

## Three-Seed Point-Metric Comparison

Aggregate behavior output:

- [`../../../results/daily/2026-07-22/rl_seed_screen/seed_41_42_43_aggregate/rl_behavior_summary.csv`](../../../results/daily/2026-07-22/rl_seed_screen/seed_41_42_43_aggregate/rl_behavior_summary.csv)
- [`../../../results/daily/2026-07-22/rl_seed_screen/seed_41_42_43_aggregate/rl_behavior_monthly.csv`](../../../results/daily/2026-07-22/rl_seed_screen/seed_41_42_43_aggregate/rl_behavior_monthly.csv)

| Metric | Seed 41 | Seed 42 | Seed 43 | Three-seed mean | Range |
| --- | ---: | ---: | ---: | ---: | ---: |
| Total return | 201.36% | 170.64% | 178.95% | 183.65% | 30.72 pp |
| Annualized return | 57.66% | 50.81% | 52.71% | 53.73% | 6.84 pp |
| Sharpe | 1.2614 | 1.1582 | 1.1658 | 1.1951 | 0.1033 |
| Sortino | 1.7645 | 1.6321 | 1.6333 | 1.6766 | 0.1324 |
| Max drawdown | -30.87% | -28.20% | -31.90% | -30.32% | 3.70 pp |
| Profit factor | 1.0470 | 1.0434 | 1.0438 | 1.0447 | 0.0036 |
| Material trade count | 61 | 57 | 56 | 58.0 | 5 |
| Trade win rate | 50.82% | 49.12% | 44.64% | 48.20% | 6.18 pp |
| Trade profit factor | 2.4531 | 2.3739 | 2.4039 | 2.4103 | 0.0793 |
| Trade expectancy | 2.5538% | 2.4081% | 2.5111% | 2.4910% | 0.1457 pp |

Interpretation:

- Seed 41 is the current research leader by total return, Sharpe, Sortino, profit factor, trade win rate, and trade expectancy.
- Seed 42 has the best maximum drawdown, but it gives up return and Sharpe.
- Seed 43 sits near the center and remains useful as a baseline replication.
- The result is stable enough to justify the next reliability gates, but not stable enough to serve as an LLM-agent source.

## Behavior Comparison

| Behavior diagnostic | Seed 41 | Seed 42 | Seed 43 | Three-seed mean | Range |
| --- | ---: | ---: | ---: | ---: | ---: |
| Mean realized risk-on | 71.45% | 69.80% | 71.02% | 70.76% | 1.66 pp |
| Mean target risk-on | 95.51% | 93.81% | 90.81% | 93.37% | 4.70 pp |
| Mean risk-tracking gap | 24.73% | 24.62% | 20.62% | 23.32% | 4.10 pp |
| Mean cash weight | 28.55% | 30.20% | 28.98% | 29.24% | 1.66 pp |
| Turnover sum | 593.04 | 614.50 | 611.21 | 606.25 | 21.47 |
| Transaction-cost sum | 1.7791 | 1.8435 | 1.8336 | 1.8187 | 0.0644 |
| Risk exits applied | 96 | 96 | 106 | 99.33 | 10 |
| Risk governor active count | 15,157 | 15,547 | 14,762 | 15,155.33 | 785 |

Interpretation:

- The three seeds have very similar realized risk-on exposure, around `70-71%`.
- Seed 41 does not win by simply trading more; it has the lowest turnover and lowest transaction-cost sum among the three.
- Seed 42 has the highest cash weight and best drawdown.
- The execution layer clips seed 41 and seed 42 more than seed 43, which is visible in the larger target-vs-realized risk gap.

## LLM Evidence Status

Seed 42 evidence envelope:

- [`../../../results/daily/2026-07-22/rl_seed_screen/manual_seed42/seed_42/rl_evidence.json`](../../../results/daily/2026-07-22/rl_seed_screen/manual_seed42/seed_42/rl_evidence.json)

Status:

```text
ABSTAIN
```

The same fail-closed status applies to seed 41 and seed 43. The reason is correct and intentional: same-path backtests, even strong ones, do not satisfy the promotion, DSR/PBO, calibration, or prospective shadow requirements.

LLM agents may cite these results as non-executable research context only. They must not infer target allocations, position sizes, leverage, orders, or confidence scores from them.

## Reliability Decision

Do not promote an RL source yet.

Current candidate ranking:

1. Seed 41: best return/Sharpe research candidate.
2. Seed 42: best drawdown candidate.
3. Seed 43: central replication candidate.

Next required gates:

1. Add cost-stress evaluation across fee/slippage assumptions.
2. Aggregate seed/fold/cost results with bootstrap intervals across evaluation units, not only same-path hourly returns.
3. Compute DSR/PBO over the append-only trial registry.
4. Add conformal outcome calibration fields for the LLM evidence envelope.
5. Run prospective paper/shadow evaluation with an expiry before any `VERIFIED` or `CAUTION` RL evidence status is allowed.

## Artifacts

- Seed 42 summary: [`../../../results/daily/2026-07-22/rl_seed_screen/manual_seed42/seed_screen_summary.csv`](../../../results/daily/2026-07-22/rl_seed_screen/manual_seed42/seed_screen_summary.csv)
- Seed 42 training stderr: [`../../../results/daily/2026-07-22/rl_seed_screen/manual_seed42/seed_42/training_stderr.log`](../../../results/daily/2026-07-22/rl_seed_screen/manual_seed42/seed_42/training_stderr.log)
- Seed 42 PPO validation metrics: [`../../../results/daily/2026-07-22/rl_seed_screen/manual_seed42/seed_42/ppo_rolling_validation_metrics.csv`](../../../results/daily/2026-07-22/rl_seed_screen/manual_seed42/seed_42/ppo_rolling_validation_metrics.csv)
- Seed 42 SAC validation metrics: [`../../../results/daily/2026-07-22/rl_seed_screen/manual_seed42/seed_42/sac_rolling_validation_metrics.csv`](../../../results/daily/2026-07-22/rl_seed_screen/manual_seed42/seed_42/sac_rolling_validation_metrics.csv)
- Seed 42 model directory: [`../../../results/daily/2026-07-22/rl_seed_screen/manual_seed42/seed_42/models/`](../../../results/daily/2026-07-22/rl_seed_screen/manual_seed42/seed_42/models/)
- Seed 42 backtest metrics: [`../../../results/daily/2026-07-22/5/backtest_metrics.csv`](../../../results/daily/2026-07-22/5/backtest_metrics.csv)
- Seed 42 baselines: [`../../../results/daily/2026-07-22/5/backtest_baselines.csv`](../../../results/daily/2026-07-22/5/backtest_baselines.csv)
- Seed 42 provenance: [`../../../results/daily/2026-07-22/5/backtest_provenance.json`](../../../results/daily/2026-07-22/5/backtest_provenance.json)
- Seed 42 statistical report: [`../../../results/daily/2026-07-22/5/backtest_statistical_report.json`](../../../results/daily/2026-07-22/5/backtest_statistical_report.json)
- Seed 42 episode parquet: [`../../../results/daily/2026-07-22/5/backtest_episode_rl_only_live_like_dynamic_weighted.parquet`](../../../results/daily/2026-07-22/5/backtest_episode_rl_only_live_like_dynamic_weighted.parquet)
- Seed 42 trade decisions: [`../../../results/daily/2026-07-22/5/trade_decisions_rl_only_live_like_dynamic_weighted.csv`](../../../results/daily/2026-07-22/5/trade_decisions_rl_only_live_like_dynamic_weighted.csv)
- Seed 42 equity curve: [`../../../results/daily/2026-07-22/5/equity_curve.png`](../../../results/daily/2026-07-22/5/equity_curve.png)
- Seed 42 KPI radar: [`../../../results/daily/2026-07-22/5/kpi_target_radar.png`](../../../results/daily/2026-07-22/5/kpi_target_radar.png)
