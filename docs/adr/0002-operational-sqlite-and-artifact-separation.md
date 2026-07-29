# ADR 0002: Operational SQLite And Artifact Separation

## Status

Accepted

## Context

Analyst events and order suggestions were append-only JSONL files. Live history
queries repeatedly scanned nested CSV files. That made mutable suggestion state
non-transactional, allowed confirmation races, and forced UI/report readers to
understand directory and file-format details.

Research outputs still need transparent, portable files for inspection and
reproduction. Treating every experiment row as application database state would
make that workflow harder.

## Decision

Use one local SQLite operational database for:

- analyst events;
- mutable order-suggestion lifecycle;
- a query index of live decision CSV artifacts;
- schema and artifact-import metadata.

Keep research and session evidence in canonical daily CSV, parquet, JSON, plots,
and Markdown files. Import legacy JSONL/CSV incrementally and idempotently.

Do not add a generic repository interface until a second database adapter is a
real requirement. Domain stores are the external seam; SQLite is their current
implementation.

## Consequences

Positive:

- Suggestion confirmation can be claimed atomically.
- Analyst/UI queries avoid repeated full-history parsing.
- Schema changes are explicit and versioned.
- Existing research artifacts remain readable without database tooling.
- Database knowledge stays behind three small domain store interfaces.

Tradeoffs:

- Live decisions are intentionally written to both a CSV artifact and a SQLite index.
- Operators must back up mutable SQLite state separately from daily artifacts.
- A crash after an order claim leaves `submitting` state for manual reconciliation.

## Follow-Up

- Add an operator command for online backup and integrity checking before live rollout.
- Add reconciliation for stale `submitting` records using OKX client order IDs.
- Consider retention/compaction only after real database growth is measured.
