# One-Pass RL Improvement + Retrain Report

## Outcome
- Seed divergence re-baseline: pass.
- Training-time action-delta penalty and `regime_weighted` selector were implemented and validated in code/tests.
- Fast 3-seed retrain completed.
- Promotion decision: reject. The new challengers do not beat the protected `107.06%` champion on risk-adjusted terms or return.

## Baseline To Beat
- Champion baseline remains: `107.06%` return, `0.8492` Sharpe, `-36.78%` max drawdown.
- Immutable backup source: `results/important/model_backups/2026-05-24_107pct_baseline/models`.

## Seed Audit
- Evidence: `results/daily/2026-05-28/phase1_seed_policy_audit.csv`.
- PPO policy hashes differ across seeds `42`, `1337`, `2026`.
- SAC policy hashes differ across seeds `42`, `1337`, `2026`.
- First-step deterministic actions differ across seeds for both PPO and SAC.
- Conclusion: the earlier identical-seed failure was fixed by the resume-seed patch in `train.py`.

## Retrain Results
- Combined metrics: `results/daily/2026-05-28/phase1_rebaseline_all_metrics.csv`.
- Method means: `results/daily/2026-05-28/phase1_rebaseline_method_means.csv`.
- Per-seed comparison plots:
  - `results/daily/2026-05-28/phase1_seed_42_method_comparison.png`
  - `results/daily/2026-05-28/phase1_seed_1337_method_comparison.png`
  - `results/daily/2026-05-28/phase1_seed_2026_method_comparison.png`

Average method performance across seeds:
- `mean`: return `10.07%`, Sharpe `0.0832`, max DD `-41.44%`, profit factor `1.0082`.
- `weighted`: return `10.07%`, Sharpe `0.0832`, max DD `-41.44%`, profit factor `1.0082`.
- `regime_weighted`: return `2.60%`, Sharpe `-0.0076`, max DD `-42.49%`, profit factor `1.0052`.
- `dynamic_weighted`: return `0.73%`, Sharpe `-0.0251`, max DD `-42.58%`, profit factor `1.0046`.

## Interpretation
- The seed-fix did what it needed to do: the training paths now diverge across seeds.
- The new training-time turnover penalty did not produce a competitive challenger within the fast budget.
- `regime_weighted` was directionally sensible on some seeds, but not enough to overtake `mean`/`weighted`, and none of the challengers approached the champion baseline.
- `mean` and `weighted` tied in this pass because the current weighting inputs still collapse to effectively similar blends under these checkpoints.

## Promotion Decision
- Keep the current `107.06%` champion as the active best model.
- Keep the new code paths as challenger infrastructure for future runs.
- Do not switch the default ensemble method in live or research mode based on this pass.

## Operational Note
- The local `.venv` launcher is currently broken after the move and resolves to a stale base interpreter path. The experiments were completed by running the base Python 3.12 interpreter with the venv `site-packages` injected through `PYTHONPATH`.
- This should be cleaned up before the next long run to avoid wrapper friction.
