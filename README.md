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
adapters/llm_risk_gate_adapter.py -> low-cadence local LLM risk gate (Ollama)
agents/meta_fusion_agent.py     -> RL + overlays fusion (Kronos / TradingAgents / LLM risk gate)
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

For a small live-only server deployment, use `requirements-live.txt` instead of
the full research stack in `requirements.txt`.

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

By default, `train.py` now runs a post-training RL-only, live-like backtest
using the configured ensemble default (`dynamic_weighted`). To train without
the automatic backtest:

```powershell
python train.py --algo ALL --device auto --skip-backtest
```

If GPU is unavailable and you still want a CPU run:

```powershell
python train.py --algo ALL --device cpu
```

## backtest

Single pipeline run:

```powershell
python backtest.py --pipeline rl_full --realism-profile live_like --method dynamic_weighted
python backtest.py --pipeline rl_llm_risk_gate --realism-profile live_like --method dynamic_weighted
```

Run all ablations for a profile:

```powershell
python backtest.py --run-matrix --realism-profile live_like --method dynamic_weighted
```

Diagnose realism drift between baseline and live-like assumptions:

```powershell
python backtest.py --diagnose-realism --method dynamic_weighted
```

Compare all ensemble aggregation methods and generate a combined plot:

```powershell
python backtest.py --compare-ensemble-methods --realism-profile live_like
```

Outputs go to `results/`, including:

- `backtest_metrics.csv`
- `backtest_episode.parquet`
- `backtest_matrix_metrics.csv`
- `backtest_realism_report.csv`
- `backtest_ensemble_method_comparison.csv`
- `backtest_ensemble_method_comparison.png`
- `equity_curve.png`
- `kpi_target_radar.png`

LLM risk gate (research mode defaults):

- `LLM_RISK_GATE_ENABLED = True`
- `LLM_RISK_GATE_CADENCE = "weekly"`
- `LLM_RISK_GATE_MODE = "de_risk"`
- `LLM_RISK_GATE_TIMEOUT_SECS = 5.0`
- On timeout/unavailable provider, fallback is `allow` (no override), so RL remains authoritative.

## live execution

Primary runner (OKX default):

```powershell
python run_live.py --exchange okx --mode testnet --dry-run --max-cycles 1
```

Current live baseline:

- model source: `models/live_baseline`
- method: `dynamic_weighted`
- overlays: disabled by default (`ENABLE_KRONOS=false`, `ENABLE_TRADINGAGENTS=false`)
- execution controls: adaptive threshold + cooldown + reversal hysteresis + delayed position-reset reset

Paper/dry-run verification without private credentials:

```powershell
python run_live.py --exchange okx --mode testnet --dry-run --max-cycles 1 --bootstrap-usdt 10000
```

Enable/disable fusion components:

```powershell
python run_live.py --enable-kronos --enable-tradingagents
python run_live.py --disable-kronos --disable-tradingagents
```

TradingAgents local research mode:

- `TRADINGAGENTS_PROVIDER_FALLBACKS` in `config.py` controls order.
- Research default order is `ollama` only; no ShopAI calls are made by default.
- `ollama` is supported through `OLLAMA_BASE_URL`
  with `OLLAMA_MODEL` (default `qwen3.5:4b-gpu8k`; `qwen-3.5-4b` is accepted as an alias).
- The recommended local model profile is built from `ollama/qwen3.5-4b-gpu8k.Modelfile`
  to cap context at 8k and keep the model fully GPU-resident.
- Dormant ShopAI support remains in the adapter for future deployment, but it
  must be enabled explicitly and is intentionally absent from research defaults.
- If Ollama is unavailable, TradingAgents returns no signal and the portfolio
  remains RL-only for that layer. There is no heuristic trading fallback.

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

- `docs/rocm_runtime_architecture.md`
- `docs/rx6700xt_rocm_training.md`

## git and data hygiene

Keep secrets, raw market data, model artifacts, and logs out of commits.

- `.env` should never be committed.
- `data/raw`, `data/processed`, `models`, `results`, and `logs` are generated.

## documentation

- `docs/project_comprehensive_report_and_integration_plan.md`
- `docs/codebase_audit.md`
- `docs/architecture.md`
- `docs/digitalocean_live_deployment_guide.md`
- `docs/rocm_runtime_architecture.md`
- `docs/trading_env_documentation.md`
