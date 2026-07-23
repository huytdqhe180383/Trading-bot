# RL Promotion Gate for Turnover-Strict Candidate

**Date:** 2026-07-23

**Status:** Implemented and evaluated; candidate remains not promoted

## Summary

Added a machine-readable RL promotion-gate evaluator so multi-seed research results cannot be promoted to LLM-agent context by manual interpretation alone.

The turnover-strict seed `41/42/43` candidate still fails closed:

- Promotion status: `NOT_PROMOTED`
- LLM evidence status: `ABSTAIN`
- Operating 2x cost gates passed.
- Severe 3x cost gates failed.
- Evidence artifacts are still `ABSTAIN`.
- Source artifacts are not marked promoted.
- Seed count is `3`, below the default promotion threshold of `5`.

## Implementation

New script:

- [evaluate_rl_promotion_gate.py](../../../scripts/evaluate_rl_promotion_gate.py)

New tests:

- [test_rl_promotion_gate.py](../../../tests/test_rl_promotion_gate.py)

The script consumes a preserved by-seed cost-stress CSV and writes:

- `promotion_gate_report.json`
- `promotion_gate_summary.csv`

It emits `PROMOTED` only when all blocking gates pass. Otherwise it emits `llm_evidence_status: ABSTAIN`, with explicit blocking failure names.

## Actual Gate Run

Input artifacts:

- [turnover_strict_seed41_42_43_cost_stress_by_seed.csv](../../../results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed41_42_43_cost_stress_by_seed.csv)
- [turnover_strict_seed41_42_43_validation_best.csv](../../../results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed41_42_43_validation_best.csv)

Output artifacts:

- [promotion_gate_report.json](../../../results/daily/2026-07-23/rl_promotion_gate/turnover_strict_seed41_42_43_1/promotion_gate_report.json)
- [promotion_gate_summary.csv](../../../results/daily/2026-07-23/rl_promotion_gate/turnover_strict_seed41_42_43_1/promotion_gate_summary.csv)

Command:

```text
python scripts/evaluate_rl_promotion_gate.py --candidate-label turnover_strict_seed41_42_43 --cost-stress-by-seed results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed41_42_43_cost_stress_by_seed.csv --validation-best results/daily/2026-07-22/rl_cost_stress/turnover_strict_seed41_42_43_validation_best.csv --output-dir results/daily/2026-07-23/rl_promotion_gate/turnover_strict_seed41_42_43_1
```

## Gate Results

Blocking failures:

| Gate | Observed | Threshold |
|---|---:|---:|
| `min_seed_count` | `3` seeds | `>= 5` |
| `severe_return_all_seeds` | min `-41.55%` at 3x | `>= 0.0%` |
| `severe_sharpe_all_seeds` | min `-0.8010` at 3x | `>= 0.0` |
| `all_evidence_verified` | `ABSTAIN` | `VERIFIED` |
| `all_artifacts_marked_promoted` | `0 / 6` rows promoted | all rows promoted |

Passing blocking gates:

| Gate | Observed |
|---|---:|
| `required_profiles_present` | 2x and 3x present for all 3 seeds |
| `metrics_complete` | no missing required metrics |
| `operating_return_all_seeds` | min `56.74%` at 2x |
| `operating_sharpe_all_seeds` | min `0.5674` at 2x |
| `operating_drawdown_all_seeds` | worst `-35.94%`, limit `-40.0%` |

Diagnostic non-blocking gate:

- `code_commit_consistency` failed because the preserved rows span implementation/report/parser commits. This is recorded for auditability but does not itself block promotion.

## Interpretation

This turns the previous narrative decision into a reusable gate:

- The candidate is good enough to justify more research.
- It is not reliable enough for LLM agents.
- Future agent-visible promotion must pass the same kind of explicit, machine-readable gate rather than relying on a favorable single metric.

## Verification

Completed checks:

- `python -m pytest tests/test_rl_promotion_gate.py -q`: `2 passed, 1 warning`
- `python -m pytest tests/test_rl_evidence.py tests/test_rl_cost_stress.py tests/test_rl_seed_screen.py tests/test_rl_promotion_gate.py -q`: `19 passed, 1 warning`

Known environment note:

- Pytest cannot write `.pytest_cache` under this sandbox profile, producing the existing cache permission warning.

## Completion Checklist

- Report stored under `report/daily/2026-07-23/`.
- Preserved outputs stored under `results/daily/2026-07-23/`.
- Markdown links should resolve from this report location.
- No `.env`, credentials, virtual environments, or external source clones are referenced or stored by this report.
