# DigitalOcean Private UI Deployment Guide

This guide covers the private web UI for the trading bot. The
intended use is:

- private access only
- phone-friendly browser use
- Tailscale-only network exposure
- no public internet ingress
- no trade buttons and no arbitrary command execution

The UI is designed to sit beside the existing bot service on the same Droplet.

## Scope

Current phase:

- login-protected dashboard
- reports/history/logs pages
- JSON APIs for the same views
- audit logging
- optional admin-only start/stop/restart controls

Out of scope for this phase:

- public deployment
- `.env` editing
- model switching
- manual trade placement
- shell access

## 1. Install Dependencies

On the Droplet:

```bash
cd /home/deploy/trading-bot
source .venv/bin/activate
pip install -r requirements-live.txt
```

## 2. Add UI Environment Variables

Open your server `.env`:

```bash
nano /home/deploy/trading-bot/.env
```

Add these values:

```dotenv
UI_USERNAME=choose-a-strong-username
UI_PASSWORD=choose-a-strong-password
UI_SESSION_SECRET=replace-with-a-long-random-secret
UI_BIND_HOST=127.0.0.1
UI_PORT=8080
UI_TAIL_LINES_DEFAULT=200
UI_LOGIN_RATE_LIMIT=5
UI_ENABLE_CONTROLS=true
UI_TRUST_TAILSCALE_HEADERS=true
UI_ALLOWED_TAILSCALE_USERS=you@example.com,friend1@example.com,friend2@example.com
UI_ADMIN_TAILSCALE_USERS=you@example.com
```

Recommended secret generation:

```bash
python - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
```

Recommended during the paper-trading week:

- keep `UI_BIND_HOST=127.0.0.1`
- keep `UI_TRUST_TAILSCALE_HEADERS=true`
- keep friends in `UI_ALLOWED_TAILSCALE_USERS`
- keep only your own Tailscale login in `UI_ADMIN_TAILSCALE_USERS`

## 3. Upload The UI Service File

The repo includes:

- [trading-bot-ui.service.example](../scripts/server/trading-bot-ui.service.example)

Copy it to the server:

```bash
sudo cp /home/deploy/trading-bot/scripts/server/trading-bot-ui.service.example /etc/systemd/system/trading-bot-ui.service
```

Reload `systemd`:

```bash
sudo systemctl daemon-reload
```

Enable and start the UI:

```bash
sudo systemctl enable trading-bot-ui
sudo systemctl start trading-bot-ui
```

Check status:

```bash
sudo systemctl status trading-bot-ui --no-pager
```

## 4. Verify Locally On The Server

Still on the Droplet:

```bash
curl http://127.0.0.1:8080/health
```

Expected response:

```json
{"status":"ok"}
```

## 5. Put It Behind Tailscale Only

The safest v1 shape is:

- app bound to `127.0.0.1`
- Tailscale installed on the Droplet
- Tailscale installed on your phone
- no public reverse proxy
- no open public firewall rule for port `8080`

If Tailscale is not already installed on the Droplet:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Then install Tailscale on your phone and sign into the same tailnet.

Two safe access patterns:

1. `tailscale serve`
2. direct Tailscale IP / MagicDNS access if you bind specifically to the
   Tailscale interface instead of localhost

For the paper-trading week, keep the simpler and safer option:

- `UI_BIND_HOST=127.0.0.1`
- expose via `tailscale serve`

Example:

```bash
sudo tailscale serve --bg --https=443 http://127.0.0.1:8080
```

Then open the Tailscale-served URL from your phone.

Do **not** use Tailscale Funnel for this UI.

For friend access, prefer:

1. same-tailnet access, or
2. Tailscale machine/service sharing

Do not widen access by binding the UI to `0.0.0.0`.

## 6. Useful Runtime Commands

Start:

```bash
sudo systemctl start trading-bot-ui
```

Stop:

```bash
sudo systemctl stop trading-bot-ui
```

Restart:

```bash
sudo systemctl restart trading-bot-ui
```

Status:

```bash
sudo systemctl status trading-bot-ui --no-pager
```

Live logs:

```bash
sudo journalctl -u trading-bot-ui -f
```

App stderr:

```bash
tail -n 200 /home/deploy/trading-bot/logs/ui_stderr.log
```

App stdout:

```bash
tail -n 200 /home/deploy/trading-bot/logs/ui_stdout.log
```

UI audit log:

```bash
tail -n 200 /home/deploy/trading-bot/logs/ui_audit.jsonl
```

## 7. What To Check On Your Phone

Before trusting it for regular use, confirm:

1. `/login` loads and prompts for credentials
2. bad password is rejected
3. dashboard loads after login
4. today report loads
5. history page loads
6. logs page loads
7. logging out clears access
8. stopping cellular/Wi-Fi path outside Tailscale blocks access

## 8. Controls Safety Rules

If you enable controls:

- keep CSRF enabled
- keep app auth or Tailscale identity auth enabled
- use exact-command `sudoers` allowlisting only
- keep friends as viewer-only users
- allow only:
  - `systemctl status trading-bot`
  - `systemctl start trading-bot`
  - `systemctl stop trading-bot`
  - `systemctl restart trading-bot`

Do not allow wildcard `sudo` command patterns.

## 9. Related Files

- [README.md](../README.md)
- [run_ui.py](../scripts/run_ui.py)
- [trading-bot-ui.service.example](../scripts/server/trading-bot-ui.service.example)
- [secure_private_ui_security_baseline.md](../report/important/secure_private_ui_security_baseline.md)
- [shared_private_ui_tailscale_guide.md](./shared_private_ui_tailscale_guide.md)
