# AGENTS.md

## Git Workflow Rules

For every work session:

1. Create or switch to a dedicated working branch for that session.
2. Commit the completed session changes with a clear message.
3. Push the session branch to the remote before ending the session.

## Report And Result Storage Rules

All future agents must keep reports and generated result snapshots under the canonical categorized folders below. Do not create new ad-hoc session folders such as `report/<date>_session/`.

### Reports

Use `report/daily/YYYY-MM-DD/` for normal work-session reports written on that date, including:

- training summaries
- backtest summaries
- debugging notes
- provider/API diagnostics
- model-performance notes
- short implementation follow-ups

Use `report/important/` for durable, high-value reports that should be easy to find later, including:

- architecture changes
- major overhauls
- code restructures
- integration plans
- postmortems that affect future design

If an important report is also produced during a daily session, store the canonical copy in `report/important/` and optionally add a short daily note that links to it.

### Results

Use `results/daily/YYYY-MM-DD/` for snapshots of generated outputs from runs performed on that date, including:

- backtest CSVs
- backtest parquet episodes
- generated plots
- diagnostics CSVs
- model comparison outputs

Use `results/important/` for curated result snapshots tied to major decisions, releases, architecture changes, or overhaul reports.

The root `results/` directory may remain a transient compatibility output target for scripts, but any result worth preserving must be copied into the appropriate daily or important folder before reporting completion.

### Naming

- Use ISO dates: `YYYY-MM-DD`.
- Use descriptive lowercase filenames with underscores.
- Keep related report artifacts in a subfolder beside the report, for example `report/daily/2026-05-23/drawdown_diagnosis/`.
- Never store secrets, `.env`, API keys, raw credentials, virtual environments, or external source clones in report/result folders.

### Minimum Completion Checklist

Before claiming report/result work is complete:

1. Confirm the report is under `report/daily/YYYY-MM-DD/` or `report/important/`.
2. Confirm preserved outputs are under `results/daily/YYYY-MM-DD/` or `results/important/`.
3. Confirm markdown links still work relative to the report location.
4. Confirm no secrets or heavyweight local-only folders were added.
