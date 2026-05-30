# Smooth NAV cap and trade-profile comparison

## Summary

- Implemented a smooth NAV-based single-asset cap curve for the active spot portfolio environment and live execution controller.
- Added three backtest trade profiles: `mild`, `moderate`, and `aggressive`.
- Ran all three profiles at `100 USD` initial capital with `position_cap_mode = smooth_nav`.

## Curve used

- NAV `<= 100 USD` -> max single-asset weight `0.35`
- NAV `>= 500 USD` -> max single-asset weight `0.80`
- Between those points -> smoothstep interpolation

In these runs, the observed dynamic cap ranged from `0.35` to about `0.64`, with average realized cap around `0.44`.

## Command template

```powershell
.\.venv\Scripts\python backtest.py --pipeline rl_only --realism-profile live_like --method dynamic_weighted --initial-capital 100 --position-cap-mode smooth_nav --trade-profile <profile>
```

## Results

| Profile | Session | Return | Sharpe | Max DD | Trades | Change Rate | Blocked Min-Notional Steps |
|---|---:|---:|---:|---:|---:|---:|---:|
| mild | 3 | 167.48% | 1.1645 | -31.28% | 1190 | 0.1698 | 959 |
| moderate | 5 | 165.30% | 1.1499 | -31.30% | 1215 | 0.1712 | 1216 |
| aggressive | 4 | 163.81% | 1.1450 | -31.64% | 1244 | 0.1720 | 1550 |

## Reading the experiment

- `mild` performed best on both total return and Sharpe.
- `aggressive` did trade more, but the extra looseness did not improve returns in this setup.
- As the thresholds loosened, blocked sub-minimum legs increased materially, which is expected for a `100 USD` account.
- The smooth cap appears to have constrained concentration at low NAV without causing a drawdown blow-up; max drawdown stayed near `31%` across all three runs.

## Recommendation

- Keep `smooth_nav` enabled for small-account testing.
- Use `mild` as the current default experiment profile for balances in the `100-300 USD` range.
- Only move to `moderate` or `aggressive` if you specifically want more responsiveness and are comfortable with more dust-blocked legs and churn.

## Preserved outputs

- Mild: [results/daily/2026-05-30/3](../../../results/daily/2026-05-30/3/)
- Aggressive: [results/daily/2026-05-30/4](../../../results/daily/2026-05-30/4/)
- Moderate: [results/daily/2026-05-30/5](../../../results/daily/2026-05-30/5/)

Key files per session:

- `session_metadata.json`
- `backtest_metrics.csv`
- `backtest_episode_rl_only_live_like_dynamic_weighted.parquet`
- `trade_decisions_rl_only_live_like_dynamic_weighted.csv`
- `equity_curve.png`
- `kpi_target_radar.png`
