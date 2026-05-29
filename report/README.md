# Report Directory

Canonical report layout:

- `report/daily/YYYY-MM-DD/` stores normal daily/session reports written on that date.
- `report/important/` stores durable reports for architecture changes, overhauls, code restructures, integration plans, and major postmortems.

Generated result snapshots follow the same convention under `results/`:

- `results/daily/YYYY-MM-DD/`
- `results/important/`

The legacy `report/2026-05-23_session/` folder is retained only for previously committed session artifacts and should not be used for new reports.

See `AGENTS.md` for the full rule and completion checklist.
