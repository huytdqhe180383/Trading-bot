# Hold-12 tighter-cap RL challenger, seeds 41-50

Date: 2026-07-28  
Aggregate evidence code commit: `abf2884ed069eaaf15efe2bc8fb6c7dc02f97560`

## Outcome

The ten-seed extension broke the earlier five-seed optimism.

This challenger remains **not promoted** for LLM-agent use, and the aggregate RL evidence envelope remains **ABSTAIN**.

- Promotion gate: `NOT_PROMOTED`
- Statistical gate: `FAILED`
- Aggregate candidate evidence: `ABSTAIN`
- Operating 2x live-like costs: still positive across all 10 seeds
- Severe 3x live-like costs: mean return turned negative, with three consecutive failing seeds (`46`, `47`, `48`) and only weak recovery from seeds `49` and `50`

LLM-agent instruction: keep treating RL as **no opinion**. This candidate is not reliable enough to become an analyst-visible RL source.

## Candidate configuration

This extension kept the exact same configuration that passed the earlier five-seed screen.

Training and validation settings:

- Training fee/slippage: `0.0036` / `0.0054`
- Validation profiles: nominal, 2x, severe 3x
- Validation score: worst-profile mean
- Validation early stop: patience `1`, minimum evals `2`
- Reward turnover weight: `25.0`
- Action-delta penalty: `2.5`
- Action-delta deadband/scale: `0.0` / `1.0`

Execution controls:

- Rebalance thresholds normal/stress/crisis: `0.10` / `0.15` / `0.22`
- Min hold bars: `12`
- Material trade threshold: `0.12`
- Reversal hysteresis multiplier: `2.5`
- Turnover caps normal/stress/crisis: `0.035` / `0.020` / `0.012`

## Preserved artifacts

Aggregate artifacts written on 2026-07-28:

- Cost-stress by seed: `../../../results/daily/2026-07-28/rl_promotion_gate/hold12captight_seed41_50_1/cost_stress_by_seed.csv`
- Promotion gate report: `../../../results/daily/2026-07-28/rl_promotion_gate/hold12captight_seed41_50_1/promotion_gate_report.json`
- Promotion gate summary: `../../../results/daily/2026-07-28/rl_promotion_gate/hold12captight_seed41_50_1/promotion_gate_summary.csv`
- Statistical gate report: `../../../results/daily/2026-07-28/rl_statistical_gates/hold12captight_seed41_50_1/rl_statistical_report.json`
- Statistical gate summary: `../../../results/daily/2026-07-28/rl_statistical_gates/hold12captight_seed41_50_1/statistical_gate_summary.csv`
- Validation summary: `../../../results/daily/2026-07-28/hold12captight_multiseed_seed41_50_1/validation_selection_summary.csv`
- Aggregate candidate evidence envelope: `../../../results/daily/2026-07-28/rl_candidate_evidence/hold12captight_seed41_50_1/rl_evidence.json`

Seed-specific training and replay artifacts remain under the existing July 23 sweep folders:

- Models: `../../../results/daily/2026-07-23/hold12captight_model_seed41_1/` through `../../../results/daily/2026-07-23/hold12captight_model_seed50_1/`
- Cost stress: `../../../results/daily/2026-07-23/rl_cost_stress/`

Replay suffix note:

- Seed `41` uses refreshed cost-stress folder `hold12captight_seed41_2`
- Seed `48` uses final successful cost-stress folder `hold12captight_seed48_4`
- Other seeds in the ten-seed aggregate use their `_1` cost-stress folders

## Ten-seed cost-stress result

Aggregate by profile:

| Cost profile | Mean return | Min return | Mean Sharpe | Min Sharpe | Mean max DD | Worst max DD |
|---|---:|---:|---:|---:|---:|---:|
| live_like_1x | 207.1942% | 197.4343% | 2.1237 | 2.0545 | -16.0840% | -16.6920% |
| live_like_2x | 66.5317% | 15.6542% | 1.0446 | 0.4454 | -17.8794% | -21.8072% |
| live_like_3x | -2.1282% | -16.0551% | -0.0789 | -0.5863 | -22.2197% | -32.1455% |

Operating and severe profiles by seed:

| Seed | 2x return | 2x Sharpe | 2x max DD | 3x return | 3x Sharpe | 3x max DD |
|---:|---:|---:|---:|---:|---:|---:|
| 41 | 88.3699% | 1.3055 | -15.5558% | 4.5500% | 0.1617 | -15.9351% |
| 42 | 82.7797% | 1.2377 | -17.0106% | 3.1801% | 0.1224 | -16.5284% |
| 43 | 61.4550% | 0.9954 | -18.2630% | 2.0573% | 0.0730 | -19.4582% |
| 44 | 96.1808% | 1.3785 | -17.2700% | 5.4851% | 0.2005 | -20.5276% |
| 45 | 81.0912% | 1.1998 | -20.4033% | 1.9061% | 0.0748 | -17.1537% |
| 46 | 90.0089% | 1.3124 | -15.7889% | -11.9795% | -0.4540 | -29.1457% |
| 47 | 52.8888% | 0.8832 | -20.1315% | -14.6663% | -0.5360 | -30.9581% |
| 48 | 19.5138% | 0.4958 | -15.7518% | -16.0551% | -0.5863 | -32.1455% |
| 49 | 15.6542% | 0.4454 | -21.8072% | 3.8472% | 0.1398 | -20.4777% |
| 50 | 77.3750% | 1.1928 | -16.8119% | 0.3934% | 0.0153 | -19.8665% |

Interpretation:

- All 10 seeds still survived the operating 2x cost profile.
- The severe 3x profile no longer survives at the candidate level: mean return is negative and mean Sharpe is negative.
- Seeds `46`, `47`, and `48` failed hard under severe costs.
- Seeds `49` and `50` recovered only to thin severe-cost margins, not promotion-grade robustness.

## Promotion gate

Final gate status: `NOT_PROMOTED`  
Final LLM evidence status: `ABSTAIN`

Passed blocking gates:

- `min_seed_count`
- `required_profiles_present`
- `metrics_complete`
- `operating_return_all_seeds`
- `operating_sharpe_all_seeds`
- `operating_drawdown_all_seeds`

Blocking failures:

- `severe_return_all_seeds`: severe 3x minimum return fell to `-16.0551%`
- `severe_sharpe_all_seeds`: severe 3x minimum Sharpe fell to `-0.5863`
- `all_evidence_verified`: source evidence envelopes remain `ABSTAIN`
- `all_artifacts_marked_promoted`: source artifacts are not marked promoted

Non-blocking diagnostic:

- `code_commit_consistency`: the ten-seed aggregate includes source rows from two historical commits (`fdc91ffc89926de799021499b42463a40170840b` and `abf2884ed069eaaf15efe2bc8fb6c7dc02f97560`)

## Statistical gate

Final statistical status: `FAILED`

Passed:

- `min_statistical_seed_count`
- `required_profiles_present`
- `metrics_complete`
- operating 2x bootstrap return/Sharpe/drawdown threshold probabilities
- severe 3x bootstrap drawdown threshold probability

Blocking failures:

- `severe_bootstrap_return_probability`
- `severe_bootstrap_sharpe_probability`
- `deflated_sharpe_probability`
- `backtest_overfit_probability`

Useful diagnostics:

- Severe 3x observed mean return: `-2.1282%`
- Severe 3x observed mean Sharpe: `-0.0789`
- Severe 3x bootstrap mean return CI: `-7.4261%` / `-2.0490%` / `2.6712%`
- Severe 3x bootstrap mean Sharpe CI: `-0.2753` / `-0.0767` / `0.0902`
- Severe 3x threshold probability for mean return `>= 0`: `0.1986`
- Severe 3x threshold probability for mean Sharpe `>= 0`: `0.2021`

The statistical gate now has enough seeds, so the remaining failure is real severe-cost weakness plus the still-missing DSR/PBO workflow.

## Candidate evidence envelope

The aggregate envelope is preserved at `../../../results/daily/2026-07-28/rl_candidate_evidence/hold12captight_seed41_50_1/rl_evidence.json`.

It emits:

- status: `ABSTAIN`
- horizon: `historical_multiseed_backtest`
- operating mean return: `66.5317%`
- operating min return: `15.6542%`
- severe mean return: `-2.1282%`
- severe min return: `-16.0551%`

The fail-closed reasons remain correct:

- `promotion_gate_not_promoted`
- `promotion_gate_llm_evidence_not_verified`
- `promotion_gate_blocking_failures_present`
- `promotion_status_missing`
- `promotion_expiry_missing`
- `causal_integrity_gate_missing`
- `statistical_gates_missing`
- `calibration_gate_missing`
- `prospective_shadow_gate_missing`

## Environment note

On 2026-07-28 the project-local `.venv` still pointed to a missing system Python, and the bundled Codex Python initially lacked pieces of the RL/backtest stack.

This session repaired the bundled interpreter used for the seed-47 through seed-50 continuation by installing the missing runtime dependencies needed by `train.py`, `backtest.py`, and parquet loading. The successful aggregate outputs above were generated only after direct import and parquet-read checks passed.

## Lessons for implementation

1. Five-seed screens were not enough for this candidate.

   The first five seeds looked promotion-adjacent under severe costs, but the ten-seed extension flipped severe mean return and Sharpe negative.

2. Validation still overstates real severe-cost resilience.

   Seeds `46` through `50` kept validation selection scores in the same general band as the earlier winners, yet several collapsed under 3x live-like cost stress.

3. The next model-improvement target is severe-cost margin, not nominal upside.

   Operating-profile performance remains strong. The real gap is sensitivity to harsher execution friction and unstable severe-profile behavior across seeds.

4. LLM trust should stay fail-closed even when average operating performance looks good.

   The envelope staying `ABSTAIN` is correct. Historical operating profitability is not enough to make RL a reliable upstream source for LLM agents.

## Verification

Passed:

- Seeds `47` through `50` trained under the frozen hold-12 tighter-cap configuration.
- Seeds `47` through `50` completed 1x/2x/3x cost-stress evaluation.
- Ten-seed aggregate cost-stress, promotion, statistical, and candidate-evidence artifacts were regenerated under `results/daily/2026-07-28/`.
- The aggregate candidate evidence envelope remained `ABSTAIN`.
- Focused regression pack passed on 2026-07-28: `tests/test_rl_evidence.py tests/test_rl_statistical_gates.py tests/test_rl_promotion_gate.py tests/test_rl_cost_stress.py tests/test_trading_env_reward_controls.py tests/test_train_hygiene.py tests/test_analyst_service.py` (`46 passed`)

Pending after this report:

- Final git staging, commit, and push for the July 28, 2026 session

## Next recommendation

Do not promote `hold12captight_seed41_50` into the LLM analyst path.

The next implementation slice should start from the failure mode revealed here:

1. diagnose why severe 3x cost sensitivity jumps sharply for seeds `46` through `48`;
2. revise the candidate to widen severe-cost margin, not to maximize 1x return;
3. add DSR/PBO from a preserved trial-registry plus CSCV workflow;
4. rerun a fresh multi-seed screen before any prospective-shadow or analyst-evidence promotion step.
