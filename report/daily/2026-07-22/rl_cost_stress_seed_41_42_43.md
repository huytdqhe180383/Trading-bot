# RL Cost-Stress Screen: Seeds 41, 42, And 43

Date: 2026-07-22

## Outcome

Added explicit backtest fee/slippage/latency overrides, added a reusable RL cost-stress runner, and evaluated seeds `41`, `42`, and `43` across 1x, 2x, and 3x live-like transaction-cost assumptions.

Decision: **do not promote any RL seed as an LLM-agent-trustworthy source.** The three-seed family looks strong under nominal live-like costs, but the edge collapses under 2x costs and becomes deeply negative under 3x costs.

This is a material reliability finding. Seed 41 remains the nominal point-metric leader, but it fails the cost-stress gate.

## Code Change

Committed tooling:

```text
d789128 Add RL cost-stress evaluation runner
```

Changes:

- `backtest.py`: added `--fee-override`, `--slippage-override`, and `--latency-steps-override`.
- `backtest.py`: persists the resolved realism settings and override values in `session_metadata.json`.
- `scripts/run_rl_cost_stress.py`: runs existing model directories through named cost profiles, writes `cost_stress_summary.csv`, and builds fail-closed RL evidence envelopes.
- Tests cover override parsing/application and the cost-stress runner dry-run path.

Focused tests:

```text
python -m pytest tests/test_backtest_session_outputs.py tests/test_rl_cost_stress.py -q
27 passed
```

## Cost Profiles

All runs used:

```text
pipeline=rl_only
method=dynamic_weighted
realism_profile=live_like
latency_steps=1
post_policy_overlay=none
```

| Profile | Fee | Slippage | Interpretation |
| --- | ---: | ---: | --- |
| `live_like_1x` | 0.0012 | 0.0018 | current live-like assumption |
| `live_like_2x` | 0.0024 | 0.0036 | doubled cost stress |
| `live_like_3x` | 0.0036 | 0.0054 | tripled cost stress |

Output directory:

- [`../../../results/daily/2026-07-22/rl_cost_stress/seed_41_42_43_x1_x2_x3/`](../../../results/daily/2026-07-22/rl_cost_stress/seed_41_42_43_x1_x2_x3/)

## Matrix Result

Summary:

- [`../../../results/daily/2026-07-22/rl_cost_stress/seed_41_42_43_x1_x2_x3/cost_stress_summary.csv`](../../../results/daily/2026-07-22/rl_cost_stress/seed_41_42_43_x1_x2_x3/cost_stress_summary.csv)

| Seed | Profile | Return | Sharpe | Max drawdown | Cost-bearing steps |
| --- | --- | ---: | ---: | ---: | ---: |
| seed 41 | `live_like_1x` | 201.36% | 1.2614 | -30.87% | 2,359 |
| seed 41 | `live_like_2x` | -20.96% | -0.3065 | -50.13% | 1,825 |
| seed 41 | `live_like_3x` | -69.51% | -1.6714 | -71.60% | 1,512 |
| seed 42 | `live_like_1x` | 170.64% | 1.1582 | -28.20% | 2,517 |
| seed 42 | `live_like_2x` | -23.46% | -0.3440 | -47.39% | 1,834 |
| seed 42 | `live_like_3x` | -71.47% | -1.7449 | -73.34% | 1,497 |
| seed 43 | `live_like_1x` | 178.95% | 1.1658 | -31.90% | 2,392 |
| seed 43 | `live_like_2x` | -16.35% | -0.2287 | -46.61% | 1,673 |
| seed 43 | `live_like_3x` | -63.95% | -1.4085 | -66.57% | 1,381 |

Profile-level aggregate:

- [`../../../results/daily/2026-07-22/rl_cost_stress/seed_41_42_43_x1_x2_x3/cost_stress_profile_aggregate.csv`](../../../results/daily/2026-07-22/rl_cost_stress/seed_41_42_43_x1_x2_x3/cost_stress_profile_aggregate.csv)

| Profile | Mean return | Median return | Return range | Mean Sharpe | Mean max drawdown |
| --- | ---: | ---: | ---: | ---: | ---: |
| `live_like_1x` | 183.65% | 178.95% | 170.64% to 201.36% | 1.1951 | -30.32% |
| `live_like_2x` | -20.26% | -20.96% | -23.46% to -16.35% | -0.2931 | -48.04% |
| `live_like_3x` | -68.31% | -69.51% | -71.47% to -63.95% | -1.6083 | -70.50% |

Degradation from 1x:

- [`../../../results/daily/2026-07-22/rl_cost_stress/seed_41_42_43_x1_x2_x3/cost_stress_degradation.csv`](../../../results/daily/2026-07-22/rl_cost_stress/seed_41_42_43_x1_x2_x3/cost_stress_degradation.csv)

| Seed | Profile | Return delta vs 1x | Sharpe delta vs 1x | Drawdown delta vs 1x |
| --- | --- | ---: | ---: | ---: |
| seed 41 | `live_like_2x` | -222.33 pp | -1.5680 | -19.27 pp |
| seed 41 | `live_like_3x` | -270.87 pp | -2.9329 | -40.73 pp |
| seed 42 | `live_like_2x` | -194.11 pp | -1.5022 | -19.18 pp |
| seed 42 | `live_like_3x` | -242.11 pp | -2.9031 | -45.14 pp |
| seed 43 | `live_like_2x` | -195.30 pp | -1.3945 | -14.70 pp |
| seed 43 | `live_like_3x` | -242.90 pp | -2.5743 | -34.66 pp |

## Interpretation

The model family is highly transaction-cost-sensitive.

The nominal 1x result was not enough evidence for reliability, but this cost-stress result is stronger: it actively contradicts promotion. If fee/slippage assumptions are even moderately wrong, the current policies can flip from high-return/high-Sharpe to negative-return/negative-Sharpe.

Notable details:

- Seed 41 is best at 1x costs but not robust.
- Seed 43 is least bad at 2x and 3x costs, but still loses money and has negative Sharpe.
- Higher costs reduce cost-bearing steps, which means the execution controls react by trading less, but not enough to preserve profitability.
- The policy family likely relies on relatively thin rebalancing edge after costs.

## LLM Evidence Status

All nine cost-stress evidence envelopes are `ABSTAIN`.

Examples:

- Seed 41 1x: [`../../../results/daily/2026-07-22/rl_cost_stress/seed_41_42_43_x1_x2_x3/seed_41/live_like_1x/rl_evidence.json`](../../../results/daily/2026-07-22/rl_cost_stress/seed_41_42_43_x1_x2_x3/seed_41/live_like_1x/rl_evidence.json)
- Seed 41 2x: [`../../../results/daily/2026-07-22/rl_cost_stress/seed_41_42_43_x1_x2_x3/seed_41/live_like_2x/rl_evidence.json`](../../../results/daily/2026-07-22/rl_cost_stress/seed_41_42_43_x1_x2_x3/seed_41/live_like_2x/rl_evidence.json)
- Seed 43 3x: [`../../../results/daily/2026-07-22/rl_cost_stress/seed_41_42_43_x1_x2_x3/seed_43/live_like_3x/rl_evidence.json`](../../../results/daily/2026-07-22/rl_cost_stress/seed_41_42_43_x1_x2_x3/seed_43/live_like_3x/rl_evidence.json)

LLM agents must treat the RL source as non-executable research context only. They must not infer orders, target allocations, leverage, or confidence from this RL family.

## Next Required Slice

The next model-improvement step should target cost robustness before more promotion statistics:

1. Add a cost-aware training/evaluation objective or selection criterion.
   - Selection should require non-negative performance at 2x costs.
   - Penalize turnover explicitly enough that 2x cost does not destroy the edge.
2. Add a validation callback metric that evaluates candidate checkpoints under at least nominal and 2x costs.
3. Re-train a new challenger after that cost-aware selection is implemented.
4. Re-run the seed/fold/cost matrix before DSR/PBO and prospective shadow work.

This changes the immediate research target from “find the highest nominal Sharpe seed” to “find a seed family that survives realistic cost misspecification.”

## Artifacts

- Cost-stress stdout: [`../../../results/daily/2026-07-22/rl_cost_stress/seed_41_42_43_x1_x2_x3/cost_stress_stdout.log`](../../../results/daily/2026-07-22/rl_cost_stress/seed_41_42_43_x1_x2_x3/cost_stress_stdout.log)
- Seed 41 1x backtest: [`../../../results/daily/2026-07-22/6/`](../../../results/daily/2026-07-22/6/)
- Seed 41 2x backtest: [`../../../results/daily/2026-07-22/7/`](../../../results/daily/2026-07-22/7/)
- Seed 41 3x backtest: [`../../../results/daily/2026-07-22/8/`](../../../results/daily/2026-07-22/8/)
- Seed 42 1x backtest: [`../../../results/daily/2026-07-22/9/`](../../../results/daily/2026-07-22/9/)
- Seed 42 2x backtest: [`../../../results/daily/2026-07-22/10/`](../../../results/daily/2026-07-22/10/)
- Seed 42 3x backtest: [`../../../results/daily/2026-07-22/11/`](../../../results/daily/2026-07-22/11/)
- Seed 43 1x backtest: [`../../../results/daily/2026-07-22/12/`](../../../results/daily/2026-07-22/12/)
- Seed 43 2x backtest: [`../../../results/daily/2026-07-22/13/`](../../../results/daily/2026-07-22/13/)
- Seed 43 3x backtest: [`../../../results/daily/2026-07-22/14/`](../../../results/daily/2026-07-22/14/)
