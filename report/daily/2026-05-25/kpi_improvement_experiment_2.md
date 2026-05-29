# KPI Improvement Experiment

- Created: 2026-05-25
- Results directory: `results\daily\2026-05-25\kpi_improvement_experiment\2`
- Phase requested: `phase1`
- Baseline checkpoint source: `results\important\model_backups\2026-05-24_107pct_baseline`
- Methods: `dynamic_weighted, mean, weighted`
- Seeds: `42, 1337, 2026`

## Status

Best completed row: phase `phase1_resume_expansion`, variant `flat_resume_only`, seed `42`, method `mean`, Sharpe `-1.1647`, return `-56.40%`, max DD `-66.05%`.

## Notes

- Each seed restores the immutable 107% checkpoint before training.
- Phase 1 uses flat slippage and disabled eval kill switch to isolate resume-only effects.
- Phase 2 enables volatility-scaled slippage, eval kill switch, and step turnover caps.
- Promotion still requires manual review against the clean Phase 0 baseline gates.
