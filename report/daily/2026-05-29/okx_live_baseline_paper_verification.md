# OKX Live Baseline Promotion And Paper Verification

## Summary

The promoted de-overtraded champion has been moved into the live baseline path and the canonical OKX runner now uses it by default.

Live baseline now means:
- model source: `models/live_baseline`
- ensemble method: `dynamic_weighted`
- Kronos: disabled by default
- TradingAgents: disabled by default
- execution controls: promoted anti-churn settings from the champion pass

## What Changed

Code/runtime changes:
- Added `LIVE_BASELINE_MODEL_DIR` and pointed live inference to `models/live_baseline` by default.
- Promoted execution-control defaults in `config.py`:
  - `REBALANCE_THRESHOLD_NORMAL=0.03`
  - `REBALANCE_THRESHOLD_STRESS=0.05`
  - `REBALANCE_THRESHOLD_CRISIS=0.08`
  - `MIN_HOLD_BARS=4`
  - `MATERIAL_TRADE_THRESHOLD=0.05`
  - `REVERSAL_HYSTERESIS_MULT=1.5`
  - `POSITION_RESET_WEIGHT_THRESHOLD=0.05`
  - `POSITION_RESET_PERSIST_BARS=2`
- Changed live defaults to RL-only baseline:
  - `ENABLE_KRONOS=False`
  - `ENABLE_TRADINGAGENTS=False`
- Extended `scripts/run_live.py` with:
  - baseline model-dir selection
  - live execution controller parity with the promoted backtest baseline
  - credential preflight behavior
  - finite-cycle runs via `--max-cycles`
  - bootstrap dry-run balances for public verification mode

Promoted baseline snapshot:
- source: `models/best/2026-05-28/5/models`
- deployed copy: `models/live_baseline/`
- metadata: `models/live_baseline/baseline_metadata.json`

## Verification

Commands run:

```powershell
python -m unittest discover -s tests
python run_live.py --exchange okx --mode testnet --max-cycles 1 --disable-kronos --disable-tradingagents
```

Test result:
- `73` tests passed

OKX paper-trading result:
- Date/time: `2026-05-29 00:03:03 +07:00`
- Exchange: `OKX`
- Mode: `testnet`
- Method: `dynamic_weighted`
- Model dir: `models/live_baseline`
- Status: successful paper execution with filled orders

Observed target and fills:
- target weights: BTC `0.5010`, ETH `0.4968`, USDT `0.0022`
- order 1: `SELL 0.07674582 BTCUSDT`
  - fill id: `3606611170248642560`
- order 2: `BUY 2.717148 ETHUSDT`
  - fill id: `3606611175013371904`
- reported NAV: `$76,956.87`

Preserved verification artifacts:
- `../../../results/daily/2026-05-29/1/okx_testnet_live_trades_excerpt.csv`
- `../../../results/daily/2026-05-29/1/okx_testnet_run_excerpt.log`
- `../../../results/daily/2026-05-29/1/live_baseline_metadata.json`

## Notes

- The shell environment itself did not expose `OKX_TESTNET_*` variables, but `run_live.py` successfully loaded credentials from `.env` through `load_dotenv()`.
- This pass verified the new baseline on actual OKX testnet/paper execution, not only dry-run.
- The live runner still supports Kronos/TradingAgents toggles, but the promoted baseline keeps them off by default because the best validated profile is RL-only.
