# BTC/ETH Trading Research System

This repository runs a BTC/ETH spot allocation strategy with PPO/SAC base RL,
plus optional Kronos and TradingAgents signal fusion for inference.

Primary runtime is now OKX-first. Legacy Binance-specific scripts are archived
under `archive/binance_legacy/`.

## Architecture

```text
data/download_historical.py     -> CCXT historical OHLCV (default: OKX)
data/preprocess.py              -> multi-timeframe feature engineering
train.py                        -> PPO/SAC training (GPU-capable)
agents/ensemble_agent.py        -> RL ensemble allocation
adapters/kronos_adapter.py      -> Kronos forecast adapter (fallback-safe)
adapters/tradingagents_adapter.py -> TradingAgents adapter (fallback-safe)
agents/meta_fusion_agent.py     -> RL + Kronos + TradingAgents fusion
backtest.py                     -> ablations + realism profiles + reports
scripts/run_live.py             -> canonical live/testnet execution runner
run_live.py                     -> compatibility wrapper to scripts/run_live.py
```

## setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Prepare data:

```powershell
python -m data.download_historical --exchange okx
python -m data.preprocess
```

External integrations:

```powershell
# Kronos is source-based (not a pip package): clone once and point env var.
git clone https://github.com/shiyu-coder/Kronos.git external/Kronos
$env:KRONOS_REPO_PATH = (Resolve-Path .\external\Kronos).Path
```

## training

GPU-capable training command:

```powershell
python train.py --algo ALL --device auto --require-gpu
```

If GPU is unavailable and you still want a CPU run:

```powershell
python train.py --algo ALL --device cpu
```

## backtest

Single pipeline run:

```powershell
python backtest.py --pipeline rl_full --realism-profile live_like --method mean
```

Run all ablations for a profile:

```powershell
python backtest.py --run-matrix --realism-profile live_like --method mean
```

Diagnose realism drift between baseline and live-like assumptions:

```powershell
python backtest.py --diagnose-realism --method mean
```

Outputs go to `results/`, including:

- `backtest_metrics.csv`
- `backtest_episode.parquet`
- `backtest_matrix_metrics.csv`
- `backtest_realism_report.csv`
- `equity_curve.png`
- `kpi_target_radar.png`

## live execution

Primary runner (OKX default):

```powershell
python run_live.py --exchange okx --mode testnet --dry-run
```

Enable/disable fusion components:

```powershell
python run_live.py --enable-kronos --enable-tradingagents
python run_live.py --disable-kronos --disable-tradingagents
```

TradingAgents provider fallback:

- `TRADINGAGENTS_PROVIDER_FALLBACKS` in `config.py` controls order.
- `openai` requires `OPENAI_API_KEY`.
- `groq` is supported as an alias through the OpenAI-compatible endpoint
  (`GROQ_BASE_URL`, default `https://api.groq.com/openai/v1`) and `GROQ_API_KEY`.
- `ollama` is supported as a local final fallback through `OLLAMA_BASE_URL`
  with `OLLAMA_MODEL` (default `qwen3.5:4b`; `qwen-3.5-4b` is accepted as an alias).
- Provider-specific model names should be set per backend, for example
  `OPENAI_MODEL`, `GROQ_MODEL`, and `OLLAMA_MODEL`.

## current results

The repository includes historical artifacts under `results/`, but you should
rerun training/backtest in your active environment before making deployment
decisions.

## agent cost estimate

```powershell
python scripts/estimate_agent_cost.py
```

## rx6700xt training

Check stack readiness:

```powershell
python scripts/verify_gpu_training_stack.py
```

Detailed ROCm notes:

- `docs/rx6700xt_rocm_training.md`

## git and data hygiene

Keep secrets, raw market data, model artifacts, and logs out of commits.

- `.env` should never be committed.
- `data/raw`, `data/processed`, `models`, `results`, and `logs` are generated.

## documentation

- `docs/project_comprehensive_report_and_integration_plan.md`
- `docs/codebase_audit.md`
- `docs/architecture.md`
- `docs/trading_env_documentation.md`
