# Small-account backtest realism upgrade

## What changed

- Renamed the active training/backtest environment to `SpotPortfolioEnv` to reflect that it models a generic BTC/ETH/USDT spot portfolio rather than a Binance-only runtime.
- Kept `BinanceSpotEnv` as a compatibility alias so older imports do not break immediately.
- Added hard minimum-notional execution filtering inside the environment so sub-`10 USD` rebalance legs no longer change portfolio weights for free.
- Removed non-archived Binance live support from the active surface by limiting supported live exchange choices to OKX and removing `binance-connector` from the active requirements list.

## Why this was needed

The old environment already suppressed fees for dust trades, but it still let those sub-minimum legs change portfolio weights. For a `100 USD` account, that made the backtest more optimistic or at least less executable than a real exchange would be.

## Verification

- Tests run:

```powershell
.\.venv\Scripts\python -m unittest tests.test_audit_hotfixes tests.test_backtest_session_outputs tests.test_run_live_safety
```

- Result: passed

## Post-fix 100 USD run

```powershell
.\.venv\Scripts\python backtest.py --pipeline rl_only --realism-profile live_like --method dynamic_weighted --initial-capital 100
```

## Post-fix key results

- Initial portfolio value: `100.00` USD
- Final portfolio value: `304.91` USD
- Total return: `204.91%`
- Sharpe ratio: `1.2439`
- Max drawdown: `-31.18%`
- Total trades: `1447`
- Steps with min-notional blocking: `1053`
- Blocked asset legs: `1330`

## Comparison to pre-fix run

- Pre-fix session: [results/daily/2026-05-30/1](../../../results/daily/2026-05-30/1/)
- Post-fix session: [results/daily/2026-05-30/2](../../../results/daily/2026-05-30/2/)
- Pre-fix total return: `163.65%`
- Post-fix total return: `204.91%`

The return increased after the realism fix. That does not mean the old model was better; it means the old dust-trade behavior was materially changing the trade path. The post-fix run is more executable for small capital because blocked sub-minimum legs now stay in the prior position instead of being silently filled.

## Preserved outputs

- Post-fix metadata: [session_metadata.json](../../../results/daily/2026-05-30/2/session_metadata.json)
- Post-fix metrics: [backtest_metrics.csv](../../../results/daily/2026-05-30/2/backtest_metrics.csv)
- Post-fix episode parquet: [backtest_episode_rl_only_live_like_dynamic_weighted.parquet](../../../results/daily/2026-05-30/2/backtest_episode_rl_only_live_like_dynamic_weighted.parquet)
- Post-fix trade decisions: [trade_decisions_rl_only_live_like_dynamic_weighted.csv](../../../results/daily/2026-05-30/2/trade_decisions_rl_only_live_like_dynamic_weighted.csv)
- Post-fix equity curve: [equity_curve.png](../../../results/daily/2026-05-30/2/equity_curve.png)
- Post-fix KPI radar: [kpi_target_radar.png](../../../results/daily/2026-05-30/2/kpi_target_radar.png)
