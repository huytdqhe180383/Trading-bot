# Live Runner Merge Regression Fix

## Summary
The live bot crash on the server after switching to `codex/refactor-application-spine` was caused by a bad merged version of `scripts/run_live.py` on the branch tip.

Symptoms:
- `ImportError: cannot import name 'POSITION_CAP_MODE' from 'config'` on the old mixed checkout
- after aligning the server branch, `NameError: get_live_session_tz is not defined`

## Root Cause
The remote branch tip had newer nav-scaled position-cap changes partially merged into `scripts/run_live.py`:
- it referenced `apply_position_cap_mode(...)`
- it referenced `_compute_nav_scaled_max_asset_weight(...)`
- it called `get_live_session_tz()`

But the file was missing:
- the import for `apply_position_cap_mode`
- the import for `compute_nav_scaled_max_asset_weight`
- the `get_live_session_tz()` helper definition

This left the live runner internally inconsistent even after the server checkout itself was corrected.

## Fix
Patched [scripts/run_live.py](/K:/BTC-ETH Trading/scripts/run_live.py) to:
- import `apply_position_cap_mode`
- import `compute_nav_scaled_max_asset_weight as _compute_nav_scaled_max_asset_weight`
- restore `get_live_session_tz()`

## Verification
Commands run locally:

```powershell
python -m unittest tests.test_run_live_safety
python -m unittest discover -s tests
python run_live.py --exchange okx --mode testnet --disable-kronos --disable-tradingagents --max-cycles 1 --dry-run
```

Results:
- targeted tests passed: `13`
- full suite passed: `132`
- one-cycle dry-run completed and logged a normal cycle

## Server Recovery
After pulling the fixed branch on the server:

```bash
cd ~/trading-bot
source .venv/bin/activate
git pull --ff-only origin codex/refactor-application-spine
python run_live.py --exchange okx --mode testnet --disable-kronos --disable-tradingagents --max-cycles 1
sudo systemctl restart trading-bot
sudo systemctl status trading-bot --no-pager
```
