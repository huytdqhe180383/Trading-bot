# Scripts Map

Scripts are operator-facing wrappers and maintenance utilities. New shared
runtime logic should live under `tradingbot/`; scripts should stay thin when
practical.

## Primary Commands

- `run_live.py`: compatibility wrapper for OKX testnet/live execution.
- `scripts/run_live.py`: current canonical live runner implementation.
- `scripts/live_daily_report.py`: compatibility wrapper for `tradingbot.reports.live_daily`.
- `scripts/run_ui.py`: private UI service runner.
- `backtest.py`: backtest and ablation runner.
- `train.py`: PPO/SAC training runner.

## Server Operations

- `scripts/server/live_monitor.sh`: one-screen live bot monitor.
- `scripts/server/start_rootless_tailscale_ui.sh`: rootless Tailscale fallback.
- `scripts/server/enable_rootless_tailscale_serve.sh`: rootless Tailscale Serve helper.
- `scripts/server/install_private_ui_root.sh`: privileged UI service installer.
- `scripts/server/install_tailscale_ui_root.sh`: privileged Tailscale installer.

## Maintenance Utilities

- `scripts/estimate_agent_cost.py`: rough LLM/agent cost estimate.
- `scripts/verify_gpu_training_stack.py`: ROCm/GPU training stack verification.
- `scripts/run_kpi_improvement_experiment.py`: historical KPI experiment runner.

## Direction

When adding new behavior, prefer:

1. reusable code under `tradingbot/`
2. tests under `tests/`
3. a thin script wrapper only when an operator command is needed

