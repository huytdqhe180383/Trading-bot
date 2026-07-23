# Ultra3x-Strict Early-Stop RL Training and Evaluation: Seed 41

**Date:** 2026-07-23

**Status:** Evaluated; not promoted

**Code commit used for training/evaluation:** `216dd151d404e86b1abd05d477607a560b3a8c46`

## Executive Decision

Implemented configurable rolling-validation early stopping, then trained and evaluated an ultra3x-strict seed `41` challenger.

The new run is still not agent-reliable, but it improved the severe 3x cost frontier again:

- Severe3x-strict 3x return: `-38.46%`
- Ultra3x-strict 3x return: `-35.20%`
- Delta: `+3.26 pp`

The model still fails 3x return and Sharpe gates, and all evidence envelopes remain `ABSTAIN`. The promotion gate correctly returns `NOT_PROMOTED`.

## Code Change

Implemented tunable rolling-validation early stopping in [train.py](../../../train.py):

- `--validation-early-stop-patience`
- `--validation-early-stop-min-evals`

Default behavior remains conservative: patience `10`, min evals `20`.

For this cheap screen, the run used:

- `--validation-early-stop-patience 1`
- `--validation-early-stop-min-evals 2`

SAC stopped after 20k when the second rolling validation deteriorated, preserving the 10k best model.

Verification:

- `python -m pytest tests/test_train_hygiene.py -q`: `15 passed, 1 warning`

## Training Setup

Training artifacts are preserved under [ultra3x_strict_model_seed41_1](../../../results/daily/2026-07-23/ultra3x_strict_model_seed41_1/).

Training command: [training_command.txt](../../../results/daily/2026-07-23/ultra3x_strict_model_seed41_1/training_command.txt)

Key settings:

| Setting | Value |
|---|---:|
| Seed | `41` |
| Algorithms | PPO, SAC |
| Requested timesteps | `30,000` |
| Training fee/slippage | `0.0036 / 0.0054` |
| Validation profiles | `nominal`, `stress2x`, `severe3x` |
| Checkpoint selection score | worst profile mean reward |
| Early-stop patience/min evals | `1 / 2` |
| Reward turnover weight | `20.0` |
| Reward action-delta weight | `2.0` |
| Reward action-delta deadband | `0.0` |
| Reward action-delta scale | `1.0` |
| Step turnover cap | enabled |
| Normal/stress/crisis cap | `0.05 / 0.03 / 0.02` |

Preserved validation logs:

- [ppo_rolling_validation_metrics.csv](../../../results/daily/2026-07-23/ultra3x_strict_model_seed41_1/ppo_rolling_validation_metrics.csv)
- [sac_rolling_validation_metrics.csv](../../../results/daily/2026-07-23/ultra3x_strict_model_seed41_1/sac_rolling_validation_metrics.csv)

Best model artifacts:

- [models/PPO/ppo_best.zip](../../../results/daily/2026-07-23/ultra3x_strict_model_seed41_1/models/PPO/ppo_best.zip)
- [models/SAC/sac_best.zip](../../../results/daily/2026-07-23/ultra3x_strict_model_seed41_1/models/SAC/sac_best.zip)

## Rolling Validation

| Algorithm | Step | Nominal mean reward | Stress2x mean reward | Severe3x mean reward | Selection score |
|---|---:|---:|---:|---:|---:|
| PPO | 20,000 | `-125.59` | `-138.12` | `-160.67` | `-160.67` |
| SAC | 10,000 | `-124.79` | `-137.88` | `-157.85` | `-157.85` |
| SAC | 20,000 | `-132.35` | `-152.12` | `-174.82` | `-174.82` |

SAC stopped after the 20k non-improving validation:

```text
Stopping SAC: no rolling-validation improvement for 1 evals.
```

This confirms the early-stop control works for cheap screens and avoids the already-observed 30k deterioration pattern.

## Cost-Stress Evaluation

Cost-stress outputs are preserved under [rl_cost_stress/ultra3x_strict_seed41_1](../../../results/daily/2026-07-23/rl_cost_stress/ultra3x_strict_seed41_1/).

Summary CSV: [cost_stress_summary.csv](../../../results/daily/2026-07-23/rl_cost_stress/ultra3x_strict_seed41_1/cost_stress_summary.csv)

Promotion input CSV: [ultra3x_strict_seed41_promotion_input.csv](../../../results/daily/2026-07-23/rl_cost_stress/ultra3x_strict_seed41_1/ultra3x_strict_seed41_promotion_input.csv)

| Cost profile | Fee | Slippage | Return | Sharpe | Max drawdown | Cost-bearing steps | Trade events | Evidence |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| live_like_1x | `0.0012` | `0.0018` | `452.01%` | `2.0726` | `-19.22%` | `6,493` | `64` | `ABSTAIN` |
| live_like_2x | `0.0024` | `0.0036` | `59.22%` | `0.6485` | `-31.89%` | `6,715` | `49` | `ABSTAIN` |
| live_like_3x | `0.0036` | `0.0054` | `-35.20%` | `-0.7543` | `-48.51%` | `6,498` | `44` | `ABSTAIN` |

Evidence envelopes:

- [live_like_1x/rl_evidence.json](../../../results/daily/2026-07-23/rl_cost_stress/ultra3x_strict_seed41_1/ultra3x_strict_seed41/live_like_1x/rl_evidence.json)
- [live_like_2x/rl_evidence.json](../../../results/daily/2026-07-23/rl_cost_stress/ultra3x_strict_seed41_1/ultra3x_strict_seed41/live_like_2x/rl_evidence.json)
- [live_like_3x/rl_evidence.json](../../../results/daily/2026-07-23/rl_cost_stress/ultra3x_strict_seed41_1/ultra3x_strict_seed41/live_like_3x/rl_evidence.json)

## Comparison to Severe3x-Strict Seed 41

| Profile | Ultra return | Severe return | Delta | Ultra Sharpe | Severe Sharpe | Sharpe delta | Drawdown delta |
|---|---:|---:|---:|---:|---:|---:|---:|
| live_like_1x | `452.01%` | `418.39%` | `+33.62 pp` | `2.0726` | `1.9713` | `+0.1013` | `+1.57 pp` |
| live_like_2x | `59.22%` | `66.15%` | `-6.93 pp` | `0.6485` | `0.6806` | `-0.0321` | `+1.67 pp` |
| live_like_3x | `-35.20%` | `-38.46%` | `+3.26 pp` | `-0.7543` | `-0.8037` | `+0.0493` | `+1.32 pp` |

Interpretation: the stricter cap/reward regime improved 1x and 3x return/drawdown versus the previous severe run, while giving back some 2x return. It still does not solve 3x, but the direction suggests severe-cost robustness is responding to stronger action regularization.

The warning sign is cost-bearing steps: `6,498` at 3x versus `4,679` in the previous severe run. The policy may be making many smaller capped adjustments rather than truly staying out of the market. The next improvement should reduce cost-bearing step frequency, not just cap each step.

## Promotion Gate

Promotion-gate outputs are preserved under [rl_promotion_gate/ultra3x_strict_seed41_1](../../../results/daily/2026-07-23/rl_promotion_gate/ultra3x_strict_seed41_1/).

- [promotion_gate_report.json](../../../results/daily/2026-07-23/rl_promotion_gate/ultra3x_strict_seed41_1/promotion_gate_report.json)
- [promotion_gate_summary.csv](../../../results/daily/2026-07-23/rl_promotion_gate/ultra3x_strict_seed41_1/promotion_gate_summary.csv)

Blocking failures:

| Gate | Observed | Threshold |
|---|---:|---:|
| `min_seed_count` | `1` seed | `>= 5` |
| `severe_return_all_seeds` | `-35.20%` at 3x | `>= 0.0%` |
| `severe_sharpe_all_seeds` | `-0.7543` at 3x | `>= 0.0` |
| `all_evidence_verified` | `ABSTAIN` | `VERIFIED` |
| `all_artifacts_marked_promoted` | `0 / 2` rows promoted | all rows promoted |

Passing gates:

- required 2x and 3x profiles present;
- required metrics complete;
- operating 2x return positive;
- operating 2x Sharpe positive;
- operating 2x drawdown within the `-40%` gate.

## Lessons

1. Early stopping should remain enabled for cheap RL screens; it saved the selected SAC checkpoint and avoided a known bad later checkpoint.
2. Stronger action regularization continues to move 3x in the right direction, but not enough for promotion.
3. The next improvement should target cost-bearing step frequency explicitly. Candidate implementation: a deadband or minimum-edge no-trade gate that keeps weights unchanged unless the policy asks for a materially better allocation.
4. The LLM-agent contract stays fail-closed: `ABSTAIN` only.

## Verification

Completed checks:

- `python -m pytest tests/test_train_hygiene.py -q`: `15 passed, 1 warning`
- Training completed for PPO and SAC.
- SAC early stopped at 20k after a non-improving validation.
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
