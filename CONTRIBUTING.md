# Contributing

This is a local research trading system. Treat every change as potentially
financially sensitive, even when it only touches backtests.

## Local Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

Never commit `.env`, raw market data, model checkpoints, logs, or generated
result artifacts.

## Checks

Run the test suite before committing:

```powershell
python -m pytest -q
```

Run a syntax check for touched Python files when making small targeted edits:

```powershell
.\.venv\Scripts\python.exe -m py_compile train.py backtest.py
```

If Ruff is installed, run:

```powershell
python -m ruff check .
```

When changing operational persistence, also run:

```powershell
python -m pytest tests/test_operational_storage.py tests/test_analyst_service.py tests/test_okx_execution.py -q
```

See [Repository map](docs/development/repository_map.md) before adding a new
top-level module. Reusable application behavior belongs under `tradingbot/`;
operator scripts should remain thin.

## Backtest Discipline

- Use `--realism-profile live_like` for serious comparisons.
- Use `--method dynamic_weighted` as the current default candidate.
- Keep `rl_only` as the reference when overlays are unavailable.
- Do not add heuristic fallbacks for Kronos or TradingAgents. Missing overlays
  must be no-op signals so the RL policy remains the source of truth.

## Reporting

Save notable runs under the canonical daily or important report folders with:

- command used
- model checkpoint/version
- key metrics
- log paths
- known warnings or unavailable providers

Generated result snapshots follow the same `daily/YYYY-MM-DD` or `important`
split under `results/`. Never commit the local operational SQLite database.
