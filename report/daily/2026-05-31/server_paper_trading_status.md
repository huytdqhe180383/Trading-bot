# Server Paper Trading Status

## Summary

- Droplet: `174.138.26.180`
- Exchange: `OKX testnet`
- Strategy: `RL-only live baseline`
- Overlays: `disabled`
- Live timezone: `Asia/Bangkok`

## PnL Reconciliation

Two different PnL windows were being compared:

- `live_stderr.log` reports `Session PnL`, which is cumulative from the start of the active service session.
- `python scripts/live_daily_report.py --date 2026-05-31` reports only the local calendar day in `Asia/Bangkok`.

Those numbers are not contradictory.

## Current Figures

As checked from the Droplet on `2026-05-31`:

- Daily PnL for `2026-05-31 Asia/Bangkok`: `+$331.34` (`+0.4273%`)
- Full history PnL since the first server paper-trading run on `2026-05-30 01:50:13 UTC`: `+$872.54` (`+1.1332%`)

Full-history calculation window:

- Start NAV: `$76,997.37`
- Latest NAV checked: `$77,869.91`
- Rows included: `29`
- Source sessions:
  - `results/daily/2026-05-30/1`
  - `results/daily/2026-05-30/2`
  - `results/daily/2026-05-30/3`
  - `results/daily/2026-05-31/1`

## Compact Report Workflow

The server now supports:

```bash
python scripts/live_daily_report.py --date "$(TZ=Asia/Bangkok date +%F)" --export
python scripts/live_daily_report.py --last-hours 24
python scripts/live_daily_report.py --full-history
```

Compact exported report files are written to:

- `report/daily/YYYY-MM-DD/live_report_*.json`
- `report/daily/YYYY-MM-DD/live_report_*.md`

This keeps raw `results/` out of Git while still preserving small tracked summaries.
