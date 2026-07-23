# Turnover-Strict RL Multi-Seed Screen: Seeds 41, 42, 43

**Date:** 2026-07-22

**Status:** Three-seed cheap screen passed at 2x costs; not promoted to LLM-agent evidence

**Primary implementation commit:** `c8bdf00634b4f018c525f42a35a7cf7f1dc1085a`

**Report/evaluator follow-up commit:** `c6af25e19c18c8cfcf15d8a632d4d3c2c331a493`

## Executive decision

The turnover-strict challenger survived the intended three-seed cheap screen at doubled live-like costs. Seeds `41`, `42`, and `43` all produced positive 2x-cost returns with positive Sharpe.

It is still not reliable enough to expose as an executable or trusted directional source for LLM agents. Every evidence envelope remains `ABSTAIN`, all promotion gates remain false, and every seed still loses money at 3x live-like costs.

The correct agent-facing interpretation is:

- Use these results as research evidence only.
- Keep RL output fail-closed as `ABSTAIN`.
- Advance this configuration to a larger promotion screen, not production use.

## What was evaluated

Training used the turnover-strict configuration introduced in `c8bdf00`:

| Setting | Value |
|---|---:|
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

Seed `43` first attempted folder [turnover_strict_model_seed43_1](../../../results/daily/2026-07-22/turnover_strict_model_seed43_1/) is partial: PPO completed, SAC did not produce `sac_best.zip`. It is not used in this report. The complete seed `43` rerun is [turnover_strict_model_seed43_2](../../../results/daily/2026-07-22/turnover_strict_model_seed43_2/).

## Preserved artifacts

Training/model folders:

- [turnover_strict_model_seed41_1](../../../results/daily/2026-07-22/turnover_strict_model_seed41_1/)
- [turnover_strict_model_seed42_1](../../../results/daily/2026-07-22/turnover_strict_model_seed42_1/)
- [turnover_strict_model_seed43_2](../../../results/daily/2026-07-22/turnover_strict_model_seed43_2/)

Cost-stress folders:

- [turnover_strict_seed41_1](../../../results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed41_1/)
- [turnover_strict_seed42_1](../../../results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed42_1/)
- [turnover_strict_seed43_2](../../../results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed43_2/)

Aggregate CSVs:

- [turnover_strict_seed41_42_43_cost_stress_by_seed.csv](../../../results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed41_42_43_cost_stress_by_seed.csv)
- [turnover_strict_seed41_42_43_cost_stress_aggregate.csv](../../../results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed41_42_43_cost_stress_aggregate.csv)
- [turnover_strict_seed41_42_43_validation_checkpoints.csv](../../../results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed41_42_43_validation_checkpoints.csv)
- [turnover_strict_seed41_42_43_validation_best.csv](../../../results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed41_42_43_validation_best.csv)

## Rolling validation

Best selected checkpoints:

| Seed | Algo | Selected step | Nominal mean reward | Stress2x mean reward | Selection score |
|---:|---|---:|---:|---:|---:|
| 41 | PPO | `20,000` | `-98.45` | `-114.40` | `-114.40` |
| 41 | SAC | `10,000` | `-100.50` | `-117.99` | `-117.99` |
| 42 | PPO | `20,000` | `-101.03` | `-118.09` | `-118.09` |
| 42 | SAC | `10,000` | `-101.49` | `-119.28` | `-119.28` |
| 43 | PPO | `20,000` | `-99.72` | `-116.90` | `-116.90` |
| 43 | SAC | `10,000` | `-101.15` | `-118.88` | `-118.88` |

SAC degraded after 10k in every seed. This supports keeping rolling validation and early checkpoint selection. It also suggests a concrete next implementation path: either lower the SAC training budget for this configuration or add an early-stop rule once worst-profile validation degrades for consecutive checkpoints.

## Cost-stress results

Per-seed cost-stress summary:

| Seed | Profile | Return | Sharpe | Max drawdown | Trades | Evidence |
|---:|---|---:|---:|---:|---:|---|
| 41 | live_like_1x | `481.56%` | `1.9833` | `-23.25%` | `65` | `ABSTAIN` |
| 41 | live_like_2x | `59.73%` | `0.5944` | `-35.28%` | `55` | `ABSTAIN` |
| 41 | live_like_3x | `-40.46%` | `-0.7857` | `-53.03%` | `48` | `ABSTAIN` |
| 42 | live_like_1x | `496.40%` | `1.9889` | `-22.28%` | `66` | `ABSTAIN` |
| 42 | live_like_2x | `56.74%` | `0.5674` | `-35.43%` | `58` | `ABSTAIN` |
| 42 | live_like_3x | `-40.97%` | `-0.7872` | `-53.02%` | `49` | `ABSTAIN` |
| 43 | live_like_1x | `457.46%` | `1.9428` | `-23.26%` | `62` | `ABSTAIN` |
| 43 | live_like_2x | `61.02%` | `0.5998` | `-35.94%` | `54` | `ABSTAIN` |
| 43 | live_like_3x | `-41.55%` | `-0.8010` | `-52.89%` | `47` | `ABSTAIN` |

Aggregate profile summary:

| Profile | Mean return | Std return | Min return | Max return | Mean Sharpe | All seeds positive? |
|---|---:|---:|---:|---:|---:|---|
| live_like_1x | `478.47%` | `19.65 pp` | `457.46%` | `496.40%` | `1.9717` | yes |
| live_like_2x | `59.16%` | `2.20 pp` | `56.74%` | `61.02%` | `0.5872` | yes |
| live_like_3x | `-40.99%` | `0.54 pp` | `-41.55%` | `-40.46%` | `-0.7913` | no |

The 2x result is unusually stable across seeds. The 3x failure is also unusually stable. That is a clean research signal: the turnover-strict model has moved the robustness frontier, but the current policy is still not robust to severe cost stress.

## Evidence gates

All nine evidence envelopes report `ABSTAIN` and `promoted = false`.

Evidence paths:

- [seed41 live_like_1x](../../../results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed41_1/turnover_strict_seed41/live_like_1x/rl_evidence.json)
- [seed41 live_like_2x](../../../results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed41_1/turnover_strict_seed41/live_like_2x/rl_evidence.json)
- [seed41 live_like_3x](../../../results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed41_1/turnover_strict_seed41/live_like_3x/rl_evidence.json)
- [seed42 live_like_1x](../../../results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed42_1/turnover_strict_seed42/live_like_1x/rl_evidence.json)
- [seed42 live_like_2x](../../../results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed42_1/turnover_strict_seed42/live_like_2x/rl_evidence.json)
- [seed42 live_like_3x](../../../results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed42_1/turnover_strict_seed42/live_like_3x/rl_evidence.json)
- [seed43 live_like_1x](../../../results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed43_2/turnover_strict_seed43/live_like_1x/rl_evidence.json)
- [seed43 live_like_2x](../../../results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed43_2/turnover_strict_seed43/live_like_2x/rl_evidence.json)
- [seed43 live_like_3x](../../../results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed43_2/turnover_strict_seed43/live_like_3x/rl_evidence.json)

This fail-closed behavior is correct. LLM agents should receive no RL trade opinion from these envelopes until promotion, causal integrity, statistical, calibration, and prospective-shadow gates are actually passed.

## Evaluator fix

During seed 43 evaluation, colored `backtest.py` output added an ANSI reset suffix to the parsed session directory. The backtests completed, but the initial seed43 summary had blank metrics because the path parser included the terminal escape sequence.

Fixed in `c6af25e`:

- `scripts/run_rl_cost_stress.py` now strips ANSI control sequences before parsing backtest session paths.
- `scripts/run_rl_seed_screen.py` received the same defensive cleanup.
- Regression tests cover ANSI-suffixed session path logs.

The corrected seed 43 evaluator output is [cost_stress_summary.csv](../../../results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed43_2/cost_stress_summary.csv), with backtest sessions `27`, `28`, and `29`.

## Lessons to implement

1. Keep turnover and action-delta regularization. This is the first evaluated configuration to pass all three seeds at 2x live-like costs.
2. Keep deterministic step-turnover caps in training, validation, and backtesting. The stable 2x result suggests caps are doing useful risk-budget work.
3. Add a SAC early-stop or smaller SAC budget for this configuration. Across all seeds, SAC selected 10k and degraded at later checkpoints.
4. Do not promote on backtest profit alone. The model still fails 3x and lacks calibration/prospective evidence.
5. Make the next promotion screen stricter and larger: at least 5-10 seeds, sealed holdout or walk-forward split, DSR/PBO/statistical interval reporting, calibration coverage, causal-integrity checks, and prospective shadow results.
6. Keep LLM integration fail-closed. Until the evidence builder emits a non-`ABSTAIN` envelope through explicit gates, agents should treat RL as no opinion.

## Recommended next step

Advance this exact turnover-strict configuration to a promotion candidate, but do not expose it to agents yet.

Minimum promotion-gate proposal:

| Gate | Required threshold |
|---|---|
| Multi-seed stability | At least 5-10 seeds |
| 2x live-like cost | Positive return and positive Sharpe for every seed |
| 3x severe cost | Non-negative mean return, or explicitly classify as outside operating envelope |
| Drawdown | Predefined max drawdown cap by profile |
| Statistical evidence | DSR/PBO/interval gates pass |
| Calibration | Trailing coverage or conformal interval available and passing |
| Prospective shadow | Passes a sealed shadow period before any agent-visible promotion |
| Agent contract | Evidence envelope remains machine-readable and fail-closed |

## Verification

Completed checks:

- `python -m pytest tests/test_rl_cost_stress.py tests/test_rl_seed_screen.py -q`: `11 passed, 1 warning`
- `python -m pytest tests/test_train_hygiene.py -q`: `14 passed, 1 warning`
- `python -m pytest tests/test_backtest_session_outputs.py -q`: `25 passed, 1 warning`
- Markdown link check: `22` links resolved
- Sensitive-output scan: `29` text files scanned, no secret patterns found
- Seed 43 complete model artifacts verified: `models/PPO/ppo_best.zip`, `models/SAC/sac_best.zip`
- Seed 43 validation CSVs copied to the preserved result folder
- Cost-stress aggregate CSVs written under `results/daily/2026-07-22/`

Inconclusive checks:

- A combined focused run including `tests/test_audit_hotfixes.py` was stopped after staying CPU-active for more than 30 minutes with no pytest output.
- A standalone `tests/test_audit_hotfixes.py -q` run was also stopped after staying CPU-active for a long silent run. No failure output was produced, but it is not counted as passing in this report.

Remaining before final session close:

- Commit and push this report plus trackable artifacts.

## Completion checklist

- Report stored under `report/daily/2026-07-22/`.
- Preserved outputs stored under `results/daily/2026-07-22/`.
- Markdown links should resolve from this report location.
- No `.env`, credentials, virtual environments, or external source clones are referenced or stored by this report.
