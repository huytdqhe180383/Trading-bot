#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/home/deploy/trading-bot}"
UI_PORT="${UI_PORT:-8080}"
TAILSCALE_HOSTNAME="${TAILSCALE_HOSTNAME:-trading-bot-ui}"
TAILSCALE_AUTHKEY="${TAILSCALE_AUTHKEY:-}"
TAILSCALE_EXTRA_ARGS="${TAILSCALE_EXTRA_ARGS:-}"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi

if ! command -v tailscale >/dev/null 2>&1; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi

systemctl enable tailscaled
systemctl restart tailscaled

if [[ -n "$TAILSCALE_AUTHKEY" ]]; then
  tailscale up --authkey="$TAILSCALE_AUTHKEY" --hostname="$TAILSCALE_HOSTNAME" $TAILSCALE_EXTRA_ARGS
else
  echo "tailscale is installed but not authenticated by this script."
  echo "Run: sudo tailscale up --hostname=$TAILSCALE_HOSTNAME"
fi

echo
echo "Configuring Tailscale Serve for the private UI..."
tailscale serve --bg --https=443 "http://127.0.0.1:${UI_PORT}"
tailscale serve status || true

echo
echo "Done. Share the machine through the Tailscale admin console or invite friends to the tailnet."
