# Contributing

This is a local research trading system. Treat every change as potentially
financially sensitive, even when it only touches backtests.

## Local Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Never commit `.env`, raw market data, model checkpoints, logs, or generated
result artifacts.

## Checks

Run the unit suite before committing:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Run a syntax check for touched Python files when making small targeted edits:

```powershell
.\.venv\Scripts\python.exe -m py_compile train.py backtest.py
```

If Ruff is installed, run:

```powershell
.\.venv\Scripts\ruff.exe check .
```

## Backtest Discipline

- Use `--realism-profile live_like` for serious comparisons.
- Use `--method dynamic_weighted` as the current default candidate.
- Keep `rl_only` as the reference when overlays are unavailable.
- Do not add heuristic fallbacks for Kronos or TradingAgents. Missing overlays
  must be no-op signals so the RL policy remains the source of truth.

## Reporting

Save notable runs under `report/` with:

- command used
- model checkpoint/version
- key metrics
- log paths
- known warnings or unavailable providers
