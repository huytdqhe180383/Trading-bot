# BTC/ETH Trading Research System

This repository contains a BTC/ETH spot portfolio trading system built around
Stable-Baselines3 reinforcement learning agents. The current strategy trains
PPO and SAC policies on multi-timeframe Binance OHLCV features, combines their
target allocations with an ensemble agent, and evaluates the result on an
out-of-sample backtest.

This is a research and engineering project, not a promise of profitable trading.
Backtests are useful for comparison, but live crypto execution has slippage,
latency, API, liquidity, and regime risks.

## Architecture

```text
data/download_historical.py -> data/raw/*.parquet
data/preprocess.py          -> data/processed/*_{train,test}.parquet
environment/trading_env.py  -> Gymnasium BTC/ETH/USDT spot environment
train.py                    -> PPO/SAC training
agents/ensemble_agent.py    -> model loading and allocation aggregation
backtest.py                 -> out-of-sample evaluation and plots
run_live.py                 -> Binance testnet/live execution
```

Important directories:

| Path | Purpose |
| --- | --- |
| `agents/` | Ensemble logic, VAE anomaly detector, research sketches |
| `data/` | Historical download, preprocessing, and live feed builders |
| `environment/` | Portfolio environment and reward/cost mechanics |
| `metrics/` | Performance metrics and charts |
| `docs/` | Architecture, audit notes, and integration planning |
| `scripts/` | Utility and alternate operational scripts |

## Setup

Use Python 3.10-3.12 for the main project environment. The current Windows
Anaconda Python 3.13 runtime can import some packages, but it is not the safest
baseline for Stable-Baselines3, PyTorch, and ROCm work.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Configure exchange keys locally:

```powershell
Copy-Item .env.example .env
```

Then edit `.env`. Never commit `.env`.

Prepare data:

```powershell
python -m data.download_historical
python -m data.preprocess
```

## Training

Train both configured algorithms:

```powershell
python train.py --algo ALL
```

Train one algorithm:

```powershell
python train.py --algo PPO --timesteps 500000
python train.py --algo SAC --timesteps 300000
```

Best checkpoints are loaded from:

- `models/PPO/ppo_best.zip`
- `models/SAC/sac_best.zip`

The root `train.py` is the canonical training entrypoint. The `scripts/train.py`
variant adds VAE training support and should be treated as experimental until
the two entrypoints are reconciled.

## Backtest

Run the ensemble backtest on the processed test split:

```powershell
python backtest.py --method mean
```

Supported ensemble methods in code include:

- `mean`
- `voting`
- `weighted`
- `dynamic_weighted`
- `imca`

Outputs are written to `results/`:

- `backtest_metrics.csv`
- `backtest_episode.parquet`
- `equity_curve.png`
- `kpi_target_radar.png`

## Live Execution

Start with testnet or dry-run workflows only.

```powershell
python run_live.py --mode testnet
```

The CCXT multi-exchange runner is available separately:

```powershell
python scripts/run_live.py --exchange binance --mode testnet --dry-run
python scripts/run_live.py --exchange okx --mode testnet --dry-run
```

Known live-run concerns from existing logs:

- Binance timestamp errors can occur when client/server time drifts.
- Insufficient-balance errors can occur when buy orders are planned before sell
  proceeds are available.
- Testnet PnL can be misleading if the initial NAV is hardcoded instead of read
  from account state.

## Current Results

The latest stored result artifacts in this workspace were generated on
2026-03-31.

| Metric | Value |
| --- | ---: |
| Total return | 50.84% |
| Annualized return | 21.06% |
| Win rate | 47.20% |
| Profit factor | 1.0249 |
| Max drawdown | -49.55% |
| Sharpe ratio | 0.4734 |
| Sortino ratio | 0.6370 |
| Calmar ratio | 0.4249 |
| Total trades | 14,011 |

Interpretation: the strategy made money over the saved backtest window, but the
risk profile is not production-ready. Drawdown is too large, risk-adjusted
returns are weak, and trade count is high for an hourly system.

## Agent Cost Estimate

Estimated text surface for this repo, excluding raw data, processed data,
models, logs, and generated results:

- Input tokens: `55,802`
- Assumed output tokens for a planning pass: `10,000`

Formula:

```text
(input_tokens / 1_000_000 * input_rate)
+ (output_tokens / 1_000_000 * output_rate)
```

Run the estimator:

```powershell
python scripts/estimate_agent_cost.py
```

Baseline estimates:

| Model | API USD | Codex credits |
| --- | ---: | ---: |
| GPT-5.4 mini | $0.087 | 2.18 |
| GPT-5.3-Codex | n/a | 5.94 |
| GPT-5.4 | $0.290 | 7.24 |
| GPT-5.5 | $0.579 | 14.48 |

Rates are based on OpenAI's published API pricing and Codex token-based rate
card as of 2026-05-22. Recalculate before budgeting long-running multi-agent
work.

## RX6700XT Training

This machine has an AMD Radeon RX 6700 XT, but the current Python environment is
CPU-only for PyTorch:

```text
torch 2.10.0+cpu
torch.cuda.is_available() == False
torch.version.hip == None
```

Recommended path: WSL2 Ubuntu or native Linux with ROCm. Windows-native PyTorch
ROCm is not the primary target for this card because RX6700XT is RDNA2/gfx1031
and official Windows support is limited compared with Linux.

Read the detailed guide:

```text
docs/rx6700xt_rocm_training.md
```

Verify the local training stack:

```powershell
python scripts/verify_gpu_training_stack.py
```

Stable-Baselines3 note: PPO can remain CPU-bound because vectorized
environments dominate rollout collection. SAC is more likely to benefit from
GPU acceleration because replay-buffer updates spend more time in neural-network
optimization.

## Git and Data Hygiene

This repo should track source, tests, configuration examples, and documentation.
It should not track secrets or heavyweight generated artifacts.

Ignored by `.gitignore`:

- `.env`
- virtual environments
- `data/raw/`
- `data/processed/`
- `models/`
- `results/`
- `logs/`
- Python caches

Recommended first-time Git setup:

```powershell
git init -b main
git status --short
git add .
git commit -m "chore: initialize trading research repo"
```

Before committing, check that `.env`, model checkpoints, data parquet files,
logs, and generated plots are not staged.

## Verification

Run the lightweight checks:

```powershell
python -m unittest discover -s tests
python scripts/estimate_agent_cost.py
python scripts/verify_gpu_training_stack.py
```

Full backtest and training runs require the project dependencies and processed
data to be present.

## Documentation

More detailed project notes live in `docs/`, especially:

- `docs/project_comprehensive_report_and_integration_plan.md`
- `docs/codebase_audit.md`
- `docs/architecture.md`
- `docs/trading_env_documentation.md`

