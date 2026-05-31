# DigitalOcean Deployment Guide For Live Trading

## Purpose

This guide walks you through deploying the current live BTC/ETH trading bot to a DigitalOcean server from scratch, using the cheapest setup I would actually trust for this repo.

This is written for a beginner. It assumes:

- you already have a DigitalOcean account
- you are working from a Windows PC
- you want to run the current promoted live baseline continuously
- you want the simplest stable setup, not the most advanced one

This guide is for the current live baseline only:

- model source: `models/live_baseline`
- exchange: `OKX`
- mode to start with: `testnet`
- overlays: disabled by default
- no Ollama on the server
- no Kronos on the server
- no TradingAgents on the server

That is intentional. The cheapest server should run the RL-only live baseline, not local LLM inference.

---

## Recommended Server Size

### What is the absolute cheapest option?

DigitalOcean's cheapest Basic Droplet is currently:

- `512 MiB RAM`
- `1 vCPU`
- `10 GiB SSD`
- `$4/month`

### What should you actually use for this bot?

Use this instead:

- `Basic Droplet`
- `Regular shared CPU`
- `1 GiB RAM`
- `1 vCPU`
- `25 GiB SSD`
- `$6/month`

### Why I am not recommending the $4 server

This repo uses:

- Python
- `numpy`
- `pandas`
- `stable-baselines3`
- `torch`
- exchange/network libraries

The model files are small enough, but the runtime stack is not tiny. On a `512 MiB` server, imports plus live execution plus logs can become fragile. You can force it with swap, but it is a poor beginner setup and more likely to fail silently or get killed for memory pressure.

So:

- cheapest possible: `$4`
- cheapest sensible choice for this project: `$6`

If you insist on `$4`, I included notes later, but I do not recommend it.

---

## Expected Monthly Cost

For the recommended setup:

- Droplet: about `$6/month`
- Cloud firewall: `$0`
- Monitoring: `$0`
- Backups: leave off initially to save money

If you later enable weekly backups, DigitalOcean documents that weekly backups for Basic Droplets add `20%` of the Droplet cost. On a `$6` Droplet that is about `$1.20/month`.

Recommended starting budget:

- `~$6/month` if backups are off
- `~$7.20/month` if weekly backups are on

---

## What You Are Building

You will create:

1. one Ubuntu server on DigitalOcean
2. one non-root Linux user for the bot
3. one Python virtual environment
4. one copy of this repo on the server
5. one uploaded `.env` file with exchange credentials
6. one uploaded `models/live_baseline` folder
7. one `systemd` service so the bot starts automatically and restarts if it crashes
8. one testnet paper-trading run first
9. one path to move to live trading later

---

## High-Level Plan

1. Create an SSH key on your Windows PC
2. Create a DigitalOcean Droplet
3. Add a cloud firewall
4. Log in to the server
5. Create a safer non-root user
6. Install system packages
7. Create a Python virtual environment
8. Upload the repo and required local files
9. Install Python dependencies
10. Run a dry run
11. Run a short OKX testnet check
12. Create a `systemd` service
13. Enable auto-start
14. Monitor logs and alerts

---

## Before You Start

Prepare these on your local PC:

- your repo code
- your `.env` file
- your promoted model folder: `models/live_baseline`
- your OKX testnet API key, secret, and passphrase

Important:

- `models/` is ignored by Git in this repo
- `.env` is also ignored by Git

That means a plain `git clone` on the server is not enough by itself. You must also upload:

- `.env`
- `models/live_baseline`

---

## Step 1: Create An SSH Key On Windows

Open PowerShell on your PC and run:

```powershell
ssh-keygen -t ed25519 -C "digitalocean-trading-bot"
```

When it asks where to save it, you can press Enter to use the default:

```text
C:\Users\YOUR_NAME\.ssh\id_ed25519
```

When it asks for a passphrase:

- recommended: set one
- acceptable for simplicity: leave blank

Then print the public key:

```powershell
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub
```

Copy the full output. You will paste it into DigitalOcean.

---

## Step 2: Create The Droplet In DigitalOcean

In the DigitalOcean web dashboard:

1. Click `Create`
2. Click `Droplets`

Use these settings:

### Region

Pick the closest region to you and your exchange traffic.

For this bot, a good first choice is:

- `Singapore`

If Singapore is unavailable, pick the nearest region with the lowest expected latency for you.

### Image

Choose:

- `Ubuntu 24.04 LTS`

### Droplet Type

Choose:

- `Basic`
- `Regular SSD`
- `1 GiB / 1 vCPU / 25 GiB`

### Authentication

Choose:

- `SSH Key`

Paste the public key you copied from Windows.

### Hostname

Example:

```text
trading-bot-okx-01
```

### Extra Options

Use these:

- `Monitoring`: `On`
- `Backups`: `Off` for now
- `IPv6`: optional

Do not spend extra money on backups yet. First get the deployment stable.

### Tags

Add a tag:

```text
trading-bot
```

This helps with firewall and monitoring later.

Then create the Droplet.

Wait until it shows an IP address.

---

## Step 3: Add A Cloud Firewall

Do this before you start using the server heavily.

In DigitalOcean:

1. Go to `Networking`
2. Go to `Firewalls`
3. Create a firewall

Recommended inbound rules:

- `SSH`, port `22`, source:
  - your home IP only if possible
  - or your country/IP range if your home IP changes often

Recommended outbound rules:

- allow all outbound traffic

Attach the firewall to the Droplet, either directly or by the `trading-bot` tag.

Do not open random ports. This bot does not need inbound web traffic.

---

## Step 4: Log In To The Server

From your Windows PC:

```powershell
ssh root@YOUR_DROPLET_IP
```

If this is your first connection, type:

```text
yes
```

You should land in a Linux shell.

---

## Step 5: Create A Safer Non-Root User

Staying on `root` works, but it is not good practice. Create a dedicated user.

On the server, run:

```bash
adduser deploy
usermod -aG sudo deploy
mkdir -p /home/deploy/.ssh
cp /root/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
```

Now test the new user from your Windows PC in a second terminal:

```powershell
ssh deploy@YOUR_DROPLET_IP
```

If that works, go back to the server and harden SSH a bit:

```bash
sudo nano /etc/ssh/sshd_config
```

Make sure these settings exist:

```text
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
```

Save and exit, then restart SSH:

```bash
sudo systemctl restart ssh
```

Important:

- do not close your working SSH session until you verify that `ssh deploy@YOUR_DROPLET_IP` still works

---

## Step 6: Update The Server And Install Base Packages

Log in as `deploy` and run:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y git python3 python3-venv python3-pip build-essential htop unzip
```

These are enough for the basic live bot.

---

## Step 7: Add Swap

Even on the `$6` server, add swap. It gives you a safety cushion.

Run:

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h
```

You should now see swap listed.

Why do this:

- prevents low-memory crashes from being more likely
- helps a small server survive imports and transient memory spikes

Swap is slower than RAM, but it is still better than a hard crash.

---

## Step 8: Create The App Directory

Run:

```bash
mkdir -p /home/deploy/trading-bot
cd /home/deploy/trading-bot
```

---

## Step 9: Get The Repo Onto The Server

You have two practical choices.

### Option A: Git Clone

Use this if your GitHub repo is public, or if you already know how to authenticate cleanly.

Example:

```bash
git clone https://github.com/huytdqhe180383/Trading-bot.git /home/deploy/trading-bot
```

### Option B: Upload A ZIP Or Copy The Repo Folder

Use this if you are not comfortable with Git authentication yet.

From your Windows PC, you can copy the whole project folder:

```powershell
scp -r "K:\BTC-ETH Trading\*" deploy@YOUR_DROPLET_IP:/home/deploy/trading-bot/
```

That is simple but heavy. A cleaner version is:

1. clone the repo on the server
2. upload only the missing local-only files from your PC

That is the method I recommend.

---

## Step 10: Upload The Local-Only Files The Server Needs

Because `.env` and `models/` are not committed, upload them manually from your Windows PC.

### Upload `.env`

From PowerShell on your PC:

```powershell
scp "K:\BTC-ETH Trading\.env" deploy@174.138.26.180:/home/deploy/trading-bot/.env
```

### Upload the live baseline model

First create the remote directory on the server:

```bash
mkdir -p /home/deploy/trading-bot/models
```

From PowerShell on your PC:

```powershell
scp -r "K:\BTC-ETH Trading\models\live_baseline" deploy@174.138.26.180:/home/deploy/trading-bot/models/
```

If Windows `scp` still complains, use this fallback form instead:

```powershell
scp -r "K:\BTC-ETH Trading\models\live_baseline" deploy@174.138.26.180:/home/deploy/trading-bot/
```

Then on the server move it into place:

```bash
mkdir -p /home/deploy/trading-bot/models
mv /home/deploy/trading-bot/live_baseline /home/deploy/trading-bot/models/live_baseline
```

### Verify on the server

Run:

```bash
ls -R /home/deploy/trading-bot/models/live_baseline
```

You should see:

- `PPO/ppo_best.zip`
- `SAC/sac_best.zip`
- `baseline_metadata.json`

---

## Step 11: Check And Edit `.env`

On the server:

```bash
cd /home/deploy/trading-bot
nano .env
```

For the first deployment, keep it simple:

- use OKX testnet credentials first
- keep Kronos disabled
- keep TradingAgents disabled
- do not try to run Ollama on this cheap server

You want values consistent with the current live baseline.

Make sure the required OKX testnet values exist:

```text
OKX_TESTNET_API_KEY=...
OKX_TESTNET_SECRET_KEY=...
OKX_TESTNET_PASSPHRASE=...
```

Also confirm these are effectively disabled:

```text
ENABLE_KRONOS=false
ENABLE_TRADINGAGENTS=false
```

If your `.env` has extra local Windows-only path settings, remove or fix them.

---

## Step 12: Create The Python Virtual Environment

On the server:

```bash
cd /home/deploy/trading-bot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-live.txt
```

This may take a little while.

Why `requirements-live.txt` and not `requirements.txt`:

- `requirements.txt` includes backtest/research packages
- one of those packages, `empyrical`, currently fails to build under Python `3.12`
- the live runner does not need that package
- the live server should install only the runtime needed for live trading

If you already ran the wrong install command and hit the `empyrical` error, the safest recovery is:

```bash
cd /home/deploy/trading-bot
deactivate 2>/dev/null || true
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-live.txt
```

When it finishes, test the key imports:

```bash
python - <<'PY'
import numpy, pandas, torch, ccxt
print("Imports OK")
PY
```

If you see `Imports OK`, the environment is basically healthy.

---

## Step 13: Create Required Runtime Folders

On the server:

```bash
cd /home/deploy/trading-bot
mkdir -p logs results report
```

---

## Step 14: First Dry Run

Do this before using exchange credentials for an actual paper order.

On the server:

```bash
cd /home/deploy/trading-bot
source .venv/bin/activate
python run_live.py --exchange okx --mode testnet --dry-run --max-cycles 1 --bootstrap-usdt 10000
```

What this does:

- loads the model
- checks your environment
- builds the live decision flow
- does not place a real testnet order

If this fails, stop and fix it before going further.

---

## Step 15: Run A Short OKX Testnet Paper Check

After the dry run succeeds:

```bash
cd /home/deploy/trading-bot
source .venv/bin/activate
python run_live.py --exchange okx --mode testnet --max-cycles 3 --disable-kronos --disable-tradingagents
```

Why `3` cycles:

- enough to confirm the loop works
- short enough to debug quickly

After it runs, inspect:

```bash
ls results/daily
find results/daily -maxdepth 3 -type f | tail -n 20
```

You should see a new session folder with:

- `live_session_metadata.json`
- `live_session_summary.json`
- `live_trade_decisions_okx_testnet.csv`

If that works, the server is ready for an always-on service.

---

## Step 16: Create A Systemd Service

This is what makes the bot run continuously and restart automatically.

Create the service file:

```bash
sudo nano /etc/systemd/system/trading-bot.service
```

Paste this:

```ini
[Unit]
Description=BTC ETH Trading Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=deploy
WorkingDirectory=/home/deploy/trading-bot
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/deploy/trading-bot/.venv/bin/python run_live.py --exchange okx --mode testnet --disable-kronos --disable-tradingagents
Restart=always
RestartSec=30
KillSignal=SIGINT
TimeoutStopSec=90
StandardOutput=append:/home/deploy/trading-bot/logs/live_stdout.log
StandardError=append:/home/deploy/trading-bot/logs/live_stderr.log

[Install]
WantedBy=multi-user.target
```

This version starts in `testnet` mode. That is correct for first deployment.

Do not switch to live mode yet.

Now reload `systemd`:

```bash
sudo systemctl daemon-reload
```

Enable the service so it starts on boot:

```bash
sudo systemctl enable trading-bot
```

Start it:

```bash
sudo systemctl start trading-bot
```

Check status:

```bash
sudo systemctl status trading-bot --no-pager
```

If it is healthy, you should see it as `active (running)`.

---

## Step 17: Watch Logs

Use these commands:

### Service logs

```bash
sudo journalctl -u trading-bot -f
```

### App stdout log

```bash
tail -f /home/deploy/trading-bot/logs/live_stdout.log
```

### App stderr log

```bash
tail -f /home/deploy/trading-bot/logs/live_stderr.log
```

### Latest live results

```bash
find /home/deploy/trading-bot/results/daily -maxdepth 3 -type f | tail -n 30
```

### Friendlier monitor view

This repo includes a simple server-side monitor helper:

```bash
chmod +x /home/deploy/trading-bot/scripts/server/live_monitor.sh
/home/deploy/trading-bot/scripts/server/live_monitor.sh
```

Auto-refresh mode:

```bash
/home/deploy/trading-bot/scripts/server/live_monitor.sh --follow
```

It shows:

- `systemd` status
- memory and disk
- latest live session summary
- recent decision rows
- stderr tail

This is much easier for daily checks than manually typing multiple commands.

### Daily report command

For a clean per-day paper-trading summary in `Asia/Bangkok`:

```bash
cd /home/deploy/trading-bot
source .venv/bin/activate
python scripts/live_daily_report.py --date "$(TZ=Asia/Bangkok date +%F)"
```

Export compact tracked files too:

```bash
cd /home/deploy/trading-bot
source .venv/bin/activate
python scripts/live_daily_report.py --date "$(TZ=Asia/Bangkok date +%F)" --export
```

Rolling last-24h summary:

```bash
cd /home/deploy/trading-bot
source .venv/bin/activate
python scripts/live_daily_report.py --last-hours 24
```

This report reads all live decision CSVs and groups rows by local timezone, so
it is safer than relying on the raw `results/daily/YYYY-MM-DD/` folder name.

### Optional: remove the `journalctl` permission warning

The warning means your `deploy` user cannot read the full system journal without `sudo`.

Simplest path:

- keep using `sudo journalctl ...`

If you want `deploy` to read journals without `sudo`, run once:

```bash
sudo usermod -aG adm deploy
sudo usermod -aG systemd-journal deploy
```

Then fully log out and log back in.

---

## Step 18: Set Up DigitalOcean Monitoring Alerts

In the DigitalOcean dashboard:

1. open the Droplet
2. go to `Insights`
3. confirm monitoring is enabled
4. create alerts

Recommended first alerts:

- CPU usage above `90%` for `10 minutes`
- memory usage above `85%` for `10 minutes`
- disk usage above `85%`

This is especially important on a small server.

---

## Step 19: Reboot Test

You want proof that the service comes back automatically after a restart.

On the server:

```bash
sudo reboot
```

Wait one or two minutes, reconnect:

```powershell
ssh deploy@YOUR_DROPLET_IP
```

Then check:

```bash
sudo systemctl status trading-bot --no-pager
```

If it is active after reboot, your baseline automation is working.

---

## Step 20: How To Update The Bot Later

Typical update routine:

1. stop the service
2. update code
3. upload new model if needed
4. restart the service
5. verify logs

Commands:

```bash
sudo systemctl stop trading-bot
cd /home/deploy/trading-bot
git pull
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl start trading-bot
sudo systemctl status trading-bot --no-pager
```

If the new promoted model is local-only, re-upload it from your PC:

```powershell
scp -r "K:\BTC-ETH Trading\models\live_baseline" deploy@YOUR_DROPLET_IP:/home/deploy/trading-bot/models/
```

---

## Step 21: How To Switch From Testnet To Live

Do not do this until you are satisfied with paper trading.

When ready:

1. update `.env` with live OKX credentials
2. edit the `systemd` service
3. change `--mode testnet` to `--mode live`
4. restart the service

Edit the service:

```bash
sudo nano /etc/systemd/system/trading-bot.service
```

Change:

```text
--mode testnet
```

to:

```text
--mode live
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl restart trading-bot
sudo systemctl status trading-bot --no-pager
```

Only do this after you have confirmed:

- the bot starts cleanly
- the session artifacts are being written
- the paper results look sane
- your anti-churn settings are the promoted baseline

---

## Recommended Day-1 Operating Routine

For the first week, do this once or twice daily:

1. SSH into the server
2. check `systemctl status`
3. check the latest session folder
4. inspect `live_session_summary.json`
5. inspect the latest rows in `live_trade_decisions_*.csv`
6. watch for repeated restarts or memory pressure

Useful commands:

```bash
sudo systemctl status trading-bot --no-pager
free -h
df -h
tail -n 50 /home/deploy/trading-bot/logs/live_stdout.log
tail -n 50 /home/deploy/trading-bot/logs/live_stderr.log
```

---

## If You Insist On The $4 Droplet

You can try:

- `Basic`
- `512 MiB`
- `1 vCPU`
- `$4/month`

If you do:

1. definitely create swap
2. keep overlays disabled
3. do not run Ollama
4. expect lower stability
5. monitor memory usage aggressively

I would only use this if:

- you are experimenting
- you accept occasional instability
- you are willing to rebuild if the process becomes unreliable

For actual unattended paper/live trading, the `$6` server is the right floor.

---

## Common Problems And Fixes

### Problem: `Permission denied (publickey)`

Cause:

- SSH key was not added correctly
- wrong username
- wrong private key

Fix:

- verify you are connecting as `deploy`
- confirm the public key exists in `/home/deploy/.ssh/authorized_keys`
- confirm local key path is correct

### Problem: Service restarts repeatedly

Cause:

- bad `.env`
- missing model files
- Python dependency issue

Fix:

```bash
sudo systemctl status trading-bot --no-pager
journalctl -u trading-bot -n 200 --no-pager
tail -n 200 /home/deploy/trading-bot/logs/live_stderr.log
```

### Problem: `models/live_baseline` missing

Cause:

- models are not in Git

Fix:

- upload the folder manually with `scp`

### Problem: Server runs out of memory

Cause:

- Droplet too small
- no swap
- too many extra services running

Fix:

- add swap
- stop unnecessary processes
- move up from `$4` to `$6`

### Problem: No trades happen

Possible causes:

- anti-churn controller blocks micro-adjustments
- market state does not justify a trade
- exchange credentials or balances are not what you think

Fix:

- inspect `live_trade_decisions_okx_testnet.csv`
- inspect live session summary and logs
- verify target weights and current weights

---

## Simple Deployment Checklist

Use this as the short version.

### Local PC

- create SSH key
- confirm `.env` is ready
- confirm `models/live_baseline` exists

### DigitalOcean

- create Ubuntu 24.04 Droplet
- choose `Basic 1 GiB / $6`
- add SSH key
- enable monitoring
- create firewall

### Server

- create `deploy` user
- install packages
- add swap
- clone repo
- upload `.env`
- upload `models/live_baseline`
- create `.venv`
- `pip install -r requirements-live.txt`
- run dry run
- run short OKX testnet check
- create `systemd` service
- enable and start service
- verify after reboot

---

## What I Recommend You Do First

If you want the lowest-risk path:

1. create the `$6` Droplet
2. deploy in `testnet` mode only
3. let it run for at least `24-72` hours
4. check logs and session output daily
5. only then consider switching to live mode

That is the right sequence for this project.

---

## Official References

These are the main official pages I used for pricing and setup guidance:

- DigitalOcean Droplet pricing: https://www.digitalocean.com/pricing/droplets
- DigitalOcean Droplet pricing details: https://docs.digitalocean.com/products/droplets/details/pricing/
- How to create a Droplet: https://docs.digitalocean.com/docs/droplets/how-to/create
- Recommended Droplet setup: https://docs.digitalocean.com/products/droplets/getting-started/recommended-droplet-setup/
- Cloud firewalls: https://docs.digitalocean.com/products/networking/firewalls/how-to/create/
- Monitoring quickstart: https://docs.digitalocean.com/products/monitoring/getting-started/quickstart/
- Monitoring alerts: https://docs.digitalocean.com/products/monitoring/how-to/manage-alerts/
- Backups pricing: https://docs.digitalocean.com/products/backups/details/pricing/
