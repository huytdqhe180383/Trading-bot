# Backtest with 100 USD initial capital

## Summary

- Added a configurable `--initial-capital` flag to `backtest.py`.
- Threaded the selected starting capital through environment setup, benchmark NAV construction, metric calculation, and session metadata.
- Ran a scaled backtest with `100.0` USD starting capital on the local-only RL pipeline.

## Run command

```powershell
.\.venv\Scripts\python backtest.py --pipeline rl_only --realism-profile live_like --method dynamic_weighted --initial-capital 100
```

## Key results

- Initial portfolio value: `100.00` USD
- Final portfolio value: `263.65` USD
- Total return: `163.65%`
- Annualised return: `50.03%`
- Sharpe ratio: `1.1100`
- Max drawdown: `-31.24%`
- Total trades: `1406`

## Preserved outputs

- Session metadata: [session_metadata.json](../../../results/daily/2026-05-30/1/session_metadata.json)
- Metrics: [backtest_metrics.csv](../../../results/daily/2026-05-30/1/backtest_metrics.csv)
- Episode parquet: [backtest_episode_rl_only_live_like_dynamic_weighted.parquet](../../../results/daily/2026-05-30/1/backtest_episode_rl_only_live_like_dynamic_weighted.parquet)
- Trade decisions: [trade_decisions_rl_only_live_like_dynamic_weighted.csv](../../../results/daily/2026-05-30/1/trade_decisions_rl_only_live_like_dynamic_weighted.csv)
- Equity curve: [equity_curve.png](../../../results/daily/2026-05-30/1/equity_curve.png)
- KPI radar: [kpi_target_radar.png](../../../results/daily/2026-05-30/1/kpi_target_radar.png)

## Notes

- The session metadata confirms `"initial_capital": 100.0`.
- Because this backtest does not appear to enforce exchange minimum order sizes, scaling down capital mostly changes dollar-denominated outputs while percentage metrics remain strategy-relative.
