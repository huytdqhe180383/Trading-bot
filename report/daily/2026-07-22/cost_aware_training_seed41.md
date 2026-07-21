# Cost-Aware RL Training and Evaluation: Seed 41

**Date:** 2026-07-22

**Status:** Evaluated; not promoted

**Code commit:** `6dc97eff28ebf60780dd64ad32f4e72d7578098c`

## Executive decision

The cost-aware challenger is better than the prior seed screen under stressed costs, but it is still not reliable enough to become an LLM-agent source.

It improved the live-like 1x result to `227.34%` return with `1.3082` Sharpe, and softened the 2x cost failure from the old three-seed mean of `-20.26%` to `-9.91%`. However, the model still loses money at 2x costs and collapses at 3x costs. All LLM-facing evidence envelopes correctly remain `ABSTAIN`.

Do not promote this model. The next improvement should target explicit turnover/risk constraints, not simply heavier training costs.

## Why this run was performed

The research plan in [RL Reliability Research and LLM Evidence Plan](../../important/rl_reliability_research_and_llm_evidence_plan.md) argues that an RL model should not become agent-trustworthy from a single backtest or seed. The immediate engineering lesson from the cost-stress screen was that the previous nominal challengers were too fragile to realistic cost changes.

This run tested whether training and selecting checkpoints against a stressed validation profile would produce a materially more robust challenger before spending on a larger multi-seed sweep.

## Training setup

Artifacts are preserved under [results/daily/2026-07-22/cost_aware_model_seed41_1/](../../../results/daily/2026-07-22/cost_aware_model_seed41_1/).

Training command:

```powershell
train.py --algo ALL --timesteps 50000 --device cpu --seed 41 --validation-fraction 0.2 --validation-windows 5 --validation-cost-profiles nominal:0.0012:0.0018,stress2x:0.0024:0.0036 --validation-score-mode worst_profile_mean --training-fee 0.0024 --training-slippage 0.0036 --models-dir "K:\BTC-ETH Trading\results\daily\2026-07-22\cost_aware_model_seed41_1\models" --skip-backtest
```

Configuration:

| Setting | Value |
|---|---:|
| Seed | `41` |
| Algorithms | PPO, SAC |
| Requested timesteps | `50,000` |
| Training fee/slippage | `0.0024 / 0.0036` |
| Validation profiles | `nominal`, `stress2x` |
| Checkpoint selection score | worst profile mean reward |
| Validation windows | `5` rolling windows |

Preserved validation logs:

- [ppo_rolling_validation_metrics.csv](../../../results/daily/2026-07-22/cost_aware_model_seed41_1/ppo_rolling_validation_metrics.csv)
- [sac_rolling_validation_metrics.csv](../../../results/daily/2026-07-22/cost_aware_model_seed41_1/sac_rolling_validation_metrics.csv)
- [training_stderr.log](../../../results/daily/2026-07-22/cost_aware_model_seed41_1/training_stderr.log)

Best model artifacts:

- [models/PPO/ppo_best.zip](../../../results/daily/2026-07-22/cost_aware_model_seed41_1/models/PPO/ppo_best.zip)
- [models/SAC/sac_best.zip](../../../results/daily/2026-07-22/cost_aware_model_seed41_1/models/SAC/sac_best.zip)

## Training observations

PPO selected its first validation checkpoint. Later PPO validation did not improve the stress profile.

| PPO step | Nominal mean reward | Stress2x mean reward | Selection score |
|---:|---:|---:|---:|
| 20,000 | `-94.06` | `-114.28` | `-114.28` |
| 40,000 | `-94.20` | `-116.56` | `-116.56` |
| 60,000 | `-95.14` | `-119.79` | `-119.79` |

SAC also selected its first validation checkpoint. Its stress2x score deteriorated as training continued.

| SAC step | Nominal mean reward | Stress2x mean reward | Selection score |
|---:|---:|---:|---:|
| 10,000 | `-94.21` | `-117.35` | `-117.35` |
| 20,000 | `-100.37` | `-130.31` | `-130.31` |
| 30,000 | `-104.88` | `-133.69` | `-133.69` |
| 40,000 | `-107.50` | `-139.79` | `-139.79` |
| 50,000 | `-104.11` | `-141.57` | `-141.57` |

This is a warning sign: cost-aware selection picked the least-bad early checkpoints, but the training objective still did not discover a durable stressed-cost policy.

## Cost-stress evaluation

Cost-stress outputs are preserved under [results/daily/2026-07-22/rl_cost_stress/cost_aware_seed41_1/](../../../results/daily/2026-07-22/rl_cost_stress/cost_aware_seed41_1/).

Summary CSV: [cost_stress_summary.csv](../../../results/daily/2026-07-22/rl_cost_stress/cost_aware_seed41_1/cost_stress_summary.csv)

| Cost profile | Fee | Slippage | Return | Sharpe | Max drawdown | Cost-bearing steps | Trade events | Evidence |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| live_like_1x | `0.0012` | `0.0018` | `227.34%` | `1.3082` | `-31.39%` | `1,648` | `59` | `ABSTAIN` |
| live_like_2x | `0.0024` | `0.0036` | `-9.91%` | `-0.1323` | `-45.85%` | `1,362` | `56` | `ABSTAIN` |
| live_like_3x | `0.0036` | `0.0054` | `-62.09%` | `-1.3524` | `-64.54%` | `1,156` | `55` | `ABSTAIN` |

Evidence envelopes:

- [live_like_1x/rl_evidence.json](../../../results/daily/2026-07-22/rl_cost_stress/cost_aware_seed41_1/cost_aware_seed41/live_like_1x/rl_evidence.json)
- [live_like_2x/rl_evidence.json](../../../results/daily/2026-07-22/rl_cost_stress/cost_aware_seed41_1/cost_aware_seed41/live_like_2x/rl_evidence.json)
- [live_like_3x/rl_evidence.json](../../../results/daily/2026-07-22/rl_cost_stress/cost_aware_seed41_1/cost_aware_seed41/live_like_3x/rl_evidence.json)

All three envelopes have `status: ABSTAIN` because promotion, causal-integrity, statistical, calibration, and prospective-shadow gates are not passed. This is correct fail-closed behavior for LLM agents.

## Comparison against previous three-seed cost-stress screen

Baseline comparison source: [seed_41_42_43_x1_x2_x3/cost_stress_summary.csv](../../../results/daily/2026-07-22/rl_cost_stress/seed_41_42_43_x1_x2_x3/cost_stress_summary.csv)

| Cost profile | New return | Old mean return | Old best return | Delta vs old mean | Delta vs old best | New Sharpe | Old mean Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|
| live_like_1x | `227.34%` | `183.65%` | `201.36%` | `+43.69 pp` | `+25.98 pp` | `1.3082` | `1.1951` |
| live_like_2x | `-9.91%` | `-20.26%` | `-16.35%` | `+10.35 pp` | `+6.44 pp` | `-0.1323` | `-0.2931` |
| live_like_3x | `-62.09%` | `-68.31%` | `-63.95%` | `+6.22 pp` | `+1.86 pp` | `-1.3524` | `-1.6083` |

The result is directionally useful but not promotion-grade. It reduced cost sensitivity and turnover, but the improvement is not large enough to survive doubled live-like costs.

## Implementable lessons

1. Keep the cost-stress gate. It caught a model that would look attractive at 1x costs but should not be trusted by agents.
2. Cost-aware validation is useful, but insufficient alone. It helped selection avoid later, worse checkpoints; it did not produce a robust policy.
3. Add a direct turnover/action-change objective. The stressed run reduced cost-bearing steps, but not enough. The reward should expose net economic return and a transparent turnover term instead of relying on cost randomization alone.
4. Require stressed-cost profitability before multi-seed promotion. A candidate that loses at 2x costs should not consume a full promotion sweep unless it is part of a deliberate ablation.
5. Preserve fail-closed LLM evidence. The evidence artifact must remain `ABSTAIN` until promotion, statistical, calibration, and prospective-shadow gates are actually satisfied.

## Recommended next implementation

Do not immediately train more seeds of this exact setup. The next challenger should change the objective and action regularization:

1. Split reward telemetry into economic net log return, turnover penalty, drawdown penalty, and tail penalty columns.
2. Add an explicit action-delta or total-variation penalty that is tuned against 2x cost validation.
3. Add a validation gate that requires non-negative 2x return in addition to worst-profile reward ranking.
4. Train one cheap seed and rerun this same 1x/2x/3x screen.
5. Only if that single seed survives 2x costs, run the three-to-five seed screen.

## Completion checklist

- Report stored under `report/daily/2026-07-22/`.
- Training artifacts and validation logs preserved under `results/daily/2026-07-22/`.
- Cost-stress outputs and evidence envelopes preserved under `results/daily/2026-07-22/`.
- Relative links in this report are intended to resolve from this report location.
- No `.env`, credentials, virtual environments, or external source clones are referenced or stored by this report.
