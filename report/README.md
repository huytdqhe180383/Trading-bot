# Report Archive

This folder stores timestamped snapshots of training artifacts, backtest outputs, logs, implementation snapshots, and session reports.

## Sessions

- `2026-05-23_session`
  - Main report: `report/2026-05-23_session/session_report.md`
  - Integration diagnosis: `report/2026-05-23_session/integration_failure_diagnosis.md`
  - ShopAI/Ollama + RL note: `report/2026-05-23_session/shopai_ollama_rl_improvement_note.md`
  - Includes:
    - `artifacts/results/`: backtest CSVs, parquet episodes, charts
    - `artifacts/logs/`: matrix logs, eval monitors, training logs, tensorboard data, TradingAgents decisions
    - `artifacts/implementation/`: source snapshot of the key integration files
    - `artifacts/docs/`: copied planning document
    - `metadata/`: git head, branch, status, diff stat, archive creation time

## Usage

- Start with the session report for the high-level summary.
- Use `artifacts/results/backtest_matrix_metrics.csv` for pipeline comparison.
- Use `artifacts/logs/matrix_run.err` to inspect provider failures and fallback behavior.
- Use `artifacts/implementation/` to recover the exact integration snapshot that produced the archived results.
