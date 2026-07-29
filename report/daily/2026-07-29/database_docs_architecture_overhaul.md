# Database And Documentation Architecture Overhaul

Date: 2026-07-29

Branch: `codex/database-docs-architecture-20260729`

Pre-change checkpoint: `2a6aca6`

## Outcome

RL training was paused. Mutable operations now use a versioned SQLite database,
while reproducible research/session evidence remains in daily CSV, parquet,
JSON, plot, and Markdown artifacts. Documentation now has a short entry page,
a repository map, current architecture and persistence references, and explicit
ADRs.

The RL trust status did not change: the current candidate remains unpromoted and
LLM agents must continue treating `ABSTAIN` as no RL opinion.

## Architectural Change

The new `tradingbot.storage` module owns:

- the SQLite file and ordered schema migrations;
- WAL mode, foreign keys, a ten-second busy timeout, and transaction cleanup;
- analyst event persistence;
- order-suggestion lifecycle state;
- a query index for live decision artifacts;
- fingerprints for incremental, idempotent legacy imports.

Three domain stores form the caller-facing interfaces:

- `AnalystEventStore` writes and queries analyst events;
- `OrderSuggestionStore` owns `pending`, `submitting`, `submitted`, `failed`,
  `rejected`, and `expired` lifecycle changes;
- `LiveDecisionStore` indexes daily CSV evidence for UI and report queries.

No generic repository abstraction was added. SQLite is the only database
adapter, so a second abstraction seam would currently add interface complexity
without leverage.

## Safety Improvements

- Confirmation claims use `BEGIN IMMEDIATE` and a conditional `pending` to
  `submitting` update.
- Rejection and expiration use the same conditional transition rule.
- Exactly one concurrent callback can close or claim a pending suggestion.
- A crash after a claim leaves `submitting` state fail-closed instead of
  automatically retrying an order with uncertain exchange outcome.
- Existing JSONL and live CSV files import lazily without duplication.

## Data Ownership

| Data | Owner |
| --- | --- |
| Mutable analyst events | SQLite |
| Mutable order suggestions | SQLite |
| Live decision query history | SQLite index |
| Live decision evidence | Daily CSV |
| Backtest/research outputs | CSV/parquet/plots |
| Human reports | Markdown/JSON |

Default database path: `results/runtime/tradingbot.sqlite3`. It can be changed
with `OPERATIONAL_DATABASE_PATH` and remains ignored by Git.

## Documentation Revamp

Added or substantially rewritten:

- [Root README](../../../README.md)
- [Documentation map](../../../docs/README.md)
- [Repository map](../../../docs/development/repository_map.md)
- [Architecture](../../../docs/architecture.md)
- [Persistence architecture](../../../docs/architecture/persistence.md)
- [ADR 0002](../../../docs/adr/0002-operational-sqlite-and-artifact-separation.md)
- [Domain language](../../../CONTEXT.md)
- [Runtime spine](../../../docs/architecture/runtime_spine.md)

Removed as obsolete point-in-time material:

- March codebase audit;
- completed comprehensive integration plan;
- rubric and rubric assessment;
- completed smooth-cap implementation plan;
- unmaintained 3 MB research Word document.

Git history preserves the deleted files if historical investigation is needed.
Current audits and experimental results belong under canonical daily/important
report folders, not evergreen documentation.

## Developer Experience

- Added `requirements-dev.txt` for repeatable test/lint setup.
- Cleaned the full requirements file into readable dependency groups.
- Limited pytest discovery to `tests/`, excluding vendored Kronos tests and
  binary scratch artifacts.
- Removed all existing Ruff E/F violations in project-owned code.
- Added tests for migrations, legacy imports, decision indexing, and atomic
  suggestion lifecycle transitions.

## Verification

- `python -m pytest -q`: **252 passed**, 47 subtests passed, 2 dependency deprecation warnings.
- `python -m ruff check .`: **passed**.
- Local Markdown links: **20 documents checked, 0 broken links**.
- `git diff --check`: passed; only Git's existing Windows line-ending notices were emitted.

Machine-readable snapshot:
[verification.json](../../../results/daily/2026-07-29/database_docs_architecture/verification.json)

## Follow-Up

Before live-money use, add an operator command for online database backup and
integrity checks, then add OKX reconciliation for stale `submitting` records.
The next code-architecture deepening target is a shared execution-policy module
used by environment, backtest, and live paths.
