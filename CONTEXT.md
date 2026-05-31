# Project Context

This repository is a BTC/ETH spot-allocation research and operations system.
It trains PPO/SAC policies, evaluates them through backtests, and runs a
private OKX testnet/live execution loop with optional overlays.

## Domain Terms

- `RL policy`: the PPO/SAC model output that proposes BTC, ETH, and cash weights.
- `Ensemble method`: the rule that combines PPO and SAC proposals into one RL target.
- `Execution controls`: the anti-churn layer that decides whether a requested weight change becomes an order.
- `Strategy NAV`: the BTC, ETH, and USDT value tracked by the bot. It excludes non-strategy assets such as OKB.
- `Live session`: one process lifetime of the live runner, stored under `results/daily/YYYY-MM-DD/N/`.
- `Compact report`: a small JSON/Markdown summary stored under `report/daily/YYYY-MM-DD/`.
- `Overlay`: an optional signal layer, such as Kronos, TradingAgents, or the LLM risk gate.
- `Artifact`: a generated file from a run, including CSV logs, parquet episodes, plots, metadata, summaries, and reports.

## Runtime Boundaries

- `tradingbot.runtime`: shared runtime helpers that must stay independent of trading strategy details.
- `tradingbot.reports`: report builders that can be used by CLIs and the private UI.
- `tradingbot.apps`: stable application entrypoints for commands and services.
- Root scripts such as `backtest.py`, `train.py`, and `run_live.py` remain user-facing compatibility commands.

## Invariants

- Reports go under `report/daily/YYYY-MM-DD/` or `report/important/`.
- Preserved generated results go under `results/daily/YYYY-MM-DD/` or `results/important/`.
- Secrets, `.env`, venvs, external clones, raw data, logs, and model checkpoints must not be committed.
- Live and paper UI PnL should be labeled as unrealized unless a closed-position accounting report is explicitly added.

