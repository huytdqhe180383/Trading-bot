# RL Seed Screen: Seed 41

Date: 2026-07-22

## Outcome

Trained and evaluated one additional rolling-validation PPO/SAC seed (`41`) with the new seed-screen runner.

Decision: seed 41 becomes the current point-metric research leader, but it is **not promoted** as an LLM-agent-trustworthy RL source. The LLM-facing evidence envelope correctly remains `ABSTAIN`.

Why:

- seed 41 improves the fixed-semantics research leader, seed 43, on return, Sharpe, Sortino, maximum drawdown, and several trade-level diagnostics;
- the result is still one seed on the already-used 2024-2026 research backtest surface;
- DSR/PBO, multi-seed aggregation, cost-stress robustness, conformal calibration, and prospective shadow gates are still missing.

The paper-grounded promotion plan remains canonical: [`../../important/rl_reliability_research_and_llm_evidence_plan.md`](../../important/rl_reliability_research_and_llm_evidence_plan.md).

## Command

Seed screen output directory:

- [`../../../results/daily/2026-07-22/rl_seed_screen/manual_seed41/`](../../../results/daily/2026-07-22/rl_seed_screen/manual_seed41/)

Command:

```text
scripts/run_rl_seed_screen.py --seeds 41 --timesteps 50000 --device cpu --validation-fraction 0.2 --validation-windows 5 --output-dir "K:\BTC-ETH Trading\results\daily\2026-07-22\rl_seed_screen\manual_seed41"
```

The run used code commit:

```text
58cbf600fab9858b8af430b404726117788d0b78
```

## Training Result

The rolling validation split used five chronological windows from `2023-04-26 07:00:00+00:00` through `2023-12-31 23:00:00+00:00`, with 1,168-1,169 evaluated steps per window.

| Model | Rolling validation trace | Selected checkpoint |
| --- | --- | --- |
| PPO | 20k `-87.36 +/- 19.71`, 40k `-88.74 +/- 18.18`, 60k `-87.88 +/- 19.65` | 20k best, saved as `ppo_best.zip` |
| SAC | 10k `-87.46 +/- 19.21`, 20k `-82.69 +/- 20.12`, 30k `-94.15 +/- 17.90`, 40k `-92.77 +/- 16.66`, 50k `-93.83 +/- 18.34` | 20k best, saved as `sac_best.zip` |

Interpretation: SAC peaked early, and later checkpoints degraded materially. The rolling-validation callback protected the backtest from blindly using the final 50k checkpoint.

## Backtest Result

Backtest output directory:

- [`../../../results/daily/2026-07-22/4/`](../../../results/daily/2026-07-22/4/)

Backtest configuration:

```text
pipeline=rl_only
realism_profile=live_like
method=dynamic_weighted
fee=0.0012
slippage=0.0018
latency_steps=1
post_policy_overlay=none
```

Key metrics:

| Metric | Seed 41 | Prior leader seed 43 | Direction |
| --- | ---: | ---: | --- |
| Total return | 201.36% | 178.95% | better |
| Annualized return | 57.66% | 52.71% | better |
| Sharpe | 1.2614 | 1.1658 | better |
| Sortino | 1.7645 | 1.6333 | better |
| Max drawdown | -30.87% | -31.90% | better |
| Profit factor | 1.0470 | 1.0438 | better |
| Total cost-bearing steps | 2,359 | 2,392 | lower |
| Material trade count | 61 | 56 | higher |
| Trade win rate | 50.82% | 44.64% | better |
| Trade profit factor | 2.4531 | 2.4039 | better |
| Trade expectancy | 2.5538% | 2.5111% | better |

Same-path bootstrap diagnostics for seed 41:

| Diagnostic | Value |
| --- | ---: |
| Strategy total-return 95% interval | 0.12% to 963.55% |
| Strategy Sharpe 95% interval | 0.0016 to 2.6479 |
| Strategy max-drawdown 95% interval | -53.91% to -20.00% |
| Probability of beating cash on total return | 97.6% |
| Probability of beating BTC buy-and-hold on total return | 98.0% |
| Probability of beating ETH buy-and-hold on total return | 99.4% |
| Probability of beating equal-weight hourly rebalanced on total return | 100.0% |

Interpretation: seed 41 is a strong research challenger on this path, but the interval remains very wide and the same-path bootstrap cannot prove unseen-regime robustness.

## Behavior Comparison

Behavior comparison output:

- [`../../../results/daily/2026-07-22/rl_seed_screen/manual_seed41/behavior_comparison/rl_behavior_summary.csv`](../../../results/daily/2026-07-22/rl_seed_screen/manual_seed41/behavior_comparison/rl_behavior_summary.csv)
- [`../../../results/daily/2026-07-22/rl_seed_screen/manual_seed41/behavior_comparison/rl_behavior_monthly.csv`](../../../results/daily/2026-07-22/rl_seed_screen/manual_seed41/behavior_comparison/rl_behavior_monthly.csv)

| Behavior diagnostic | Seed 41 | Seed 43 | Interpretation |
| --- | ---: | ---: | --- |
| Mean realized risk-on | 71.45% | 71.02% | similar actual exposure |
| Mean target risk-on | 95.51% | 90.81% | seed 41 asks for more risk |
| Mean risk-tracking gap | 24.73% | 20.62% | execution/risk controls clip seed 41 more |
| Mean cash weight | 28.55% | 28.98% | seed 41 is slightly less cash-heavy |
| Turnover sum | 593.04 | 611.21 | seed 41 churns slightly less |
| Transaction-cost sum | 1.7791 | 1.8336 | seed 41 costs slightly less |
| Risk exits applied | 96 | 106 | seed 41 trips fewer hard exits |
| Risk governor active count | 15,157 | 14,762 | seed 41 spends more time under governor influence |

Interpretation: seed 41's improvement is not merely higher churn. It trades slightly less, costs slightly less, and hard-exits less often. The caution is that it targets more risk-on exposure and is clipped more by the execution/risk layer, so robustness and calibration checks matter before promotion.

## LLM Evidence Status

RL evidence envelope:

- [`../../../results/daily/2026-07-22/rl_seed_screen/manual_seed41/seed_41/rl_evidence.json`](../../../results/daily/2026-07-22/rl_seed_screen/manual_seed41/seed_41/rl_evidence.json)

Status:

```text
ABSTAIN
```

The envelope withholds an RL opinion for LLM agents for these reasons:

- promotion status missing;
- promotion expiry missing;
- causal-integrity gate missing;
- statistical gates missing;
- calibration gate missing;
- prospective shadow gate missing.

This is the desired fail-closed behavior. The result can be cited in research summaries, but an LLM agent must not turn it into a trade instruction, target allocation, leverage suggestion, or confidence score.

## Next Required Slice

1. Run the remaining cheap screen seed (`42`) and aggregate seeds `41`, `42`, and `43` as a seed distribution.
2. Add a cost-stress matrix around the live-like profile so the seed is not selected on one fee/slippage assumption.
3. Build DSR/PBO over the append-only trial registry and seed/fold matrix.
4. Add conformal outcome calibration for LLM evidence fields.
5. Only after those gates pass, run prospective paper/shadow evaluation with a time-bounded promotion expiry.

## Artifacts

- Seed-screen summary: [`../../../results/daily/2026-07-22/rl_seed_screen/manual_seed41/seed_screen_summary.csv`](../../../results/daily/2026-07-22/rl_seed_screen/manual_seed41/seed_screen_summary.csv)
- Training stderr: [`../../../results/daily/2026-07-22/rl_seed_screen/manual_seed41/seed_41/training_stderr.log`](../../../results/daily/2026-07-22/rl_seed_screen/manual_seed41/seed_41/training_stderr.log)
- PPO validation metrics: [`../../../results/daily/2026-07-22/rl_seed_screen/manual_seed41/seed_41/ppo_rolling_validation_metrics.csv`](../../../results/daily/2026-07-22/rl_seed_screen/manual_seed41/seed_41/ppo_rolling_validation_metrics.csv)
- SAC validation metrics: [`../../../results/daily/2026-07-22/rl_seed_screen/manual_seed41/seed_41/sac_rolling_validation_metrics.csv`](../../../results/daily/2026-07-22/rl_seed_screen/manual_seed41/seed_41/sac_rolling_validation_metrics.csv)
- Model directory: [`../../../results/daily/2026-07-22/rl_seed_screen/manual_seed41/seed_41/models/`](../../../results/daily/2026-07-22/rl_seed_screen/manual_seed41/seed_41/models/)
- Backtest metrics: [`../../../results/daily/2026-07-22/4/backtest_metrics.csv`](../../../results/daily/2026-07-22/4/backtest_metrics.csv)
- Backtest baselines: [`../../../results/daily/2026-07-22/4/backtest_baselines.csv`](../../../results/daily/2026-07-22/4/backtest_baselines.csv)
- Backtest provenance: [`../../../results/daily/2026-07-22/4/backtest_provenance.json`](../../../results/daily/2026-07-22/4/backtest_provenance.json)
- Backtest statistical report: [`../../../results/daily/2026-07-22/4/backtest_statistical_report.json`](../../../results/daily/2026-07-22/4/backtest_statistical_report.json)
- Episode parquet: [`../../../results/daily/2026-07-22/4/backtest_episode_rl_only_live_like_dynamic_weighted.parquet`](../../../results/daily/2026-07-22/4/backtest_episode_rl_only_live_like_dynamic_weighted.parquet)
- Trade decisions: [`../../../results/daily/2026-07-22/4/trade_decisions_rl_only_live_like_dynamic_weighted.csv`](../../../results/daily/2026-07-22/4/trade_decisions_rl_only_live_like_dynamic_weighted.csv)
- Equity curve: [`../../../results/daily/2026-07-22/4/equity_curve.png`](../../../results/daily/2026-07-22/4/equity_curve.png)
- KPI radar: [`../../../results/daily/2026-07-22/4/kpi_target_radar.png`](../../../results/daily/2026-07-22/4/kpi_target_radar.png)
