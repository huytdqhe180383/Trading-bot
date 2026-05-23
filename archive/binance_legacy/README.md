# Binance Legacy Scripts

This folder keeps Binance-specific scripts for reference after the OKX-first
migration.

Archived files:

- `run_live_binance.py`
- `data/download_historical_binance.py`
- `data/live_feed_binance.py`

Canonical active scripts now live at:

- `run_live.py` -> wrapper to `scripts/run_live.py`
- `data/download_historical.py` (CCXT, default exchange OKX)
- `data/live_feed.py` (CCXT gateway)
