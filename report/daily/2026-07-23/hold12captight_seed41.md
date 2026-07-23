# Hold-12 tighter-cap RL challenger, seed 41

Date: 2026-07-23  
Evaluation code commit: `65ddad0fd126be5fc6a9d8a5ed3f191838400e12`

## Outcome

This is the first seed-41 challenger in this reliability sequence to pass the configured operating and severe performance gates.

It is still **not promoted** for LLM-agent use.

- Promotion gate: `NOT_PROMOTED`
- LLM evidence status: `ABSTAIN`
- Performance gates: passed for seed 41
- Remaining blockers: only one seed, evidence envelopes are `ABSTAIN`, and source artifacts are not marked promoted

## Experiment

This run kept the hold-12 execution structure from the previous best external challenger and tightened only the turnover caps.

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
- Turnover caps normal/stress/crisis: `0.035` / `0.020` / `0.012`

## Training validation

Preserved artifacts:

- Model directory: `../../../results/daily/2026-07-23/hold12captight_model_seed41_1/models/`
- Validation summary: `../../../results/daily/2026-07-23/hold12captight_model_seed41_1/validation/validation_selection_summary.csv`
- PPO rolling validation: `../../../results/daily/2026-07-23/hold12captight_model_seed41_1/validation/ppo_rolling_validation_metrics.csv`
- SAC rolling validation: `../../../results/daily/2026-07-23/hold12captight_model_seed41_1/validation/sac_rolling_validation_metrics.csv`

| Algo | Timesteps | Mean validation reward | Worst-profile selection score |
|---|---:|---:|---:|
| PPO | 20,000 | -105.2654 | -116.2678 |
| SAC | 10,000 | -102.3447 | -112.7006 |
| SAC | 20,000 | -122.3193 | -133.4101 |

SAC selected the 10k checkpoint; 20k worsened and triggered early stop.

## External cost-stress results

Preserved artifacts:

- Cost-stress summary: `../../../results/daily/2026-07-23/rl_cost_stress/hold12captight_seed41_1/cost_stress_summary.csv`
- Promotion input: `../../../results/daily/2026-07-23/rl_promotion_gate/hold12captight_seed41_1/cost_stress_by_seed.csv`
- Promotion gate report: `../../../results/daily/2026-07-23/rl_promotion_gate/hold12captight_seed41_1/promotion_gate_report.json`
- Promotion gate summary: `../../../results/daily/2026-07-23/rl_promotion_gate/hold12captight_seed41_1/promotion_gate_summary.csv`

| Cost profile | Total return | Sharpe | Max drawdown | Cost-bearing steps | Trade events | Evidence |
|---|---:|---:|---:|---:|---:|---|
| live_like_1x | 210.0430% | 2.1528 | -15.6491% | 4,783 | 83 | ABSTAIN |
| live_like_2x | 88.3699% | 1.3055 | -15.5558% | 3,951 | 60 | ABSTAIN |
| live_like_3x | 4.5500% | 0.1617 | -15.9351% | 1,505 | 23 | ABSTAIN |

Compared with the previous hold-12 strict challenger:

| Profile | Hold-12 return | Tighter-cap return | Hold-12 Sharpe | Tighter-cap Sharpe | Hold-12 max DD | Tighter-cap max DD |
|---|---:|---:|---:|---:|---:|---:|
| live_like_1x | 214.6796% | 210.0430% | 2.1349 | 2.1528 | -16.3875% | -15.6491% |
| live_like_2x | 74.9134% | 88.3699% | 1.1251 | 1.3055 | -21.1474% | -15.5558% |
| live_like_3x | -16.0124% | 4.5500% | -0.5769 | 0.1617 | -32.3859% | -15.9351% |

Interpretation:

- Tightening turnover caps was the right next lever for seed 41.
- Severe 3x crossed from negative to positive return and Sharpe.
- Severe 3x cost-bearing steps dropped from `3,262` to `1,505`.
- Severe 3x trade events dropped from `213` to `23`.
- 1x upside was roughly preserved versus the prior hold-12 strict run while 2x and 3x improved.

## Promotion gate

Final gate status: `NOT_PROMOTED`  
Final LLM evidence status: `ABSTAIN`

Passed performance gates:

- `operating_return_all_seeds`
- `operating_sharpe_all_seeds`
- `operating_drawdown_all_seeds`
- `severe_return_all_seeds`
- `severe_sharpe_all_seeds`

Blocking failures:

- `min_seed_count`: only seed 41 was evaluated; threshold is at least 5 seeds.
- `all_evidence_verified`: evidence envelopes were `ABSTAIN`, not `VERIFIED`.
- `all_artifacts_marked_promoted`: evidence artifacts were not marked promoted.

LLM-agent instruction: continue treating RL as **no opinion** until this exact configuration survives multi-seed promotion and verified evidence envelopes are produced.

## Verification

Passed:

- Full PPO/SAC training completed.
- Full 1x/2x/3x cost-stress sweep completed.
- Promotion gate completed and failed closed.
- Report links resolve to canonical `results/daily/2026-07-23/` artifacts.
- Quick sensitive-string scan found no matches in this report and the referenced cost-stress/promotion artifacts.

No code changed in this run; it used the already pushed implementation at `65ddad0fd126be5fc6a9d8a5ed3f191838400e12`.

## Next recommendation

Run this exact configuration across seeds `42`, `43`, `44`, and `45`:

- thresholds `0.10` / `0.15` / `0.22`
- min hold bars `12`
- material trade threshold `0.12`
- reversal hysteresis `2.5`
- turnover caps `0.035` / `0.020` / `0.012`
- reward turnover `25.0`
- action-delta penalty `2.5`

If all five seeds keep 2x and 3x return/Sharpe non-negative, the next required step is to produce verified/promoted evidence envelopes rather than `ABSTAIN` artifacts.
