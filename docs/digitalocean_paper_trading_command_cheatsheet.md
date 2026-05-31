# DigitalOcean Paper Trading Command Cheat Sheet

## Scope

This file is the practical command reference for your current DigitalOcean paper-trading server.

Current server:

- Droplet IP: `174.138.26.180`
- Linux user: `deploy`
- app dir: `/home/deploy/trading-bot`
- venv dir: `/home/deploy/trading-bot/.venv`
- service name: `trading-bot`
- exchange target: `OKX`
- mode for this week: `testnet`

Use this during the planned `1 week` paper-trading period.

---

## 1. Most Useful Commands First

If you use only a few commands during the paper-trading week, use these.

### SSH in

```powershell
ssh deploy@174.138.26.180
```

### One-screen monitor snapshot

```bash
/home/deploy/trading-bot/scripts/server/live_monitor.sh
```

### Auto-refreshing monitor

```bash
/home/deploy/trading-bot/scripts/server/live_monitor.sh --follow
```

### Daily report for today in Asia/Bangkok

```bash
cd /home/deploy/trading-bot
source .venv/bin/activate
python scripts/live_daily_report.py --date "$(TZ=Asia/Bangkok date +%F)"
```

### Daily report and export compact files

```bash
cd /home/deploy/trading-bot
source .venv/bin/activate
python scripts/live_daily_report.py --date "$(TZ=Asia/Bangkok date +%F)" --export
```

### Rolling last 24 hours report

```bash
cd /home/deploy/trading-bot
source .venv/bin/activate
python scripts/live_daily_report.py --last-hours 24
```

### Full history report since the server paper run began

```bash
cd /home/deploy/trading-bot
source .venv/bin/activate
python scripts/live_daily_report.py --full-history
```

### Check bot status

```bash
sudo systemctl status trading-bot --no-pager
```

### Restart bot

```bash
sudo systemctl restart trading-bot
```

### Read recent service logs

```bash
sudo journalctl -u trading-bot -n 200 --no-pager
```

### Tail app stderr

```bash
tail -n 100 /home/deploy/trading-bot/logs/live_stderr.log
```

---

## 2. Connect To The Server

From your Windows PC:

```powershell
ssh deploy@174.138.26.180
```

If you need to connect as root:

```powershell
ssh root@174.138.26.180
```

---

## 3. Upload Files From Your PC To The Server

### Upload `.env`

```powershell
scp "K:\BTC-ETH Trading\.env" deploy@174.138.26.180:/home/deploy/trading-bot/.env
```

### Upload live baseline model

```powershell
scp -r "K:\BTC-ETH Trading\models\live_baseline" deploy@174.138.26.180:/home/deploy/trading-bot/models/
```

If the remote `models/` folder does not exist yet, create it first on the server:

```bash
mkdir -p /home/deploy/trading-bot/models
```

### Upload updated live runner

```powershell
scp "K:\BTC-ETH Trading\scripts\run_live.py" deploy@174.138.26.180:/home/deploy/trading-bot/scripts/run_live.py
```

### Upload live-only requirements

```powershell
scp "K:\BTC-ETH Trading\requirements-live.txt" deploy@174.138.26.180:/home/deploy/trading-bot/requirements-live.txt
```

### Upload monitor helper

```powershell
scp "K:\BTC-ETH Trading\scripts\server\live_monitor.sh" deploy@174.138.26.180:/home/deploy/trading-bot/scripts/server/live_monitor.sh
```

### Upload daily report script

```powershell
scp "K:\BTC-ETH Trading\scripts\live_daily_report.py" deploy@174.138.26.180:/home/deploy/trading-bot/scripts/live_daily_report.py
```

### Upload this cheat sheet

```powershell
scp "K:\BTC-ETH Trading\docs\digitalocean_paper_trading_command_cheatsheet.md" deploy@174.138.26.180:/home/deploy/trading-bot/docs/digitalocean_paper_trading_command_cheatsheet.md
```

---

## 4. Basic Server Navigation

After SSH login:

```bash
cd /home/deploy/trading-bot
```

Activate the virtual environment:

```bash
source /home/deploy/trading-bot/.venv/bin/activate
```

Go to logs:

```bash
cd /home/deploy/trading-bot/logs
```

Go to results:

```bash
cd /home/deploy/trading-bot/results
```

---

## 5. Install Or Reinstall Live Dependencies

Use this on the server:

```bash
cd /home/deploy/trading-bot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-live.txt
```

If the `.venv` is broken and you want a clean rebuild:

```bash
cd /home/deploy/trading-bot
deactivate 2>/dev/null || true
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-live.txt
```

Quick import check:

```bash
python - <<'PY'
import numpy, pandas, ccxt
from stable_baselines3 import PPO, SAC
print("Imports OK")
PY
```

---

## 6. Verify Files Exist

### Verify live baseline model

```bash
ls -R /home/deploy/trading-bot/models/live_baseline
```

### Verify `.env`

```bash
ls -la /home/deploy/trading-bot/.env
```

### Verify monitor helper

```bash
ls -la /home/deploy/trading-bot/scripts/server/live_monitor.sh
```

---

## 7. Make The Monitor Script Executable

Run once on the server:

```bash
mkdir -p /home/deploy/trading-bot/scripts/server
chmod +x /home/deploy/trading-bot/scripts/server/live_monitor.sh
```

---

## 8. Dry Run Commands

### One-cycle dry run with bootstrap cash

```bash
cd /home/deploy/trading-bot
source .venv/bin/activate
python run_live.py --exchange okx --mode testnet --dry-run --max-cycles 1 --bootstrap-usdt 10000
```

### One-cycle dry run with bootstrap holdings

```bash
cd /home/deploy/trading-bot
source .venv/bin/activate
python run_live.py --exchange okx --mode testnet --dry-run --max-cycles 1 --bootstrap-usdt 2000 --bootstrap-btc 0.05 --bootstrap-eth 0.5
```

---

## 9. Paper Trading Commands

### Short test: 3 cycles

```bash
cd /home/deploy/trading-bot
source .venv/bin/activate
python run_live.py --exchange okx --mode testnet --max-cycles 3 --disable-kronos --disable-tradingagents
```

### Longer test: 24 cycles

```bash
cd /home/deploy/trading-bot
source .venv/bin/activate
python run_live.py --exchange okx --mode testnet --max-cycles 24 --disable-kronos --disable-tradingagents
```

### Indefinite paper-mode run

```bash
cd /home/deploy/trading-bot
source .venv/bin/activate
python run_live.py --exchange okx --mode testnet --disable-kronos --disable-tradingagents
```

---

## 10. Service Management

### Start the service

```bash
sudo systemctl start trading-bot
```

### Stop the service

```bash
sudo systemctl stop trading-bot
```

### Restart the service

```bash
sudo systemctl restart trading-bot
```

### Check service status

```bash
sudo systemctl status trading-bot --no-pager
```

### Enable auto-start at boot

```bash
sudo systemctl enable trading-bot
```

### Disable auto-start at boot

```bash
sudo systemctl disable trading-bot
```

### Reload systemd after service file changes

```bash
sudo systemctl daemon-reload
```

---

## 11. Service Logs

### Follow the service log

```bash
sudo journalctl -u trading-bot -f
```

### Show the latest 200 service log lines

```bash
sudo journalctl -u trading-bot -n 200 --no-pager
```

### Show service log since today

```bash
sudo journalctl -u trading-bot --since today --no-pager
```

If you want to remove the permissions warning for `journalctl`, run once:

```bash
sudo usermod -aG adm deploy
sudo usermod -aG systemd-journal deploy
```

Then log out and SSH back in.

---

## 12. App Logs

### Follow stdout

```bash
tail -f /home/deploy/trading-bot/logs/live_stdout.log
```

### Follow stderr

```bash
tail -f /home/deploy/trading-bot/logs/live_stderr.log
```

### Show the last 100 lines of stdout

```bash
tail -n 100 /home/deploy/trading-bot/logs/live_stdout.log
```

### Show the last 100 lines of stderr

```bash
tail -n 100 /home/deploy/trading-bot/logs/live_stderr.log
```

---

## 13. Friendlier Monitoring

### One-screen snapshot

```bash
/home/deploy/trading-bot/scripts/server/live_monitor.sh
```

### Auto-refresh every 15 seconds

```bash
/home/deploy/trading-bot/scripts/server/live_monitor.sh --follow
```

This is the command you will likely use most during the 1-week paper trial.

---

## 14. Results And Session Files

### List daily result folders

```bash
find /home/deploy/trading-bot/results/daily -maxdepth 2 -type d | sort
```

### Show the latest result files

```bash
find /home/deploy/trading-bot/results/daily -maxdepth 3 -type f | sort | tail -n 30
```

### Find the latest session folder

```bash
find /home/deploy/trading-bot/results/daily -mindepth 2 -maxdepth 2 -type d | sort | tail -n 1
```

### Show the latest session summary

```bash
latest="$(find /home/deploy/trading-bot/results/daily -mindepth 2 -maxdepth 2 -type d | sort | tail -n 1)"; cat "$latest/live_session_summary.json"
```

### Show the last decision rows from the latest session

```bash
latest="$(find /home/deploy/trading-bot/results/daily -mindepth 2 -maxdepth 2 -type d | sort | tail -n 1)"; tail -n 20 "$latest"/live_trade_decisions_*.csv
```

### Daily report for today in Asia/Bangkok

```bash
cd /home/deploy/trading-bot
source .venv/bin/activate
python scripts/live_daily_report.py --date "$(TZ=Asia/Bangkok date +%F)"
```

### Daily report for a specific day

```bash
cd /home/deploy/trading-bot
source .venv/bin/activate
python scripts/live_daily_report.py --date 2026-05-31
```

### Rolling last 24 hours report

```bash
cd /home/deploy/trading-bot
source .venv/bin/activate
python scripts/live_daily_report.py --last-hours 24
```

### Full history report

```bash
cd /home/deploy/trading-bot
source .venv/bin/activate
python scripts/live_daily_report.py --full-history
```

---

## 15. Check Current Resource Usage

### Memory

```bash
free -h
```

### Disk

```bash
df -h
```

### Running processes

```bash
ps aux | grep python
```

### Interactive process view

```bash
htop
```

---

## 16. Reboot And Shutdown

### Reboot the server

```bash
sudo reboot
```

### Shut down the server

```bash
sudo shutdown now
```

---

## 17. Edit Important Files

### Edit `.env`

```bash
nano /home/deploy/trading-bot/.env
```

### Edit the systemd service

```bash
sudo nano /etc/systemd/system/trading-bot.service
```

### Edit the live runner

```bash
nano /home/deploy/trading-bot/scripts/run_live.py
```

---

## 18. Pull Code Updates

If the server repo is connected to Git:

```bash
cd /home/deploy/trading-bot
git pull
```

If dependencies changed:

```bash
cd /home/deploy/trading-bot
source .venv/bin/activate
pip install -r requirements-live.txt
```

Then restart:

```bash
sudo systemctl restart trading-bot
```

---

## 19. 1-Week Paper Trading Routine

Recommended daily commands during the test week:

### Morning check

```bash
/home/deploy/trading-bot/scripts/server/live_monitor.sh
```

### Daily summary

```bash
cd /home/deploy/trading-bot
source .venv/bin/activate
python scripts/live_daily_report.py --date "$(TZ=Asia/Bangkok date +%F)"
```

### Daily summary plus compact export

```bash
cd /home/deploy/trading-bot
source .venv/bin/activate
python scripts/live_daily_report.py --date "$(TZ=Asia/Bangkok date +%F)" --export
```

### If something looks wrong

```bash
sudo systemctl status trading-bot --no-pager
sudo journalctl -u trading-bot -n 200 --no-pager
tail -n 100 /home/deploy/trading-bot/logs/live_stderr.log
```

### If you changed config or code

```bash
sudo systemctl restart trading-bot
```

### End-of-day result check

```bash
latest="$(find /home/deploy/trading-bot/results/daily -mindepth 2 -maxdepth 2 -type d | sort | tail -n 1)"; cat "$latest/live_session_summary.json"
```

---

## 20. Current Recommended Operating Mode

For this week, keep it exactly here:

- exchange: `okx`
- mode: `testnet`
- live baseline model: `models/live_baseline`
- Kronos: disabled
- TradingAgents: disabled
- purpose: observe stability, decision cadence, and paper PnL

Do not switch to live trading yet.

---

