#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/home/deploy/trading-bot}"
TS_DIR="${TS_DIR:-$APP_DIR/.tailscale}"
TS_VERSION="${TS_VERSION:-1.98.4}"
TS_ARCH="${TS_ARCH:-amd64}"
TS_EXTRACT_DIR="$TS_DIR/tailscale_${TS_VERSION}_${TS_ARCH}"
TS_SOCKET="${TS_DIR}/run/tailscaled.sock"
UI_PORT="${UI_PORT:-8080}"
AUTH_URL_FILE="${TS_DIR}/auth_url.txt"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || command -v python || true)}"

if [[ ! -x "$TS_EXTRACT_DIR/tailscale" ]]; then
  echo "tailscale client not found. Run start_rootless_tailscale_ui.sh first." >&2
  exit 1
fi

if [[ -z "$PYTHON_BIN" ]]; then
  echo "python3 or python is required to inspect Tailscale state." >&2
  exit 1
fi

BACKEND_STATE="$(
  "$TS_EXTRACT_DIR/tailscale" --socket="$TS_SOCKET" status --json 2>/dev/null | "$PYTHON_BIN" -c "import json, sys; text=sys.stdin.read().strip(); print(json.loads(text).get('BackendState', '') if text else '')" 2>/dev/null || true
)"

if [[ "$BACKEND_STATE" != "Running" ]]; then
  echo "tailscale is not authenticated yet." >&2
  if [[ -f "$AUTH_URL_FILE" ]]; then
    echo "Open this URL first:" >&2
    cat "$AUTH_URL_FILE" >&2
  else
    echo "Run start_rootless_tailscale_ui.sh first to generate a login URL." >&2
  fi
  exit 1
fi

"$TS_EXTRACT_DIR/tailscale" --socket="$TS_SOCKET" serve --bg --https=443 "http://127.0.0.1:${UI_PORT}"
"$TS_EXTRACT_DIR/tailscale" --socket="$TS_SOCKET" serve status
