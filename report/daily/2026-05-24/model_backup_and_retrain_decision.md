# Model Backup + Retrain Decision

Date: 2026-05-24

## Action Taken

- Backed up current best models (107.06% RL-only baseline) to:
  - `results/important/model_backups/2026-05-24_107pct_baseline/models/PPO/ppo_best.zip`
  - `results/important/model_backups/2026-05-24_107pct_baseline/models/SAC/sac_best.zip`
- Copied source metrics and manifest to the same folder:
  - `backtest_metrics_rl_only_live_like_dynamic_weighted.csv`
  - `backup_manifest.json`

## Retrain Decision

- Retrain was **not run** because the implementation changes were in inference/overlay/backtest diagnostics only (Kronos forensics + LLM risk gate), not in RL training data pipeline, reward, model architecture, or train loop.
- Keeping the 107.06% baseline unchanged avoids unnecessary overwrite risk.

## If retrain is explicitly requested later

- Use `train.py --algo ALL --resume --device auto --seed 42 --validation-fraction 0.2`.
- Re-evaluate with `backtest.py --run-matrix --realism-profile live_like --method dynamic_weighted`.
