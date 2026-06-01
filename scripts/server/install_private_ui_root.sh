#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/home/deploy/trading-bot}"
APP_USER="${APP_USER:-deploy}"
UI_SERVICE_NAME="${UI_SERVICE_NAME:-trading-bot-ui}"
BOT_SERVICE_NAME="${BOT_SERVICE_NAME:-trading-bot}"
ENV_FILE="$APP_DIR/.env"
SERVICE_FILE="/etc/systemd/system/${UI_SERVICE_NAME}.service"
SUDOERS_FILE="/etc/sudoers.d/${UI_SERVICE_NAME}"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi

if [[ ! -d "$APP_DIR" ]]; then
  echo "App directory not found: $APP_DIR" >&2
  exit 1
fi

mkdir -p "$APP_DIR/logs"

python3 - <<'PY' "$ENV_FILE"
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8") if path.exists() else ""
updates = {
    "UI_ENABLE_CONTROLS": "true",
    "UI_CONTROL_USE_SUDO": "true",
}
lines = text.splitlines()
found = set()
out = []
for line in lines:
    if "=" in line and not line.lstrip().startswith("#"):
        key = line.split("=", 1)[0].strip()
        if key in updates:
            out.append(f"{key}={updates[key]}")
            found.add(key)
            continue
    out.append(line)
for key, value in updates.items():
    if key not in found:
        out.append(f"{key}={value}")
path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
print(f"updated {path}")
PY

cat > "$SERVICE_FILE" <<SERVICE
[Unit]
Description=Trading Bot Private UI
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/scripts/run_ui.py
Restart=always
RestartSec=15
StandardOutput=append:$APP_DIR/logs/ui_stdout.log
StandardError=append:$APP_DIR/logs/ui_stderr.log

[Install]
WantedBy=multi-user.target
SERVICE

cat > "$SUDOERS_FILE" <<SUDOERS
$APP_USER ALL=(root) NOPASSWD: /bin/systemctl start $BOT_SERVICE_NAME
$APP_USER ALL=(root) NOPASSWD: /bin/systemctl stop $BOT_SERVICE_NAME
$APP_USER ALL=(root) NOPASSWD: /bin/systemctl restart $BOT_SERVICE_NAME
$APP_USER ALL=(root) NOPASSWD: /bin/systemctl status $BOT_SERVICE_NAME
SUDOERS

chmod 440 "$SUDOERS_FILE"
visudo -cf "$SUDOERS_FILE"
systemctl daemon-reload
systemctl enable "$UI_SERVICE_NAME"
systemctl restart "$UI_SERVICE_NAME"
systemctl status "$UI_SERVICE_NAME" --no-pager || true

echo
echo "Private UI service installed."
echo "Next: install/configure Tailscale with scripts/server/install_tailscale_ui_root.sh"
