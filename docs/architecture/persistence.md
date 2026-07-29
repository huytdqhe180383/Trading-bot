# Operational Persistence

The project deliberately uses two storage forms because they serve different
jobs.

## Ownership

| Data | Canonical owner | Reason |
| --- | --- | --- |
| Analyst events | SQLite `analyst_events` | ordered queries and safe concurrent writes |
| Order suggestions | SQLite `order_suggestions` | transactional lifecycle and single confirmation claim |
| Live decision query index | SQLite `live_decisions` | fast UI/report history reads |
| Live decision evidence | daily CSV | human inspection and reproducibility |
| Backtest episodes/metrics | parquet/CSV | portable research analysis |
| Reports | Markdown/JSON | review and versioned communication |
| Models/raw data/logs | local filesystem | large or append-oriented runtime data |

The default database is `results/runtime/tradingbot.sqlite3`; set
`OPERATIONAL_DATABASE_PATH` to move it. The database, WAL files, and backups are
local runtime state and must not be committed.

## Schema Lifecycle

`tradingbot.storage.OperationalDatabase` applies ordered schema migrations and
records each applied version in `schema_migrations`. Connections enable foreign
keys, WAL mode, and a ten-second busy timeout.

Domain stores own their SQL:

- `AnalystEventStore` maps `AnalystEvent` objects to `analyst_events`.
- `OrderSuggestionStore` owns suggestion lifecycle transitions.
- `LiveDecisionStore` indexes new decisions and imports changed daily CSV files.

This keeps database knowledge local. Callers ask domain questions such as
`load_events`, `claim_for_confirmation`, or `load`; they do not build SQL.

## Compatibility And Migration

Existing `analyst_events.jsonl`, `order_suggestions.jsonl`, and live decision
CSVs are imported lazily. `artifact_imports` stores file fingerprints, so an
unchanged file is not reparsed on every request. Primary/unique keys make
re-import idempotent.

New analyst events and suggestions are written to SQLite only. Live decisions
continue writing daily CSV evidence and are also indexed in SQLite.

## Failure Behavior

- A database write failure fails the caller; it is not silently converted to an in-memory update.
- Confirmation claims use `BEGIN IMMEDIATE` and a conditional status update, so only one callback can move `pending` to `submitting`.
- A process crash after `submitting` leaves the record fail-closed for manual inspection; it does not retry an uncertain order automatically.
- SQLite backup must include the main file and any active WAL state, preferably through SQLite's online backup command or during a stopped service window.

## Inspect Locally

```powershell
python -c "from config import OPERATIONAL_DATABASE_PATH; print(OPERATIONAL_DATABASE_PATH)"
sqlite3 results/runtime/tradingbot.sqlite3 ".tables"
sqlite3 results/runtime/tradingbot.sqlite3 "select version, applied_at_utc from schema_migrations;"
```
