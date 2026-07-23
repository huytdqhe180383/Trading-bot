# Hold-12 tighter-cap RL challenger, seeds 41-45

Date: 2026-07-23  
Cost-stress evidence code commit: `fdc91ffc89926de799021499b42463a40170840b`

## Outcome

This is the first RL challenger in the reliability sequence to pass the configured five-seed historical performance gates under both operating and severe live-like cost stress.

It is **not promoted** for LLM-agent use yet.

- Promotion gate: `NOT_PROMOTED`
- LLM evidence status: `ABSTAIN`
- Quantitative performance gates: passed across seeds `41`, `42`, `43`, `44`, and `45`
- Remaining blocking gates: evidence envelopes are still `ABSTAIN`, and source artifacts are not marked promoted

LLM-agent instruction: keep treating RL as **no opinion** until verified/promoted evidence envelopes exist. This candidate is ready for the next reliability stage, not agent-visible use.

## Candidate configuration

This run used the hold-12 execution structure that first made severe 3x costs survivable, then screened it across five seeds.

Training and validation settings:

- Training fee/slippage: `0.0036` / `0.0054`
- Validation profiles: nominal, 2x, severe 3x
- Validation score: worst-profile mean
- Validation early stop: patience `1`, minimum evals `2`
- Reward turnover weight: `25.0`
- Action-delta penalty: `2.5`
- Action-delta deadband/scale: `0.0` / `1.0`
- No cash-buffer reward override
- No risk-exposure reward override
- No missed-opportunity override

Execution controls:

- Rebalance thresholds normal/stress/crisis: `0.10` / `0.15` / `0.22`
- Min hold bars: `12`
- Material trade threshold: `0.12`
- Reversal hysteresis multiplier: `2.5`
- Turnover caps normal/stress/crisis: `0.035` / `0.020` / `0.012`

## Preserved artifacts

Aggregate artifacts:

- Cost-stress by seed: `../../../results/daily/2026-07-23/rl_promotion_gate/hold12captight_seed41_45_1/cost_stress_by_seed.csv`
- Promotion gate report: `../../../results/daily/2026-07-23/rl_promotion_gate/hold12captight_seed41_45_1/promotion_gate_report.json`
- Promotion gate summary: `../../../results/daily/2026-07-23/rl_promotion_gate/hold12captight_seed41_45_1/promotion_gate_summary.csv`
- Validation summary: `../../../results/daily/2026-07-23/hold12captight_multiseed_seed41_45_1/validation_selection_summary.csv`
- Aggregate candidate evidence envelope: `../../../results/daily/2026-07-23/rl_candidate_evidence/hold12captight_seed41_45_1/rl_evidence.json`

Per-seed model and cost-stress artifacts:

| Seed | Model directory | Cost-stress directory |
|---:|---|---|
| 41 | `../../../results/daily/2026-07-23/hold12captight_model_seed41_1/models/` | `../../../results/daily/2026-07-23/rl_cost_stress/hold12captight_seed41_2/` |
| 42 | `../../../results/daily/2026-07-23/hold12captight_model_seed42_1/models/` | `../../../results/daily/2026-07-23/rl_cost_stress/hold12captight_seed42_1/` |
| 43 | `../../../results/daily/2026-07-23/hold12captight_model_seed43_1/models/` | `../../../results/daily/2026-07-23/rl_cost_stress/hold12captight_seed43_1/` |
| 44 | `../../../results/daily/2026-07-23/hold12captight_model_seed44_1/models/` | `../../../results/daily/2026-07-23/rl_cost_stress/hold12captight_seed44_1/` |
| 45 | `../../../results/daily/2026-07-23/hold12captight_model_seed45_1/models/` | `../../../results/daily/2026-07-23/rl_cost_stress/hold12captight_seed45_1/` |

Seed 41 was cost-stress refreshed into `hold12captight_seed41_2` so all aggregate rows share the same evidence-generation commit. The refreshed metrics matched the earlier seed-41 run.

## Five-seed cost-stress result

Aggregate by profile:

| Cost profile | Mean return | Min return | Mean Sharpe | Min Sharpe | Mean max DD | Worst max DD |
|---|---:|---:|---:|---:|---:|---:|
| live_like_1x | 209.7444% | 203.2967% | 2.1452 | 2.0973 | -15.9783% | -16.5320% |
| live_like_2x | 81.9753% | 61.4550% | 1.2234 | 0.9954 | -17.7005% | -20.4033% |
| live_like_3x | 3.4357% | 1.9061% | 0.1265 | 0.0730 | -17.9206% | -20.5276% |

Operating and severe profiles by seed:

| Seed | 2x return | 2x Sharpe | 2x max DD | 3x return | 3x Sharpe | 3x max DD |
|---:|---:|---:|---:|---:|---:|---:|
| 41 | 88.3699% | 1.3055 | -15.5558% | 4.5500% | 0.1617 | -15.9351% |
| 42 | 82.7797% | 1.2377 | -17.0106% | 3.1801% | 0.1224 | -16.5284% |
| 43 | 61.4550% | 0.9954 | -18.2630% | 2.0573% | 0.0730 | -19.4582% |
| 44 | 96.1808% | 1.3785 | -17.2700% | 5.4851% | 0.2005 | -20.5276% |
| 45 | 81.0912% | 1.1998 | -20.4033% | 1.9061% | 0.0748 | -17.1537% |

Interpretation:

- Every seed remained profitable at 2x and 3x live-like costs.
- Every seed kept positive Sharpe at 2x and 3x.
- The weakest severe-profile seed was seed 45 at `1.9061%` total return and `0.0748` Sharpe.
- The lowest severe-profile Sharpe was seed 43 at `0.0730`.
- Severe-profile returns are positive but thin, so this should not be treated as a capital-ready model. The result is strong enough to begin shadow/prospective evidence collection.

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
- `severe_return_all_seeds`
- `severe_sharpe_all_seeds`

Passed non-blocking diagnostic:

- `code_commit_consistency`

Blocking failures:

- `all_evidence_verified`: all source evidence envelopes report `ABSTAIN`, not `VERIFIED`.
- `all_artifacts_marked_promoted`: `0 / 10` required operating/severe source artifacts are marked promoted.

The source evidence envelopes list these fail-closed reasons:

- `promotion_status_missing`
- `promotion_expiry_missing`
- `causal_integrity_gate_missing`
- `statistical_gates_missing`
- `calibration_gate_missing`
- `prospective_shadow_gate_missing`

## Aggregate analyst evidence envelope

Follow-up implementation added `scripts/build_rl_candidate_evidence.py` and `build_evidence_from_promotion_gate(...)`.

The generated aggregate envelope is preserved at `../../../results/daily/2026-07-23/rl_candidate_evidence/hold12captight_seed41_45_1/rl_evidence.json`.

It contains the five-seed aggregate metrics that would be useful to an analyst, but it still emits:

- status: `ABSTAIN`
- horizon: `historical_multiseed_backtest`
- severe min return: `1.9061%`
- severe min Sharpe: `0.0730`
- operating min return: `61.4550%`
- operating min Sharpe: `0.9954`

This is now the correct candidate handoff shape for the LLM path: one sanitized aggregate envelope, still non-executable, still fail-closed, and ready to become the configured analyst evidence path only after the missing gates are actually passed.

## Lessons for implementation

1. Training/live execution parity mattered more than another reward tweak.

   The winning candidate came from making training obey the same anti-churn controls used in backtest/live evaluation: turnover caps, larger rebalance thresholds, hold gates, material-trade filtering, and reversal hysteresis.

2. Worst-profile validation was useful, but external cost stress remained decisive.

   The cash-buffer reward challenger looked better in validation yet regressed under external cost stress. The promotion workflow should keep validation as a selector, not as the final proof.

3. Seed-minimum metrics should be the promotion unit.

   The average severe 3x return was positive, but the worst seed was only `1.9061%`. LLM-agent evidence should cite minima or intervals, not best-seed examples.

4. The LLM contract must stay separated from model optimism.

   Historical robustness improved enough to choose a shadow candidate, but the analyst channel must still receive `ABSTAIN` until causal, statistical, calibration, and prospective gates are passed.

5. The next model-improvement lever is no longer just raw return.

   The next target should be widening the severe 3x margin: lower variance, lower cost sensitivity, stronger uncertainty estimates, and shadow calibration. Chasing higher 1x upside is secondary.

## Verification

Passed:

- Seeds `44` and `45` trained with the same configuration used by seed `41`.
- Seeds `41` through `45` completed 1x/2x/3x cost-stress evaluation.
- Seed `41` cost stress was refreshed under the current evidence-generation commit.
- The aggregate promotion gate completed and failed closed only on LLM evidence gates.
- The aggregate candidate evidence envelope was generated and confirmed to emit `ABSTAIN`.
- Focused regression pack passed: `tests/test_rl_evidence.py tests/test_rl_promotion_gate.py tests/test_rl_cost_stress.py tests/test_trading_env_reward_controls.py tests/test_train_hygiene.py` (`32 passed`).
- Analyst service regression passed: `tests/test_analyst_service.py` (`11 passed`).
- Report links resolve to canonical `results/daily/2026-07-23/` artifacts.
- Quick sensitive-string scan found no matches in this report and the referenced aggregate/promotion artifacts.

Not performed:

- No `ANALYST_RL_EVIDENCE_PATH` change was made.
- No `results/rl_evidence.json` was promoted.
- No source evidence artifact was manually upgraded from `ABSTAIN`.

## Next recommendation

Use `hold12captight_seed41_45` as the prospective shadow candidate, not as an LLM-agent trading source.

The next implementation slice should add an explicit shadow/promotion pipeline:

1. freeze this candidate configuration and model-set manifest;
2. run a leakage/causal-integrity regression pack on the frozen model set;
3. add DSR/PBO/bootstrap interval reporting for this five-seed candidate;
4. publish an aggregate non-executable evidence envelope that remains `ABSTAIN` until all gates pass;
5. start prospective shadow collection with calibration coverage and realized-outcome tracking;
6. only after those gates pass, emit a short-lived `VERIFIED` envelope with a promotion expiry.
