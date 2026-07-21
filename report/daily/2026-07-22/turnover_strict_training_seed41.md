# Turnover-Strict RL Training and Evaluation: Seed 41

**Date:** 2026-07-22

**Status:** Evaluated; promising single-seed challenger, not promoted

**Code commit:** `c8bdf00634b4f018c525f42a35a7cf7f1dc1085a`

## Executive decision

The turnover-strict challenger is the first evaluated variant in this session to survive doubled live-like costs.

It should not be promoted to LLM-agent evidence yet because it is still a single seed, fails 3x cost stress, and all promotion/statistical/calibration/prospective gates remain missing. However, it is strong enough to become the next multi-seed screen candidate.

The important change is not just a higher 1x backtest. The 2x cost-stress result moved from negative to positive:

- Prior cost-aware seed 41 at 2x: `-9.91%` return, `-0.1323` Sharpe.
- Turnover-strict seed 41 at 2x: `59.73%` return, `0.5944` Sharpe.

## What changed

Code changes were committed and pushed before this run so result provenance points to the implementation actually used.

Implemented:

1. Per-environment reward overrides for:
   - turnover penalty weight;
   - action-delta penalty weight;
   - action-delta deadband;
   - action-delta scale.
2. Per-environment step-turnover-cap overrides for training and rolling validation.
3. `train.py` CLI flags for the reward and turnover-cap controls.
4. `backtest.py` CLI flags for step-turnover-cap controls.
5. `scripts/run_rl_cost_stress.py` forwarding for those backtest controls.

Focused tests passed before training:

```text
59 passed, 1 warning
```

## Training setup

Training artifacts are preserved under [results/daily/2026-07-22/turnover_strict_model_seed41_1/](../../../results/daily/2026-07-22/turnover_strict_model_seed41_1/).

Training command is preserved in [training_command.txt](../../../results/daily/2026-07-22/turnover_strict_model_seed41_1/training_command.txt).

Key settings:

| Setting | Value |
|---|---:|
| Seed | `41` |
| Algorithms | PPO, SAC |
| Requested timesteps | `30,000` |
| Training fee/slippage | `0.0024 / 0.0036` |
| Validation profiles | `nominal`, `stress2x` |
| Checkpoint selection score | worst profile mean reward |
| Reward turnover weight | `8.0` |
| Reward action-delta weight | `0.5` |
| Reward action-delta deadband | `0.0` |
| Reward action-delta scale | `1.0` |
| Step turnover cap | enabled |
| Normal/stress/crisis cap | `0.12 / 0.08 / 0.05` |

Preserved validation logs:

- [ppo_rolling_validation_metrics.csv](../../../results/daily/2026-07-22/turnover_strict_model_seed41_1/ppo_rolling_validation_metrics.csv)
- [sac_rolling_validation_metrics.csv](../../../results/daily/2026-07-22/turnover_strict_model_seed41_1/sac_rolling_validation_metrics.csv)
- [training_stderr.log](../../../results/daily/2026-07-22/turnover_strict_model_seed41_1/training_stderr.log)

Best model artifacts:

- [models/PPO/ppo_best.zip](../../../results/daily/2026-07-22/turnover_strict_model_seed41_1/models/PPO/ppo_best.zip)
- [models/SAC/sac_best.zip](../../../results/daily/2026-07-22/turnover_strict_model_seed41_1/models/SAC/sac_best.zip)

## Validation observations

The rolling-validation rewards did not predict the size of the backtest improvement. PPO was roughly flat versus the prior cost-aware challenger; SAC again selected the first checkpoint and deteriorated afterward.

| Algorithm | Step | Nominal mean reward | Stress2x mean reward | Selection score |
|---|---:|---:|---:|---:|
| PPO | 20,000 | `-98.45` | `-114.40` | `-114.40` |
| SAC | 10,000 | `-100.50` | `-117.99` | `-117.99` |
| SAC | 20,000 | `-105.75` | `-129.31` | `-129.31` |
| SAC | 30,000 | `-109.27` | `-135.12` | `-135.12` |

Lesson: the validation reward ranking still helps avoid worse later checkpoints, but reward scale alone is not enough to decide promotion. Cost-stress backtesting remains necessary.

## Cost-stress evaluation

Cost-stress outputs are preserved under [results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed41_1/](../../../results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed41_1/).

Summary CSV: [cost_stress_summary.csv](../../../results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed41_1/cost_stress_summary.csv)

Evaluation command is preserved in [evaluation_command.txt](../../../results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed41_1/evaluation_command.txt).

| Cost profile | Fee | Slippage | Return | Sharpe | Max drawdown | Cost-bearing steps | Trade events | Evidence |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| live_like_1x | `0.0012` | `0.0018` | `481.56%` | `1.9833` | `-23.25%` | `3,697` | `65` | `ABSTAIN` |
| live_like_2x | `0.0024` | `0.0036` | `59.73%` | `0.5944` | `-35.28%` | `3,596` | `55` | `ABSTAIN` |
| live_like_3x | `0.0036` | `0.0054` | `-40.46%` | `-0.7857` | `-53.03%` | `3,346` | `48` | `ABSTAIN` |

Evidence envelopes:

- [live_like_1x/rl_evidence.json](../../../results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed41_1/turnover_strict_seed41/live_like_1x/rl_evidence.json)
- [live_like_2x/rl_evidence.json](../../../results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed41_1/turnover_strict_seed41/live_like_2x/rl_evidence.json)
- [live_like_3x/rl_evidence.json](../../../results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed41_1/turnover_strict_seed41/live_like_3x/rl_evidence.json)

All evidence envelopes remain `ABSTAIN` because promotion, causal-integrity, statistical, calibration, and prospective-shadow gates are not passed. This is correct fail-closed behavior for LLM agents.

## Comparison against prior candidates

| Cost profile | Turnover-strict return | Prior 3-seed mean | Prior best | Prior cost-aware seed 41 | Delta vs 3-seed mean | Delta vs cost-aware |
|---|---:|---:|---:|---:|---:|---:|
| live_like_1x | `481.56%` | `183.65%` | `201.36%` | `227.34%` | `+297.90 pp` | `+254.22 pp` |
| live_like_2x | `59.73%` | `-20.26%` | `-16.35%` | `-9.91%` | `+79.99 pp` | `+69.64 pp` |
| live_like_3x | `-40.46%` | `-68.31%` | `-63.95%` | `-62.09%` | `+27.85 pp` | `+21.63 pp` |

Sharpe improved materially against the previous cost-aware seed:

| Cost profile | Turnover-strict Sharpe | Cost-aware Sharpe | Delta |
|---|---:|---:|---:|
| live_like_1x | `1.9833` | `1.3082` | `+0.6751` |
| live_like_2x | `0.5944` | `-0.1323` | `+0.7266` |
| live_like_3x | `-0.7857` | `-1.3524` | `+0.5667` |

## Turnover diagnostics

The strategy still creates many cost-bearing steps, but total turnover and cost damage are lower than the previous cost-aware run. The cap is mostly cutting large reallocations rather than reducing the number of nonzero-cost steps.

| Cost profile | Total turnover | Mean turnover | Transaction-cost sum | Cap applied rate | Mean cap before | Mean cap after |
|---|---:|---:|---:|---:|---:|---:|
| live_like_1x | `480.45` | `0.0226` | `1.4414` | `13.39%` | `0.0441` | `0.0129` |
| live_like_2x | `393.95` | `0.0186` | `2.3637` | `13.92%` | `0.0379` | `0.0104` |
| live_like_3x | `306.08` | `0.0144` | `2.7547` | `13.58%` | `0.0311` | `0.0075` |

Prior cost-aware seed 41 turnover for comparison:

| Cost profile | Total turnover | Mean turnover | Transaction-cost sum | Cap applied rate |
|---|---:|---:|---:|---:|
| live_like_1x | `603.13` | `0.0284` | `1.8094` | `0.00%` |
| live_like_2x | `474.88` | `0.0224` | `2.8493` | `0.00%` |
| live_like_3x | `377.38` | `0.0178` | `3.3964` | `0.00%` |

## Interpretation

This run supports the next-step hypothesis from the previous report: explicit turnover/action regularization plus deterministic step caps can materially improve stressed-cost robustness.

However, it does not prove reliability:

1. It is one seed only.
2. 3x costs still lose money.
3. The 2024-2026 backtest window remains research history, not a sealed holdout.
4. Evidence remains `ABSTAIN`.
5. Validation reward still deteriorates with more SAC training.

## Recommended next step

Run a three-seed turnover-strict screen using seeds `41`, `42`, and `43` with the same controls:

- train `30,000` cheap-screen timesteps;
- use validation profiles `nominal` and `stress2x`;
- keep `--validation-score-mode worst_profile_mean`;
- keep step turnover caps `0.12 / 0.08 / 0.05`;
- require positive 2x return for every seed before considering a larger promotion run.

If all three seeds survive 2x, then run a larger promotion candidate with at least five to ten seeds, DSR/PBO/interval reporting, and prospective shadow evidence.

## Completion checklist

- Report stored under `report/daily/2026-07-22/`.
- Training artifacts and validation logs preserved under `results/daily/2026-07-22/`.
- Cost-stress outputs and evidence envelopes preserved under `results/daily/2026-07-22/`.
- Relative links in this report are intended to resolve from this report location.
- No `.env`, credentials, virtual environments, or external source clones are referenced or stored by this report.
