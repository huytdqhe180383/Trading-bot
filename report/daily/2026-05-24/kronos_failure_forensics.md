# Kronos Failure Forensics (MA Ignored)

Date: 2026-05-24

## Locked Findings

- Kronos changed targets on `20934/20934` steps (`100.00%`).
- Average target cash shift vs RL-only: `0.1349`.
- Kronos reduced risk-on exposure on `93.79%` of steps.
- Turnover delta vs RL-only: `34.19%`.
- Transaction cost delta vs RL-only: `34.15%`.
- Final NAV gap (kronos vs rl_only): `-55.48%`.
- Months with negative gap accumulation: `20/29`.

## Artifacts

- `kronos_step_attribution.csv`
- `kronos_monthly_gap_accumulation.csv`
- `kronos_mechanism_summary.csv`
- `kronos_top_loss_events.csv`
- `kronos_forensics_summary.json`

Output directory: `results\daily\2026-05-24\kronos_failure_forensics`
