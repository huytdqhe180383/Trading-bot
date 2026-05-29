# Kronos GPU Full-Layer Backtest Report

Date: 2026-05-24

## Command

```powershell
$env:KRONOS_REPO_PATH = (Resolve-Path .\external\Kronos).Path
.\.venv\Scripts\python.exe backtest.py --pipeline rl_kronos --realism-profile live_like --method dynamic_weighted
```

## GPU / ROCm Status

```text
torch: 2.9.1+rocmsdk20251207
HIP: 7.2.53150-dc1f946c0b
GPU: AMD Radeon RX 6700 XT
torch.cuda.is_available(): True
```

Kronos initialized natively:

```text
Kronos backend initialized (NeoQuasar/Kronos-mini) on cuda:0.
```

## Result

| Metric | Value |
|---|---:|
| Total return | -7.82% |
| Annualized return | -3.35% |
| Sharpe | -0.1053 |
| Sortino | -0.1417 |
| Max drawdown | -43.14% |
| CVaR 95 | -0.8311% |
| CVaR 99 | -1.3734% |
| Trades | 16,654 |

## Kronos Availability Diagnostics

| Check | Value |
|---|---:|
| Episode rows | 20,934 |
| Kronos available rate | 100.00% |
| Kronos signal count | 2 per row |
| Kronos source | `kronos` |
| Fusion has Kronos | 100.00% |
| TradingAgents available | 0.00% |

Mean final allocation:

| Asset | Mean weight |
|---|---:|
| BTC | 31.02% |
| ETH | 30.38% |
| Cash | 38.60% |

## Interpretation

This run verifies that the Kronos layer is now wired end-to-end on the ROCm GPU:
native Kronos signals were available for both symbols on every episode row.

The trading result is not acceptable yet. Compared with the latest RL-only
risk-governed run, Kronos fusion reduced performance materially. This points to
a strategy/fusion calibration problem, not a runtime availability problem.

## Preserved Artifacts

- `results/daily/2026-05-24/kronos_gpu_full_backtest/backtest_metrics.csv`
- `results/daily/2026-05-24/kronos_gpu_full_backtest/backtest_episode.parquet`
- `results/daily/2026-05-24/kronos_gpu_full_backtest/equity_curve.png`
- `results/daily/2026-05-24/kronos_gpu_full_backtest/kpi_target_radar.png`
- `report/daily/2026-05-24/kronos_gpu_full_backtest/backtest_rl_kronos_gpu_20260524_041745.out`

## Follow-Up

- Add Kronos signal attribution columns to quantify whether negative tilts,
  confidence scaling, or timing caused the performance loss.
- Test a much lower `MAX_TILT_PER_SIGNAL` for Kronos-only runs.
- Add a Kronos cadence/cache so full matrices do not require native inference
  at every hourly step.
