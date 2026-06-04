# KPI Improvement Experiment

- Created: 2026-06-05
- Results directory: `results\daily\2026-06-05\kpi_improvement_experiment\2`
- Phase requested: `phase2-quick`
- Training mode: `fresh`
- Baseline checkpoint source: `results\important\model_backups\2026-05-24_107pct_baseline` (unused in fresh mode)
- Methods: `dynamic_weighted`
- Seeds: `42`

## Status

Best completed row: phase `phase2_quick_screen`, variant `variant_b_balanced_light_retune`, seed `42`, method `dynamic_weighted`, trade win rate `100.00%`, profit factor `inf`, Sharpe `0.1214`, return `1.81%`, max DD `-6.78%`. Promotion gates: FAIL (sharpe_ratio 0.1214 below required 1.5000; sortino_ratio 0.0177 below required 1.8000; calmar_ratio 0.1096 below required 2.0000).

## Notes

- Fresh mode trains new PPO/SAC policies from scratch and evaluates checkpoints from `models/`.
- Phase 1 uses flat slippage and disabled eval kill switch to isolate resume-only effects.
- Phase 2 enables volatility-scaled slippage, eval kill switch, step turnover caps, and heavier drawdown/tail-loss rewards.
- Promotion fails closed unless the risk-first gates pass, including trade win rate, profit factor, drawdown, and June plunge replay.
