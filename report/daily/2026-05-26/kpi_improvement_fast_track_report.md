# KPI Improvement Fast-Track Report

## Summary

This pass was cut down intentionally after repeated long-running wrapper stalls. The result is still clear enough to make the promotion decision:

- Do not promote the current Phase 1 or Phase 2 retrained checkpoints.
- Phase 1 resume-only materially degraded performance on all three seeds.
- Phase 2 quick-screen improved seed-42 behavior, and `variant_a_balanced_conservative` won the quick screen.
- Phase 2 full validation did not generalize. With two completed seeds, the winner variant collapsed from strong seed-42 performance to sharply negative seed-1337 performance.

## Decision

Promotion decision: reject.

Reason:

- The Phase 1 gate failed decisively.
- The Phase 2 quick screen looked good on one seed, but the fast-track full validation did not hold up.
- The requested return floor of `>= 80%` was not remotely met in the completed full-validation seeds.
- The Sharpe improvement target failed on the accelerated full-validation average.

## Key Artifacts

- Baseline reference: [results/daily/2026-05-25/1](../../../results/daily/2026-05-25/1/)
- Phase 1 summary: [experiment_metrics.csv](../../../results/daily/2026-05-25/kpi_improvement_experiment/2/experiment_metrics.csv)
- Fast-track metrics: [kpi_improvement_fast_track_metrics.csv](../../../results/daily/2026-05-26/kpi_improvement_fast_track_metrics.csv)
- Quick-screen winner candidate sessions:
  - Variant A dynamic: [results/daily/2026-05-26/4](../../../results/daily/2026-05-26/4/)
  - Variant A mean: [results/daily/2026-05-26/6](../../../results/daily/2026-05-26/6/)
  - Variant A weighted: [results/daily/2026-05-26/7](../../../results/daily/2026-05-26/7/)
  - Variant B dynamic: [results/daily/2026-05-26/8](../../../results/daily/2026-05-26/8/)
  - Variant B mean: [results/daily/2026-05-26/9](../../../results/daily/2026-05-26/9/)
  - Variant B weighted: [results/daily/2026-05-26/10](../../../results/daily/2026-05-26/10/)
- Full-validation fast-track completed seeds:
  - Seed 42 dynamic/mean/weighted: [results/daily/2026-05-26/11](../../../results/daily/2026-05-26/11/), [results/daily/2026-05-26/12](../../../results/daily/2026-05-26/12/), [results/daily/2026-05-26/13](../../../results/daily/2026-05-26/13/)
  - Seed 1337 dynamic/mean/weighted: [results/daily/2026-05-26/14](../../../results/daily/2026-05-26/14/), [results/daily/2026-05-26/15](../../../results/daily/2026-05-26/15/), [results/daily/2026-05-26/16](../../../results/daily/2026-05-26/16/)

## Readout

Phase 0 baseline:

- `dynamic_weighted`: return `107.06%`, Sharpe `0.8492`, max DD `-36.78%`

Phase 1 resume-only, 3-seed mean:

- `dynamic_weighted`: return `-64.17%`, Sharpe `-1.4439`, max DD `-70.94%`
- `mean`: return `-56.40%`, Sharpe `-1.1647`, max DD `-66.05%`
- `weighted`: return `-56.40%`, Sharpe `-1.1647`, max DD `-66.05%`

Phase 2 quick screen, seed 42:

- Variant A `dynamic_weighted`: return `22.42%`, Sharpe `2.2036`, max DD `-15.09%`
- Variant A `mean`/`weighted`: return `23.89%`, Sharpe `2.3203`, max DD `-15.10%`
- Variant B `dynamic_weighted`: return `20.97%`, Sharpe `2.1527`, max DD `-15.24%`
- Variant B `mean`/`weighted`: return `23.91%`, Sharpe `1.8707`, max DD `-15.18%`

Phase 2 full fast-track, winner variant A, two completed seeds average:

- `dynamic_weighted`: return `5.99%`, Sharpe `-1.1775`, max DD `-15.23%`
- `mean`: return `6.46%`, Sharpe `-1.2966`, max DD `-15.21%`
- `weighted`: return `6.46%`, Sharpe `-1.2966`, max DD `-15.21%`

## Interpretation

- The realism and turnover controls improved single-seed risk behavior sharply on seed 42.
- That improvement did not survive the next completed seed, which points to instability rather than a robust fix.
- Phase 1 being identical across all three seeds is suspicious enough to keep on the follow-up list. It may reflect a restore/evaluation path issue or an optimizer path that converges to the same effective policy. It is not blocking today’s decision because the observed outcome is already non-promotable.

## Operational Notes

- SAC long resume runs were moved onto the no-eval path because `EvalCallback` was repeatedly wedging the process after training work had effectively completed.
- Long background jobs were polled manually, and the cadence is now a known operational risk for this repo.
- The full Phase 2 third seed (`2026`) was intentionally stopped before completion to avoid spending more hours on a run that was already non-promotable based on the first two seeds.

## Follow-Up Fix

- `scripts/run_kpi_improvement_experiment.py` now uses a watchdog around child commands instead of raw `subprocess.run()`.
- The watchdog prints a heartbeat every `--poll-seconds` seconds, defaulting to `1200` seconds.
- Every child command has a timeout via `--command-timeout-minutes`, defaulting to `180` minutes.
- On timeout or interruption, the runner kills the full child process tree so abandoned `train.py` workers do not keep burning time.
- The runner now supports smaller run slices through `--seeds`, `--methods`, and per-phase timestep overrides.

## Recommended Next Step

- Separate follow-up pass: investigate why Phase 1 produced exactly identical post-training backtest metrics across all three seeds before spending more budget on retraining.
