# Repository Map

Use this page to answer “where should this change live?” before opening large
entrypoint files.

## Runtime Code

```text
tradingbot/
  analyst/      advisory LLM events, news, budgets, Discord interaction
  apps/         lazy application entrypoints
  execution/    OKX demo client, suggestions, confirmed execution
  reports/      report construction
  runtime/      artifact and session mechanics
  storage/      SQLite ownership, migrations, operational stores
```

These modules are the preferred home for new reusable behavior.

## Research Code

```text
data/           download, preprocessing, semantic/Kronos windows
environment/    Gymnasium portfolio environment
agents/         PPO/SAC ensemble and fusion
adapters/       optional external signal providers
risk/           portfolio constraints and semi-automatic controls
metrics/        performance calculations
```

## Entrypoints

| Command | Purpose | Implementation direction |
| --- | --- | --- |
| `train.py` | train PPO/SAC and post-evaluate | migrate orchestration toward `tradingbot.apps.train` |
| `backtest.py` | backtests, matrices, diagnostics | migrate orchestration toward `tradingbot.apps.backtest` |
| `run_live.py` | stable operator command | delegates to `scripts/run_live.py` |
| `scripts/run_live.py` | current live loop | extract shared policies into `tradingbot` |
| `scripts/run_ui.py` | private UI | delegates through app entrypoint |
| `scripts/run_analyst*.py` | analyst/Discord processes | thin wrappers |

## Interfaces And UIs

- `ui/`: FastAPI/Jinja private operations UI.
- `frontend/`: Next.js chart-first analyst UI.
- `ollama/`: local model profile.
- `scripts/server/`: systemd, monitoring, and Tailscale helpers.

## Generated And Local-Only Data

- `data/raw/`, `data/processed/`, `models/`, `logs/`, and `results/` are ignored.
- Reports follow the canonical daily/important structure in `AGENTS.md`.
- `archive/binance_legacy/` is reference-only; do not add current behavior there.
- Do not build reusable code in `report/`, `results/`, notebooks, or one-off scripts.

## Dependency Profiles

- `requirements-dev.txt`: full local development, tests, and linting.
- `requirements.txt`: research and application runtime without development tools.
- `requirements-live.txt`: reduced server runtime without training-only packages.

## Change Placement Rules

1. Put a domain behavior beside the domain term it implements.
2. Put persistence SQL inside the store that owns the record lifecycle.
3. Put artifact mechanics in `tradingbot.runtime`, not in strategy modules.
4. Keep operator scripts declarative and push reusable behavior behind a small interface.
5. Add tests at the interface callers use; avoid tests that depend on internal helper order.
