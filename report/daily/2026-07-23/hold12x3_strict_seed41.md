# Hold-12 strict low-churn RL challenger, seed 41

Date: 2026-07-23  
Evaluation code commit: `b86992c51bf92d9443efc93922784dfa01b7f5b8`

## Outcome

This challenger is **not promoted**, but it is the best external cost-stress result so far in the hold-gate family.

- Promotion gate: `NOT_PROMOTED`
- LLM evidence status: `ABSTAIN`
- Main blocker: severe 3x return and Sharpe remain negative, and only one seed was evaluated.

The useful signal: stricter execution controls improved operating 2x and severe 3x external performance versus the previous hold-gate-only challenger.

## Experiment

This run removed the cash-preservation reward shaping that regressed externally and tested stricter execution-only low-churn controls.

Training settings:

- Training fee/slippage: `0.0036` / `0.0054`
- Validation profiles: nominal, 2x, severe 3x
- Validation score: worst-profile mean
- Reward turnover weight: `25.0`
- Action-delta penalty: `2.5`
- No cash-buffer reward override
- No risk-exposure reward override
- No missed-opportunity override

Execution controls:

- Rebalance thresholds normal/stress/crisis: `0.10` / `0.15` / `0.22`
- Min hold bars: `12`
- Material trade threshold: `0.12`
- Reversal hysteresis multiplier: `2.5`
- Turnover caps normal/stress/crisis: `0.04` / `0.025` / `0.015`

## Training validation

Preserved artifacts:

- Model directory: `../../../results/daily/2026-07-23/hold12x3_strict_model_seed41_1/models/`
- Validation summary: `../../../results/daily/2026-07-23/hold12x3_strict_model_seed41_1/validation/validation_selection_summary.csv`
- PPO rolling validation: `../../../results/daily/2026-07-23/hold12x3_strict_model_seed41_1/validation/ppo_rolling_validation_metrics.csv`
- SAC rolling validation: `../../../results/daily/2026-07-23/hold12x3_strict_model_seed41_1/validation/sac_rolling_validation_metrics.csv`

| Algo | Timesteps | Mean validation reward | Worst-profile selection score |
|---|---:|---:|---:|
| PPO | 20,000 | -105.6719 | -116.4816 |
| SAC | 10,000 | -101.7625 | -115.1811 |
| SAC | 20,000 | -124.5700 | -133.8826 |

SAC selected the 10k checkpoint; 20k worsened and triggered early stop.

## External cost-stress results

Preserved artifacts:

- Cost-stress summary: `../../../results/daily/2026-07-23/rl_cost_stress/hold12x3_strict_seed41_1/cost_stress_summary.csv`
- Promotion input: `../../../results/daily/2026-07-23/rl_promotion_gate/hold12x3_strict_seed41_1/cost_stress_by_seed.csv`
- Promotion gate report: `../../../results/daily/2026-07-23/rl_promotion_gate/hold12x3_strict_seed41_1/promotion_gate_report.json`
- Promotion gate summary: `../../../results/daily/2026-07-23/rl_promotion_gate/hold12x3_strict_seed41_1/promotion_gate_summary.csv`

| Cost profile | Total return | Sharpe | Max drawdown | Cost-bearing steps | Trade events | Evidence |
|---|---:|---:|---:|---:|---:|---|
| live_like_1x | 214.6796% | 2.1349 | -16.3875% | 4,339 | 87 | ABSTAIN |
| live_like_2x | 74.9134% | 1.1251 | -21.1474% | 3,961 | 109 | ABSTAIN |
| live_like_3x | -16.0124% | -0.5769 | -32.3859% | 3,262 | 26 | ABSTAIN |

Compared with the previous best hold-gate-only challenger:

| Profile | Previous return | Hold-12 return | Previous Sharpe | Hold-12 Sharpe | Previous max DD | Hold-12 max DD |
|---|---:|---:|---:|---:|---:|---:|
| live_like_1x | 346.9161% | 214.6796% | 2.1715 | 2.1349 | -18.1486% | -16.3875% |
| live_like_2x | 53.4159% | 74.9134% | 0.7316 | 1.1251 | -26.9165% | -21.1474% |
| live_like_3x | -19.3287% | -16.0124% | -0.4880 | -0.5769 | -38.2524% | -32.3859% |

Interpretation:

- The stricter hold gate improved 2x return, 2x Sharpe, 2x drawdown, severe 3x return, and severe 3x drawdown.
- It sacrificed 1x upside, which is acceptable for reliability work.
- Severe 3x Sharpe worsened slightly and remains negative, so this is not a promotion candidate yet.
- Severe 3x cost-bearing steps dropped from `4,148` to `3,262`, and trade events dropped from `49` to `26`.

## Promotion gate

Final gate status: `NOT_PROMOTED`  
Final LLM evidence status: `ABSTAIN`

Blocking failures:

- `min_seed_count`: only seed 41 was evaluated; threshold is at least 5 seeds.
- `severe_return_all_seeds`: severe 3x return was `-16.0124%`, below the `>= 0%` threshold.
- `severe_sharpe_all_seeds`: severe 3x Sharpe was `-0.5769`, below the `>= 0` threshold.
- `all_evidence_verified`: evidence envelopes were `ABSTAIN`, not `VERIFIED`.
- `all_artifacts_marked_promoted`: evidence artifacts were not marked promoted.

LLM-agent instruction: continue treating RL as **no opinion**.

## Verification

Passed:

- Full PPO/SAC training completed.
- Full 1x/2x/3x cost-stress sweep completed.
- Promotion gate completed and failed closed.
- Report links resolve to canonical `results/daily/2026-07-23/` artifacts.
- Quick sensitive-string scan found no matches in this report and the referenced cost-stress/promotion artifacts.

Inherited verification from current implementation:

- `python -m py_compile environment/trading_env.py train.py tests/test_trading_env_reward_controls.py`
- `pytest tests/test_train_hygiene.py tests/test_rl_cost_stress.py tests/test_trading_env_reward_controls.py -q` -> `22 passed`

## Next recommendation

Continue the execution-only low-churn family. The next useful variant should be a smaller step from this winner, not another shaped-reward detour:

1. Keep min hold at `12`.
2. Keep material threshold at `0.12`.
3. Try turnover caps `0.035` / `0.020` / `0.012`.
4. Keep normal/stress/crisis thresholds near `0.10` / `0.15` / `0.22`.
5. If severe 3x gets near break-even, run seeds `41, 42, 43, 44, 45` before any LLM-agent promotion consideration.
