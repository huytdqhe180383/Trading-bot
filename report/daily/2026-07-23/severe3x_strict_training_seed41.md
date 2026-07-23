# Severe3x-Strict RL Training and Evaluation: Seed 41

**Date:** 2026-07-23

**Status:** Evaluated; not promoted

**Code commit used for evaluation:** `50238dfa70fac4274267f7da95a94f31c404b4f3`

## Executive Decision

The severe3x-strict challenger improved the severe-cost frontier a little, but not enough.

Compared with turnover-strict seed `41`, it improved:

- 2x return: `59.73%` -> `66.15%`
- 2x Sharpe: `0.5944` -> `0.6806`
- 3x return: `-40.46%` -> `-38.46%`
- 3x max drawdown: `-53.03%` -> `-49.82%`

It still fails 3x cost stress with negative return and negative Sharpe. The promotion gate correctly returns `NOT_PROMOTED` with `llm_evidence_status: ABSTAIN`.

## Training Setup

Training artifacts are preserved under [severe3x_strict_model_seed41_1](../../../results/daily/2026-07-23/severe3x_strict_model_seed41_1/).

Training command: [training_command.txt](../../../results/daily/2026-07-23/severe3x_strict_model_seed41_1/training_command.txt)

Key settings:

| Setting | Value |
|---|---:|
| Seed | `41` |
| Algorithms | PPO, SAC |
| Requested timesteps | `30,000` |
| Training fee/slippage | `0.0036 / 0.0054` |
| Validation profiles | `nominal`, `stress2x`, `severe3x` |
| Checkpoint selection score | worst profile mean reward |
| Reward turnover weight | `12.0` |
| Reward action-delta weight | `1.0` |
| Reward action-delta deadband | `0.0` |
| Reward action-delta scale | `1.0` |
| Step turnover cap | enabled |
| Normal/stress/crisis cap | `0.08 / 0.05 / 0.03` |

Preserved validation logs:

- [ppo_rolling_validation_metrics.csv](../../../results/daily/2026-07-23/severe3x_strict_model_seed41_1/ppo_rolling_validation_metrics.csv)
- [sac_rolling_validation_metrics.csv](../../../results/daily/2026-07-23/severe3x_strict_model_seed41_1/sac_rolling_validation_metrics.csv)

Best model artifacts:

- [models/PPO/ppo_best.zip](../../../results/daily/2026-07-23/severe3x_strict_model_seed41_1/models/PPO/ppo_best.zip)
- [models/SAC/sac_best.zip](../../../results/daily/2026-07-23/severe3x_strict_model_seed41_1/models/SAC/sac_best.zip)

## Rolling Validation

| Algorithm | Step | Nominal mean reward | Stress2x mean reward | Severe3x mean reward | Selection score |
|---|---:|---:|---:|---:|---:|
| PPO | 20,000 | `-109.91` | `-125.23` | `-148.23` | `-148.23` |
| SAC | 10,000 | `-110.71` | `-125.71` | `-147.59` | `-147.59` |
| SAC | 20,000 | `-117.94` | `-139.47` | `-161.62` | `-161.62` |
| SAC | 30,000 | `-122.45` | `-150.75` | `-173.39` | `-173.39` |

SAC again selected the 10k checkpoint and degraded afterward. This pattern has now repeated across both turnover-strict and severe3x-strict training. The next code improvement should be an early-stop rule or cheaper SAC budget when rolling validation deteriorates.

## Cost-Stress Evaluation

Cost-stress outputs are preserved under [rl_cost_stress/severe3x_strict_seed41_1](../../../results/daily/2026-07-23/rl_cost_stress/severe3x_strict_seed41_1/).

Summary CSV: [cost_stress_summary.csv](../../../results/daily/2026-07-23/rl_cost_stress/severe3x_strict_seed41_1/cost_stress_summary.csv)

Promotion input CSV: [severe3x_strict_seed41_promotion_input.csv](../../../results/daily/2026-07-23/rl_cost_stress/severe3x_strict_seed41_1/severe3x_strict_seed41_promotion_input.csv)

| Cost profile | Fee | Slippage | Return | Sharpe | Max drawdown | Cost-bearing steps | Trade events | Evidence |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| live_like_1x | `0.0012` | `0.0018` | `418.39%` | `1.9713` | `-20.79%` | `4,742` | `63` | `ABSTAIN` |
| live_like_2x | `0.0024` | `0.0036` | `66.15%` | `0.6806` | `-33.56%` | `4,913` | `53` | `ABSTAIN` |
| live_like_3x | `0.0036` | `0.0054` | `-38.46%` | `-0.8037` | `-49.82%` | `4,679` | `45` | `ABSTAIN` |

Evidence envelopes:

- [live_like_1x/rl_evidence.json](../../../results/daily/2026-07-23/rl_cost_stress/severe3x_strict_seed41_1/severe3x_strict_seed41/live_like_1x/rl_evidence.json)
- [live_like_2x/rl_evidence.json](../../../results/daily/2026-07-23/rl_cost_stress/severe3x_strict_seed41_1/severe3x_strict_seed41/live_like_2x/rl_evidence.json)
- [live_like_3x/rl_evidence.json](../../../results/daily/2026-07-23/rl_cost_stress/severe3x_strict_seed41_1/severe3x_strict_seed41/live_like_3x/rl_evidence.json)

## Comparison to Turnover-Strict Seed 41

| Profile | Severe3x-strict return | Turnover-strict return | Delta | Severe3x-strict Sharpe | Turnover-strict Sharpe | Sharpe delta | Drawdown delta |
|---|---:|---:|---:|---:|---:|---:|---:|
| live_like_1x | `418.39%` | `481.56%` | `-63.16 pp` | `1.9713` | `1.9833` | `-0.0120` | `+2.46 pp` |
| live_like_2x | `66.15%` | `59.73%` | `+6.42 pp` | `0.6806` | `0.5944` | `+0.0862` | `+1.71 pp` |
| live_like_3x | `-38.46%` | `-40.46%` | `+2.00 pp` | `-0.8037` | `-0.7857` | `-0.0179` | `+3.21 pp` |

Interpretation: severe-cost training and tighter caps reduced drawdown and helped 2x performance, but they did not convert 3x into a viable operating regime. The higher cost-bearing step count suggests the policy became smoother but still spends too much time in nonzero cost-bearing rebalances.

## Promotion Gate

Promotion-gate outputs are preserved under [rl_promotion_gate/severe3x_strict_seed41_1](../../../results/daily/2026-07-23/rl_promotion_gate/severe3x_strict_seed41_1/).

- [promotion_gate_report.json](../../../results/daily/2026-07-23/rl_promotion_gate/severe3x_strict_seed41_1/promotion_gate_report.json)
- [promotion_gate_summary.csv](../../../results/daily/2026-07-23/rl_promotion_gate/severe3x_strict_seed41_1/promotion_gate_summary.csv)

Blocking failures:

| Gate | Observed | Threshold |
|---|---:|---:|
| `min_seed_count` | `1` seed | `>= 5` |
| `severe_return_all_seeds` | `-38.46%` at 3x | `>= 0.0%` |
| `severe_sharpe_all_seeds` | `-0.8037` at 3x | `>= 0.0` |
| `all_evidence_verified` | `ABSTAIN` | `VERIFIED` |
| `all_artifacts_marked_promoted` | `0 / 2` rows promoted | all rows promoted |

Passing gates:

- required 2x and 3x profiles present;
- required metrics complete;
- operating 2x return positive;
- operating 2x Sharpe positive;
- operating 2x drawdown within the `-40%` gate.

## Lessons

1. Adding severe3x validation is useful, but not sufficient.
2. Tighter caps improved drawdown and 2x robustness, but severe 3x remains negative.
3. SAC should not be blindly trained to 30k for this family; 10k continues to be the best checkpoint.
4. The next challenger should target lower cost-bearing exposure, not just higher cost penalties. Candidate ideas:
   - stronger explicit no-trade/hold preference under weak edge;
   - minimum expected edge threshold before reallocating;
   - drawdown-aware or CVaR-aware reward term;
   - early stopping on rolling validation deterioration.
5. LLM agents should still receive `ABSTAIN` only.

## Verification

Completed checks:

- Training completed for PPO and SAC.
- Required artifacts verified: `ppo_best.zip`, `sac_best.zip`, validation CSVs, training command.
- Cost-stress evaluation completed for 1x, 2x, and 3x profiles.
- Promotion gate completed and returned `NOT_PROMOTED`.

Remaining before final session close:

- Link check.
- Sensitive-output scan.
- Commit and push this report.

## Completion Checklist

- Report stored under `report/daily/2026-07-23/`.
- Preserved outputs stored under `results/daily/2026-07-23/`.
- Markdown links should resolve from this report location.
- No `.env`, credentials, virtual environments, or external source clones are referenced or stored by this report.
