# Cash-preservation reward RL challenger, seed 41

Date: 2026-07-23  
Implementation commit for evaluation: `d484dd4b0099cb86278ea9801a543115acc7df2a`

## Outcome

This challenger is **not promoted** and should not be used as RL evidence for LLM agents.

It produced a useful negative result: rolling validation improved strongly for SAC, but the external cost-stress backtest regressed versus the prior hold-gate-only challenger. The promotion gate correctly failed closed.

- Promotion gate: `NOT_PROMOTED`
- LLM evidence status: `ABSTAIN`
- Main blocker: severe 3x profile is still negative and worse than the previous hold-gate model.

## What changed

Added opt-in reward controls for severe-cost survival experiments:

- `reward_missed_opportunity_weight`
- `reward_cash_buffer_weight`
- `reward_cash_buffer_threshold`
- `reward_risk_exposure_weight`
- `reward_risk_exposure_threshold`

Training settings for this run:

- Training fee/slippage: `0.0036` / `0.0054`
- Validation profiles: nominal, 2x, severe 3x
- Validation score: worst-profile mean
- Reward turnover weight: `20.0`
- Missed-opportunity weight: `0.02`
- Cash-buffer reward: weight `0.01`, threshold `0.65`
- Risk-exposure penalty: weight `0.06`, threshold `0.25`
- Execution hold gate retained:
  - thresholds normal/stress/crisis: `0.08` / `0.12` / `0.18`
  - min hold bars: `8`
  - material trade threshold: `0.10`
  - reversal hysteresis: `2.0`
  - turnover caps normal/stress/crisis: `0.05` / `0.03` / `0.02`

## Training validation

Preserved artifacts:

- Model directory: `../../../results/daily/2026-07-23/cashhold3x_reward_model_seed41_1/models/`
- Validation summary: `../../../results/daily/2026-07-23/cashhold3x_reward_model_seed41_1/validation/validation_selection_summary.csv`
- PPO rolling validation: `../../../results/daily/2026-07-23/cashhold3x_reward_model_seed41_1/validation/ppo_rolling_validation_metrics.csv`
- SAC rolling validation: `../../../results/daily/2026-07-23/cashhold3x_reward_model_seed41_1/validation/sac_rolling_validation_metrics.csv`

| Algo | Timesteps | Mean validation reward | Worst-profile selection score |
|---|---:|---:|---:|
| PPO | 20,000 | -120.8855 | -127.9711 |
| SAC | 10,000 | -118.6039 | -126.3024 |
| SAC | 20,000 | -85.2256 | -94.2481 |
| SAC | 30,000 | -68.6997 | -76.5184 |

SAC validation improved through 30k, and its 30k severe validation score was better than the previous hold-gate run. This did **not** translate to better external cost-stress performance.

## Cost-stress results

Preserved artifacts:

- Cost-stress summary: `../../../results/daily/2026-07-23/rl_cost_stress/cashhold3x_reward_seed41_1/cost_stress_summary.csv`
- Promotion input: `../../../results/daily/2026-07-23/rl_promotion_gate/cashhold3x_reward_seed41_1/cost_stress_by_seed.csv`
- Promotion gate report: `../../../results/daily/2026-07-23/rl_promotion_gate/cashhold3x_reward_seed41_1/promotion_gate_report.json`
- Promotion gate summary: `../../../results/daily/2026-07-23/rl_promotion_gate/cashhold3x_reward_seed41_1/promotion_gate_summary.csv`

| Cost profile | Total return | Sharpe | Max drawdown | Cost-bearing steps | Trade events | Evidence |
|---|---:|---:|---:|---:|---:|---|
| live_like_1x | 220.9273% | 1.9656 | -20.9702% | 4,167 | 100 | ABSTAIN |
| live_like_2x | 32.7631% | 0.5347 | -25.9303% | 4,163 | 82 | ABSTAIN |
| live_like_3x | -24.6458% | -0.6480 | -41.0255% | 4,071 | 65 | ABSTAIN |

Compared with the previous hold-gate-only challenger:

| Profile | Hold-gate return | Cash-reward return | Hold-gate Sharpe | Cash-reward Sharpe |
|---|---:|---:|---:|---:|
| live_like_1x | 346.9161% | 220.9273% | 2.1715 | 1.9656 |
| live_like_2x | 53.4159% | 32.7631% | 0.7316 | 0.5347 |
| live_like_3x | -19.3287% | -24.6458% | -0.4880 | -0.6480 |

The new reward improved internal validation but degraded external severe-cost results. Treat it as overfit or misaligned reward shaping, not as a candidate improvement.

## Promotion gate

Final gate status: `NOT_PROMOTED`  
Final LLM evidence status: `ABSTAIN`

Blocking failures:

- `min_seed_count`: only seed 41 was evaluated; threshold is at least 5 seeds.
- `severe_return_all_seeds`: severe 3x return was `-24.6458%`, below the `>= 0%` threshold.
- `severe_sharpe_all_seeds`: severe 3x Sharpe was `-0.6480`, below the `>= 0` threshold.
- `all_evidence_verified`: evidence envelopes were `ABSTAIN`, not `VERIFIED`.
- `all_artifacts_marked_promoted`: evidence artifacts were not marked promoted.

LLM-agent instruction: continue treating RL as **no opinion**.

## Verification

Passed:

- `python -m py_compile environment/trading_env.py train.py tests/test_trading_env_reward_controls.py`
- `pytest tests/test_train_hygiene.py tests/test_rl_cost_stress.py tests/test_trading_env_reward_controls.py -q` -> `22 passed`
- Full training completed for PPO and SAC.
- Full cost-stress sweep completed for 1x, 2x, and 3x profiles.
- Promotion gate completed and failed closed.

Known limitation:

- `tests/test_audit_hotfixes.py` still could not be used under the Codex bundled Python because its module-level `data.live_feed` import hangs in this runtime. The new reward controls were covered in `tests/test_trading_env_reward_controls.py`, which imports only the trading environment.

## Next lesson

Do not continue this exact cash/risk reward mix. The better path is:

1. Keep the hold-gate execution controls from `fcf3270`.
2. Remove or sharply reduce the cash-buffer bonus; it did not improve external severe-cost survival.
3. Test lighter exposure penalties, or make exposure penalty regime-conditional instead of always-on.
4. Prefer external cost-stress over internal shaped validation when selecting reliability candidates.
