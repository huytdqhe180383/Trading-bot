# BTC/ETH Trading System

An OKX-first research and operations system for BTC/ETH spot allocation. PPO
and SAC propose portfolio weights; execution controls decide whether a proposed
change is safe to send. Kronos and LLM-based analysis are optional context, not
fallback trading strategies.

The current RL candidate is **not promoted**. LLM agents must treat RL evidence
with status `ABSTAIN` as no RL opinion.

## Start Here

- [Documentation map](docs/README.md)
- [Repository map](docs/development/repository_map.md)
- [Architecture](docs/architecture.md)
- [Operational persistence](docs/architecture/persistence.md)
- [Domain language](CONTEXT.md)

## Setup

Python 3.12 is the supported baseline.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Use `requirements.txt` when tests and linting are unnecessary. Use
`requirements-live.txt` on a small server that will not train models.

## Common Commands

Prepare market data:

```powershell
python -m data.download_historical --exchange okx
python -m data.preprocess
```

Train and evaluate:

```powershell
python train.py --algo ALL --device auto --require-gpu
python backtest.py --pipeline rl_only --realism-profile live_like --method dynamic_weighted
```

Run one safe testnet cycle:

```powershell
python run_live.py --exchange okx --mode testnet --dry-run --max-cycles 1 --bootstrap-usdt 10000
```

Run advisory interfaces:

```powershell
python scripts/run_analyst.py --max-cycles 1
python scripts/run_analyst_discord.py
python scripts/run_ui.py
```

## Storage Model

- `data/raw/` and `data/processed/`: local market data.
- `models/`: local checkpoints and promoted model copies.
- `results/daily/YYYY-MM-DD/`: reproducible run artifacts such as CSV and parquet.
- `report/daily/YYYY-MM-DD/`: human-readable daily reports.
- `results/runtime/tradingbot.sqlite3`: mutable operational state and query index.
- `logs/`: process logs.

Research artifacts remain files so experiments can be inspected and reproduced.
SQLite owns mutable analyst events, order-suggestion state, and the live-decision
query index. Override its location with `OPERATIONAL_DATABASE_PATH`.

## Verification

```powershell
python -m pytest -q
python -m ruff check .
```

See [Contributing](CONTRIBUTING.md) for safety and reporting rules.

## Safety

- Never commit `.env`, credentials, raw market data, checkpoints, logs, results, or the SQLite database.
- Missing overlays produce no signal; they do not invent a trade.
- Discord order suggestions require an allowlisted requester, explicit confirmation, fresh account checks, and OKX demo mode.
- Treat all performance claims as untrusted until promotion, statistical, calibration, and prospective gates pass.
