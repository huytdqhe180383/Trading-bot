# Application Spine And Artifact Refactor

## Summary

Implemented the first architecture refactor pass from the important candidate
report:

- added `tradingbot.runtime.artifacts`
- added `tradingbot.reports.live_daily`
- added `tradingbot.apps`
- kept existing commands compatible
- added navigation docs, a project context glossary, and ADR 0001

## Code Changes

- `backtest.py` now uses shared artifact helpers for daily result sessions and
  metadata writes.
- `scripts/run_live.py` now uses shared artifact helpers for live session
  folders, metadata, CSV rows, and summaries.
- `scripts/live_daily_report.py` is now a compatibility wrapper over
  `tradingbot.reports.live_daily`.
- `ui/services.py` now reads live report data through the package module rather
  than importing the script wrapper.
- `run_live.py` now enters through `tradingbot.apps.live`.

## Documentation Changes

- Added `CONTEXT.md` for project domain terms and invariants.
- Added `docs/README.md` as a documentation map.
- Added `docs/architecture/runtime_spine.md`.
- Added `docs/adr/0001-application-spine-and-artifact-runtime.md`.
- Added `scripts/README.md`.
- Updated `README.md` and `docs/architecture.md`.

## Verification

- Added tests for runtime artifacts, live report package behavior, lazy app
  entrypoints, and required docs.
- Full test suite passed on 2026-05-31.

## Next Architecture Targets

- Extract shared execution policy from environment/live/backtest paths.
- Move large orchestration modules behind `tradingbot.apps`.
- Continue replacing direct script imports with package imports.

