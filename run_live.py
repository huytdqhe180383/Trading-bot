"""
Compatibility wrapper for the canonical live runner.

Primary runtime is `scripts/run_live.py` (OKX-first).
Legacy Binance runner is archived at:
`archive/binance_legacy/run_live_binance.py`.
"""

from scripts.run_live import main


if __name__ == "__main__":
    main()
