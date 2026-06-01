# ADR 0001: Application Spine And Artifact Runtime

## Status

Accepted

## Context

The project grew through training, backtesting, live execution, private UI, and
server operations work. Several entrypoints independently handled the same
artifact tasks:

- creating `results/daily/YYYY-MM-DD/N/` folders
- writing metadata JSON
- appending CSV decision rows
- summarizing live sessions
- loading live decision history for reports and the UI

That duplication made small operational changes expensive and easy to apply in
one path but not another.

## Decision

Create a small `tradingbot` application package:

- `tradingbot.runtime.artifacts` owns shared artifact/session helpers.
- `tradingbot.reports.live_daily` owns compact live report building.
- `tradingbot.apps` exposes stable lazy entrypoints for commands and services.

Keep existing root and script commands as compatibility entrypoints.

## Consequences

Positive:

- Artifact rules now have one primary implementation.
- Live reports and the private UI share the same report loader.
- Application entrypoints can be moved gradually without breaking operator commands.
- Tests can target package boundaries instead of only root scripts.

Tradeoffs:

- Some old modules still contain orchestration logic while the migration is in progress.
- Compatibility wrappers add a small amount of temporary indirection.

## Follow-Up

- Extract shared execution policy from environment/live/backtest paths.
- Move large orchestration modules behind the `tradingbot.apps` boundary.
- Continue replacing direct script imports with package imports.

