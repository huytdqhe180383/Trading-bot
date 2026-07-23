# Hold-gate 3x strict RL challenger, seed 41

Date: 2026-07-23  
Implementation commit for evaluation: `fcf327099d01538573fe6e9bfdd27807ce7d898f`

## Outcome

The new hold-gate challenger improved severe-cost robustness, but it is still **not reliable enough for LLM-agent use**.

- Promotion gate: `NOT_PROMOTED`
- LLM evidence status: `ABSTAIN`
- Main blocker: severe 3x cost profile remains negative, only one seed was tested, and evidence envelopes are still abstained/unpromoted.

## What changed

The previous ultra-strict model reduced per-rebalance size but still generated too many cost-bearing adjustments. This run added trainable execution controls so training and validation can experience the same low-churn execution policy used in production-style `step_weights()`:

- Per-env rebalance deadbands: normal `0.08`, stress `0.12`, crisis `0.18`
- Minimum material-trade hold: `8` bars
- Material trade threshold: `0.10`
- Reversal hysteresis multiplier: `2.0`
- Existing per-step turnover caps retained: normal `0.05`, stress `0.03`, crisis `0.02`
- Training costs: fee `0.0036`, slippage `0.0054`
- Validation selection: worst profile mean across nominal, 2x, and severe 3x costs

Code changes:

- `environment/trading_env.py`: execution deadband/cooldown/hysteresis are now per environment instance and used by both `step()` and `step_weights()`.
- `train.py`: training CLI can pass execution hold-gate settings into training and rolling validation, and forwards them to post-training backtests.
- `scripts/run_rl_cost_stress.py`: cost-stress sweeps forward the same hold-gate settings to `backtest.py`.

## Training validation

Preserved artifacts:

- Model directory: `../../../results/daily/2026-07-23/holdgate3x_strict_model_seed41_1/models/`
- Validation summary: `../../../results/daily/2026-07-23/holdgate3x_strict_model_seed41_1/validation/validation_selection_summary.csv`
- PPO rolling validation: `../../../results/daily/2026-07-23/holdgate3x_strict_model_seed41_1/validation/ppo_rolling_validation_metrics.csv`
- SAC rolling validation: `../../../results/daily/2026-07-23/holdgate3x_strict_model_seed41_1/validation/sac_rolling_validation_metrics.csv`

| Algo | Selected/checkpoint evidence | Mean validation reward | Worst-profile selection score |
|---|---:|---:|---:|
| PPO | 20,000 steps | -105.4081 | -114.5732 |
| SAC | 10,000 steps | -103.5472 | -113.4660 |
| SAC | 20,000 steps | -124.3047 | -137.4831 |

SAC early-stopped after the 20k validation worsened; the selected SAC best checkpoint is the 10k model.

## Cost-stress results

Preserved artifacts:

- Cost-stress summary: `../../../results/daily/2026-07-23/rl_cost_stress/holdgate3x_strict_seed41_2/cost_stress_summary.csv`
- Promotion input: `../../../results/daily/2026-07-23/rl_promotion_gate/holdgate3x_strict_seed41_2/cost_stress_by_seed.csv`
- Promotion gate report: `../../../results/daily/2026-07-23/rl_promotion_gate/holdgate3x_strict_seed41_2/promotion_gate_report.json`
- Promotion gate summary: `../../../results/daily/2026-07-23/rl_promotion_gate/holdgate3x_strict_seed41_2/promotion_gate_summary.csv`

| Cost profile | Total return | Sharpe | Max drawdown | Cost-bearing steps | Trade events | Evidence |
|---|---:|---:|---:|---:|---:|---|
| live_like_1x | 346.9161% | 2.1715 | -18.1486% | 4,639 | 78 | ABSTAIN |
| live_like_2x | 53.4159% | 0.7316 | -26.9165% | 4,514 | 61 | ABSTAIN |
| live_like_3x | -19.3287% | -0.4880 | -38.2524% | 4,148 | 49 | ABSTAIN |

Compared with the previous `ultra3x_strict_seed41` challenger, severe 3x improved materially:

- Severe 3x return: `-35.1975%` -> `-19.3287%`
- Severe 3x Sharpe: `-0.7543` -> `-0.4880`
- Severe 3x max drawdown: `-48.5059%` -> `-38.2524%`
- Severe 3x cost-bearing steps: `6,498` -> `4,148`

The tradeoff is lower upside in easier profiles:

- 1x return declined from `452.0083%` to `346.9161%`
- 2x return declined from `59.2246%` to `53.4159%`

That is an acceptable direction for reliability work, but the severe profile still fails promotion.

## Promotion gate

Final gate status: `NOT_PROMOTED`  
Final LLM evidence status: `ABSTAIN`

Blocking failures:

- `min_seed_count`: only seed 41 was evaluated; threshold is at least 5 seeds.
- `severe_return_all_seeds`: severe 3x return was `-19.3287%`, below the `>= 0%` threshold.
- `severe_sharpe_all_seeds`: severe 3x Sharpe was `-0.4880`, below the `>= 0` threshold.
- `all_evidence_verified`: evidence envelopes were `ABSTAIN`, not `VERIFIED`.
- `all_artifacts_marked_promoted`: evidence artifacts were not marked promoted.

LLM-agent instruction: keep treating RL as **no opinion**. Do not let LLM agents infer trades, allocations, quantities, or leverage from this model.

## Verification

Passed:

- `python -m py_compile environment/trading_env.py train.py scripts/run_rl_cost_stress.py`
- `pytest tests/test_train_hygiene.py tests/test_rl_cost_stress.py -q` -> `20 passed`
- Direct environment reproduction confirmed:
  - constructor deadband override blocks a `0.08` target rebalance when normal threshold is `0.10`
  - training `step()` applies the constructor cooldown override and blocks a second material rebalance
- Full training completed for PPO and SAC.
- Full cost-stress sweep completed for 1x, 2x, and 3x profiles.
- Promotion gate completed and failed closed as expected.

Blocked/limited:

- `tests/test_audit_hotfixes.py` could not be run under the Codex bundled Python because module-level `data.live_feed` import hung. The new environment behavior was verified with a direct isolated reproduction instead.

## Next implementation lesson

The hold gate moved the right variable: fewer cost-bearing steps and much better severe drawdown. The next round should keep this execution-control family and focus on making severe 3x non-negative without throwing away the now-acceptable 2x profile.

Recommended next experiment:

1. Run the same hold-gate configuration across at least seeds `41, 42, 43, 44, 45`.
2. Add a severe-cost cash-bias objective: reward surviving severe-cost regimes with cash preservation rather than forcing risk-on participation.
3. Add a “do nothing is valid” action prior or explicit abstain/hold reward so the policy learns not to rebalance into low-edge states.
4. Gate on 2x as operating profile and 3x as fail-safe profile before exposing any RL evidence to LLM agents.
