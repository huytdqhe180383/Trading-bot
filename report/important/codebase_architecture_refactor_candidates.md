# Codebase Architecture Refactor Candidates

## Summary

This repository has solid domain coverage, but the codebase has grown around
several shallow seams:

- root entrypoints vs `scripts/` runners
- duplicated report/result/session artifact logic
- split execution-control logic between environment and live runtime
- flat documentation without a canonical domain glossary or ADR trail

There is no `CONTEXT.md` and no `docs/adr/` directory yet, so the repo lacks a
canonical place to define domain language and architecture decisions. That is a
real navigability issue for a system with training, backtesting, live trading,
private UI, and optional overlays.

Below are the highest-leverage deepening opportunities.

Implementation note: the first refactor pass implemented Candidate 1 and
Candidate 2 through `tradingbot.apps`, `tradingbot.runtime.artifacts`, and
`tradingbot.reports.live_daily`. See
`docs/adr/0001-application-spine-and-artifact-runtime.md` and
`docs/architecture/runtime_spine.md`.

## Candidate 1: Create An Application Spine

**Files**

- `backtest.py`
- `train.py`
- `run_live.py`
- `scripts/run_live.py`
- `scripts/live_daily_report.py`
- `scripts/run_ui.py`
- `config.py`

**Problem**

The runtime concepts are spread across root wrappers and `scripts/` modules.
Understanding one workflow requires bouncing between multiple entrypoints,
implicit path bootstrapping, and mixed CLI/runtime logic. The current seam is
shallow: deleting the root wrappers would spread more bootstrapping code into
callers, not reduce complexity.

**Solution**

Create a real application package with focused runtime modules, for example:

- `app/backtest/`
- `app/live/`
- `app/training/`
- `app/reporting/`
- `app/common/`

Keep root scripts as thin compatibility entrypoints that only parse CLI and
delegate to package functions.

**Benefits**

- Better locality for each workflow
- Clearer test surface per runtime
- Easier import graph for agents and humans
- Lower coupling between CLI bootstrapping and business logic

## Candidate 2: Unify Session Artifacts And Compact Reports

**Files**

- `backtest.py`
- `scripts/run_live.py`
- `scripts/live_daily_report.py`
- `ui/services.py`
- `report/`
- `results/`

**Problem**

Backtest sessions, live sessions, compact reports, and UI summaries all encode
artifact semantics slightly differently. The recent `PnL` vs `Unrealized PnL`
confusion happened because persistence, summarization, and UI labeling are not
owned by one deep module.

**Solution**

Introduce a dedicated artifact seam, for example:

- `artifacts/session_paths.py`
- `artifacts/live_sessions.py`
- `artifacts/backtest_sessions.py`
- `artifacts/compact_reports.py`
- `artifacts/schemas.py`

All report/result naming, writing, loading, and summary derivation should go
through that seam.

**Benefits**

- One interface for report/result persistence
- Fewer naming drifts across runtime and UI
- Stronger testability of saved artifacts
- Better compliance with `AGENTS.md` report/result storage rules

## Candidate 3: Extract A Shared Execution Policy Module

**Files**

- `environment/trading_env.py`
- `scripts/run_live.py`
- `risk/post_policy_overlay.py`
- `risk/risk_constraints.py`

**Problem**

Requested-weight to executed-weight behavior is split across the environment and
the live controller. Concepts such as deadband, cooldown, hysteresis, trailing
stop reset behavior, and risk-governor effects are close conceptually, but not
owned by one seam. This makes parity checks between training, backtest, and
live harder than they should be.

**Solution**

Extract a shared execution-policy module that takes:

- current weights
- requested weights
- prices
- regime state
- execution settings

and returns:

- executed weights
- execution diagnostics
- block reasons

Then call that module from both `BinanceSpotEnv` and the live runtime.

**Benefits**

- Better train/backtest/live parity
- Smaller environment and live runner modules
- Easier experimentation with trade profiles
- Cleaner debugging when the bot "holds too much" or "trades too much"

## Candidate 4: Separate Overlay Providers From Portfolio Fusion

**Files**

- `adapters/tradingagents_adapter.py`
- `adapters/kronos_adapter.py`
- `adapters/llm_risk_gate_adapter.py`
- `agents/meta_fusion_agent.py`
- `agents/ensemble_agent.py`

**Problem**

The overlay stack mixes provider chains, cadence logic, diagnostics, and fusion
consumption. The seams are real, but still shallow in places because provider
runtime concerns leak into portfolio-level orchestration.

**Solution**

Reorganize overlays into a stable signal interface plus adapter-specific
provider stacks, for example:

- `overlays/signals.py`
- `overlays/kronos/`
- `overlays/tradingagents/`
- `overlays/llm_risk_gate/`
- `overlays/cadence.py`
- `overlays/cache.py`

Keep `MetaFusionAgent` focused on consuming normalized signals and applying
portfolio constraints.

**Benefits**

- Better locality for overlay-specific logic
- Lower coupling between provider failures and portfolio code
- Easier ablation work
- Cleaner live safety reasoning

## Candidate 5: Reorganize Docs Around Architecture, Operators, And Research

**Files**

- `docs/`
- `README.md`
- new `CONTEXT.md`
- new `docs/adr/`

**Problem**

The documentation is valuable but flat. Architecture, deployment, ROCm,
research notes, and operational guides live side by side without an obvious
information architecture. There is also no domain glossary and no ADR trail.

**Solution**

Reorganize docs into subtrees such as:

- `docs/architecture/`
- `docs/operator/`
- `docs/research/`
- `docs/archive/`

Add:

- `CONTEXT.md` for domain language
- `docs/adr/` for architectural decisions

Seed ADRs for:

- live baseline model path and execution profile
- report/result storage rules
- private Tailscale-only UI security model

**Benefits**

- Better navigability for future agents and collaborators
- Shared domain vocabulary
- Explicit decision history
- Less repeated explanation in reports

## Recommended Order

Recommended first slice:

1. Candidate 1: application spine
2. Candidate 2: artifact/report seam
3. Candidate 3: shared execution policy

Rationale:

- these three deepen the main runtime seams first
- they reduce file size and coupling in the areas that change most often
- they create a better foundation before larger overlay or docs moves

Candidate 5 should run in parallel with the first slice where practical, but it
should follow the code reorganization rather than lead it.
