# Ollama-Only Dynamic Training Run

Date: 2026-05-23

## Configuration Changes

- `TRADINGAGENTS_PROVIDER = "ollama"`
- `TRADINGAGENTS_PROVIDER_FALLBACKS = ["ollama"]`
- `ENSEMBLE_METHOD = "dynamic_weighted"`
- PPO default budget remains `200_000` steps.
- SAC default budget remains `50_000` steps.
- `.env.example` no longer includes ShopAI keys; local Ollama is the research default.
- `docs/architecture.md` was refreshed for the OKX-first, Ollama-only, no-heuristic-fallback architecture.

## Baseline Archive

- Archive: `K:\BTC-ETH Trading\archive\baseline_before_ollama_dynamic_training_20260523_121441`
- Included: `models/`, `logs/`, `results/`, `config.py`, `.env.example`, `README.md`, `docs/architecture.md`, and current session report notes.
- Excluded: `.env` and real secrets.

## Pre-Training Checks

- `.\.venv\Scripts\python.exe -m unittest discover -s tests`: passed, 28 tests OK.
- `.\.venv\Scripts\python.exe train.py --help`: passed.
- `.\.venv\Scripts\python.exe backtest.py --help`: passed.
- Non-fatal warning observed: ROCm SDK version mismatch warning (`compiled 7.1.1`, installed `7.2.0`).

## Training Launch

```text
PID=3636
COMMAND=.\.venv\Scripts\python.exe train.py --algo ALL --resume --device auto --seed 42 --validation-fraction 0.2
STDOUT=K:\BTC-ETH Trading\logs\training_ollama_dynamic_resume_20260523_121520.out
STDERR=K:\BTC-ETH Trading\logs\training_ollama_dynamic_resume_20260523_121520.err
STARTED=2026-05-23T12:15:20.1013259+07:00
```

- Running when report was written: `True`
- PPO resumed from `K:\BTC-ETH Trading\models\PPO\ppo_best.zip`.
- PPO split from startup log: fit rows `24,195`, validation rows `6,049`, seed `42`.
- ShopAI marker found in this training log set: `no`

## Original Post-Training Evaluation Plan

The resumed PPO/SAC process later completed and these commands were run; see the completion section below.

Planned commands:

```powershell
.\.venv\Scripts\python.exe backtest.py --pipeline rl_only --realism-profile live_like --method dynamic_weighted
.\.venv\Scripts\python.exe backtest.py --run-matrix --realism-profile live_like --method dynamic_weighted
```
## Completion And Post-Training Backtests

Training completed successfully according to `logs/training_ollama_dynamic_resume_20260523_121520.err`:

- PPO best model saved: `K:\BTC-ETH Trading\models\PPO\ppo_best.zip`
- SAC best model saved: `K:\BTC-ETH Trading\models\SAC\sac_best.zip`
- Completion marker: `Training complete for: PPO, SAC` at `2026-05-23 12:36:49 +07:00`
- The completed training process left a parent/child Python process running after the success marker; those specific PIDs were stopped before post-training backtests.

### RL-Only Dynamic Weighted Backtest

Command:

```powershell
.\.venv\Scripts\python.exe backtest.py --pipeline rl_only --realism-profile live_like --method dynamic_weighted
```

Log files:

- `logs\post_training_rl_only_dynamic_20260523_155137.out`
- `logs\post_training_rl_only_dynamic_20260523_155137.err`

Result:

- Total return: `13.05%`
- Annualized return: `5.84%`
- Sharpe: `0.1153`
- Sortino: `0.1569`
- Max drawdown: `-55.72%`
- Profit factor: `1.0116`
- Trades: `8,031`

### Local Ollama-Only Matrix

Command:

```powershell
.\.venv\Scripts\python.exe backtest.py --run-matrix --realism-profile live_like --method dynamic_weighted
```

Log files:

- `logs\post_training_matrix_dynamic_20260523_155352.out`
- `logs\post_training_matrix_dynamic_20260523_155352.err`

Matrix result from `results\backtest_matrix_metrics.csv`:

| Pipeline | Return | Sharpe | Max DD | Trades | Notes |
| --- | ---: | ---: | ---: | ---: | --- |
| `rl_only` | `13.05%` | `0.1153` | `-55.72%` | `8,031` | RL-only baseline |
| `rl_kronos` | `13.05%` | `0.1153` | `-55.72%` | `8,031` | Kronos unavailable/no-op |
| `rl_tradingagents` | `13.05%` | `0.1153` | `-55.72%` | `8,031` | Ollama timed out/no-op |
| `rl_full` | `13.05%` | `0.1153` | `-55.72%` | `8,031` | Both overlays no-op |

Provider verification:

- New post-training logs contain `provider=ollama` attempts.
- New post-training logs contain no `provider=shopai`, `SHOPAI`, or `shopai` markers.
- TradingAgents timed out after five Ollama attempts and returned unavailable/no signal.
- Kronos initialized but returned unavailable because native OHLCV input columns were missing in the backtest path.

## Train CLI Update

`train.py` now runs a post-training backtest by default after successful training:

```powershell
.\.venv\Scripts\python.exe backtest.py --pipeline rl_only --realism-profile live_like --method dynamic_weighted
```

New controls:

- `--skip-backtest`
- `--post-backtest-pipeline {rl_only,rl_kronos,rl_tradingagents,rl_full}`
- `--post-backtest-realism-profile {baseline,live_like}`
- `--post-backtest-method {mean,voting,weighted,dynamic_weighted,imca}`


