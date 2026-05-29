# Live Baseline Follow-Up And Automation Note

## Summary

This follow-up completed all three requested actions:
- backtest now defaults to the promoted live baseline model directory
- live runs now create per-run session artifacts under `results/daily/YYYY-MM-DD/N/`
- a 24-cycle OKX testnet paper soak has been started in the background

## Implemented Changes

Code changes:
- `backtest.py`
  - default `--model-dir` now resolves to `models/live_baseline`
  - falls back to `models/` only if the live baseline directory is incomplete
- `scripts/run_live.py`
  - creates a dedicated session folder per invocation under `results/daily/YYYY-MM-DD/N/`
  - writes:
    - `live_session_metadata.json`
    - `live_trade_decisions_<exchange>_<mode>.csv`
    - `live_session_summary.json`
  - supports bounded runs with `--max-cycles`
- tests updated in:
  - `tests/test_backtest_session_outputs.py`
  - `tests/test_run_live_safety.py`

Verification:
- `python -m unittest tests.test_run_live_safety tests.test_backtest_session_outputs tests.test_audit_hotfixes`
- passed: `27` tests
- `python -m unittest discover -s tests`
- passed earlier in this pass: `73` tests

## Backtest Default Verification

Ran:

```powershell
python backtest.py --pipeline rl_only --realism-profile live_like --method dynamic_weighted
```

Confirmed default model source:
- `model_dir = K:\BTC-ETH Trading\models\live_baseline`

Result session:
- `results/daily/2026-05-29/3/`

Headline metrics:
- return: `159.47%`
- sharpe: `1.0911`
- max drawdown: `-31.20%`
- trades: `1,560`

## 24-Cycle Paper Soak

Started background process:
- process id: `3620`
- command profile: `run_live.py --exchange okx --mode testnet --max-cycles 24 --disable-kronos --disable-tradingagents`

Current session folder:
- `results/daily/2026-05-29/4/`

Current artifacts already present:
- `results/daily/2026-05-29/4/live_session_metadata.json`
- `results/daily/2026-05-29/4/live_trade_decisions_okx_testnet.csv`
- `results/daily/2026-05-29/4/live_session_summary.json`

The first recorded cycle in that soak shows the anti-churn controller working as intended:
- requested delta: very small
- `rebalance_blocked_by_deadband = True`
- no unnecessary orders submitted

## Automation Recommendation

Your intuition is correct: if you want this running continuously, use a small always-on server and run the bot as a long-lived process.

Recommended path:
1. Use a small Linux VM, not GitHub-hosted Actions, for the trading process itself.
2. Run the bot under `systemd` or Docker with automatic restart.
3. Keep GitHub Actions only for CI, health checks, or deployment, not as the 24/7 bot host.

Why:
- GitHub-hosted runners have a `6 hour` job execution limit.
- GitHub self-hosted runners can run longer, but Actions is still job-oriented; official limits include `5 days` job execution and `24 hours` queue time, which is not the right primitive for a permanent trading daemon.
- Oracle Cloud Always Free currently offers Arm `Ampere A1` compute equivalent to `4 OCPUs` and `24 GB` memory total, which is enough for this bot.
- Google Cloud free features exist, but the free `e2-micro` tier is much smaller and also requires a billing account, so it is a weaker fit for a 24/7 trading process.

Practical recommendation:
- Best free-server candidate: Oracle Cloud Always Free Ampere VM.
- Best runtime model: Ubuntu VM + Python venv + `systemd` service + daily log rotation + a small health-check script.
- Use GitHub only to push updates; deploy from the repo onto the VM.

Official references:
- Oracle Always Free resources: https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm
- GitHub Actions limits: https://docs.github.com/en/actions/reference/limits
- GitHub Actions billing/usage: https://docs.github.com/en/actions/learn-github-actions/usage-limits-billing-and-administration
- Google Cloud free program / Compute docs: https://docs.cloud.google.com/free/docs/free-cloud-features

## Suggested Production Automation Layout

Minimal robust stack:
- one VM
- one service account / SSH key
- one `.env`
- one `systemd` service running:
  - `python run_live.py --exchange okx --mode live --disable-kronos --disable-tradingagents`
- one `systemd` timer or cron task for backups/report snapshots
- one health-check script that alerts if:
  - process is down
  - no new live decision row appears for > 2 cycles
  - exchange credentials fail

This is the right next step if you want, and I can implement the server-side deployment files next.
