# BTC/ETH Allocation Context

This repository researches BTC/ETH spot allocation and operates a guarded OKX
execution loop. Its language separates model proposals, execution decisions,
reproducible artifacts, and mutable operational state.

## Language

**RL Policy**:
A trained PPO or SAC model that proposes BTC, ETH, and cash weights.
_Avoid_: Bot, strategy, agent

**Ensemble Allocation**:
The combined portfolio proposal produced from PPO and SAC outputs.
_Avoid_: Final trade, order

**Overlay**:
Optional context that may constrain or tilt an **Ensemble Allocation**.
_Avoid_: Fallback strategy

**Execution Controls**:
The safety and anti-churn rules that decide whether an allocation change may become orders.
_Avoid_: Policy, model

**Strategy NAV**:
The BTC, ETH, and USDT value owned by this strategy, excluding unrelated assets such as OKB.
_Avoid_: Account balance, realized PnL

**Live Session**:
One process lifetime of the live runner with numbered daily artifacts.
_Avoid_: Backtest, deployment

**Analyst Event**:
A non-executable LLM observation, answer, validation, or visible failure.
_Avoid_: Signal when no recommendation exists

**Order Suggestion**:
A bounded demo-order proposal that is inert until its requester confirms it.
_Avoid_: Pending order, trade

**Research Artifact**:
An immutable experiment or session file kept for inspection and reproduction.
_Avoid_: Database record, cache

**Operational Database**:
The local SQLite store for mutable application state and artifact query indexes.
_Avoid_: Results archive, model registry

## Relationships

- An **RL Policy** contributes to exactly one **Ensemble Allocation** per decision cycle.
- Zero or more **Overlays** may constrain an **Ensemble Allocation**.
- **Execution Controls** may turn an allocation change into zero or more orders.
- A **Live Session** produces many **Research Artifacts** and indexed decision records.
- An **Analyst Event** may produce one **Order Suggestion**, but cannot submit it.
- An **Order Suggestion** requires one explicit requester confirmation before demo submission.
- The **Operational Database** indexes **Research Artifacts** without replacing them.

## Runtime Modules

- `tradingbot.storage` owns SQLite schema migrations and operational persistence.
- `tradingbot.runtime` owns artifact/session mechanics, independent of strategy logic.
- `tradingbot.reports` turns stored decisions into operator-facing summaries.
- `tradingbot.apps` exposes stable lazy entrypoints.
- Root commands remain compatibility entrypoints.

## Invariants

- Reports belong under `report/daily/YYYY-MM-DD/` or `report/important/`.
- Preserved results belong under `results/daily/YYYY-MM-DD/` or `results/important/`.
- Research artifacts are append-only evidence; the operational database is mutable state.
- Secrets, raw data, logs, model checkpoints, and local databases are never committed.
- UI PnL is unrealized unless a closed-position accounting report explicitly says otherwise.
- RL evidence with status `ABSTAIN` is no RL opinion for LLM agents.

## Example Dialogue

> **Developer:** "The **RL Policy** says 60% BTC. Should the analyst submit it?"
> **Domain expert:** "No. It is only an **Ensemble Allocation**. **Execution Controls** decide whether orders are allowed, and an **Analyst Event** is never executable."

## Flagged Ambiguities

- "signal" previously meant both model output and LLM commentary; use **Ensemble Allocation** for RL output and **Analyst Event** for LLM output.
- "results" previously included mutable application state; use **Research Artifact** for files and **Operational Database** for mutable state.
