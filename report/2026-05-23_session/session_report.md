# Session Report

## Scope

This snapshot captures the integration work completed through 2026-05-23 in branch `codex/continue-integration-plan` at commit `14e37588f0bbf2e63a782f33fc4dbcc0ee8fa006`.

The archive preserves:

- training logs and tensorboard runs
- backtest metrics, charts, and per-pipeline parquet episodes
- TradingAgents raw decision traces
- implementation snapshots for the key integration files
- git metadata needed to map these artifacts back to the worktree state

## Key Implementation Changes

### TradingAgents integration

- Added provider chain: `openai -> groq -> ollama -> heuristic`
- Added bounded retries: `5` attempts per provider
- Added immediate provider switching for permanent errors such as `401`, `413`, and hard rate-limit/token failures
- Added local Ollama fallback using `qwen3.5:4b`
- Added alias handling for requested local model name `qwen-3.5-4b`
- Added per-call timeout: `45s`
- Added cadence-aware caching so duplicate calls are avoided during repeated same-period evaluation

### Runtime safety and cadence

- Backtest TradingAgents cadence default set to `weekly`
- Live TradingAgents cadence default set to `hourly`
- Live safety gates enforce:
  - data staleness limit: `7200s`
  - turnover kill-switch: `0.25`
  - native Kronos requirement: enabled
  - native TradingAgents requirement: enabled

### Training defaults

The default reduced training horizons now in config are:

- PPO total timesteps: `200,000`
- SAC total timesteps: `50,000`
- PPO checkpoint frequency: `20,000`
- SAC checkpoint frequency: `10,000`

No retrain was executed after the matrix rerun. The current evidence indicates the overlays are the issue, not the base RL checkpoint horizon.

## Archived Artifacts

### Results

- `artifacts/results/backtest_matrix_metrics.csv`
- `artifacts/results/backtest_metrics.csv`
- `artifacts/results/backtest_realism_report.csv`
- `artifacts/results/backtest_episode*.parquet`
- `artifacts/results/equity_curve.png`
- `artifacts/results/kpi_target_radar.png`

### Logs

- `artifacts/logs/matrix_run.err`
- `artifacts/logs/matrix_run.out`
- `artifacts/logs/PPO_eval.monitor.csv`
- `artifacts/logs/SAC_eval.monitor.csv`
- `artifacts/logs/PPO/`
- `artifacts/logs/SAC/`
- `artifacts/logs/tensorboard/`
- `artifacts/logs/tradingagents_decisions.jsonl`
- `artifacts/logs/run_testnet.log`
- `artifacts/logs/run_okx_testnet.log`
- `artifacts/logs/live_trades.csv`

### Implementation snapshot

- `artifacts/implementation/config.py`
- `artifacts/implementation/backtest.py`
- `artifacts/implementation/tradingagents_adapter.py`
- `artifacts/implementation/run_live.py`
- `artifacts/implementation/test_tradingagents_adapter.py`
- `artifacts/implementation/test_run_live_safety.py`
- `artifacts/implementation/.env.example`
- `artifacts/implementation/README.md`

## Backtest Matrix Summary

Source: `artifacts/results/backtest_matrix_metrics.csv`

| Pipeline | Return % | Sharpe | Max DD % | Trades |
| --- | ---: | ---: | ---: | ---: |
| `rl_only` | `10.42` | `0.0919` | `-58.45` | `8215` |
| `rl_kronos` | `-43.17` | `-0.5471` | `-66.09` | `8444` |
| `rl_tradingagents` | `-40.71` | `-0.5389` | `-63.72` | `7929` |
| `rl_full` | `-40.79` | `-0.5401` | `-63.76` | `7945` |

## Interpretation

- `rl_only` is the best-performing pipeline in the archived matrix.
- All overlay variants materially degrade return and risk-adjusted performance.
- `rl_kronos` is the weakest performer in this run.
- `rl_tradingagents` and `rl_full` are both substantially worse than the base RL policy.
- Based on this matrix, retraining the base PPO/SAC models was postponed because the dominant issue is overlay integration quality, not the current baseline model horizon.

## Observed Provider Behavior During Matrix Rerun

From `artifacts/logs/matrix_run.err`:

- `openai` path failed with repeated `401 Invalid token` responses from the ShopAI/proxy path
- `groq` failed with both:
  - `429 rate_limit_exceeded`
  - `413 request too large`
- local `ollama` initialized successfully with `qwen3.5:4b`
- local `ollama` then hit repeated `45s` inference timeouts and exhausted all `5` retries
- after the provider chain was exhausted, the adapter degraded to `heuristic`

This confirms the retry-and-fallback logic is bounded and completes, but the current LLM decision path is still not operationally strong enough for the backtest regime.

## Recommendation

Current evidence supports these conclusions:

1. Keep `rl_only` as the baseline reference pipeline.
2. Treat Kronos and TradingAgents as advisory overlays until their call footprint and weighting are reduced.
3. Reduce TradingAgents prompt size or call frequency before attempting another overlay-heavy matrix.
4. Retrain only after the overlay policy is redesigned or disabled for the target experiment.

## Metadata

- Git branch: `metadata/git_branch.txt`
- Git head: `metadata/git_head.txt`
- Git status snapshot: `metadata/git_status.txt`
- Git diff stat snapshot: `metadata/git_diff_stat.txt`
- Archive created at: `metadata/created_at.txt`
