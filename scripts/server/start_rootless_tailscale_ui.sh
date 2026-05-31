#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/home/deploy/trading-bot}"
TS_DIR="${TS_DIR:-$APP_DIR/.tailscale}"
TS_VERSION="${TS_VERSION:-1.98.4}"
TS_ARCH="${TS_ARCH:-amd64}"
TS_BASE_URL="${TS_BASE_URL:-https://pkgs.tailscale.com/stable}"
TS_TGZ="${TS_BASE_URL}/tailscale_${TS_VERSION}_${TS_ARCH}.tgz"
TS_EXTRACT_DIR="$TS_DIR/tailscale_${TS_VERSION}_${TS_ARCH}"
TS_RUN_DIR="$TS_DIR/run"
TS_STATE_FILE="$TS_DIR/state/tailscaled.state"
TS_SOCKET="$TS_RUN_DIR/tailscaled.sock"
TS_LOG="$APP_DIR/logs/tailscaled_rootless.log"
TS_PID_FILE="$TS_RUN_DIR/tailscaled.pid"
TS_HOSTNAME="${TS_HOSTNAME:-trading-bot-ui-do}"
UI_PORT="${UI_PORT:-8080}"
TS_UP_TIMEOUT="${TS_UP_TIMEOUT:-15s}"
AUTH_URL_FILE="$TS_DIR/auth_url.txt"
UP_JSON_FILE="$TS_DIR/tailscale_up.json"
STATUS_JSON_FILE="$TS_DIR/tailscale_status.json"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || command -v python || true)}"

mkdir -p "$TS_EXTRACT_DIR" "$TS_RUN_DIR" "$TS_DIR/state" "$APP_DIR/logs"
rm -f "$AUTH_URL_FILE"

if [[ -z "$PYTHON_BIN" ]]; then
  echo "python3 or python is required to manage the rootless Tailscale login flow." >&2
  exit 1
fi

if [[ ! -x "$TS_EXTRACT_DIR/tailscaled" || ! -x "$TS_EXTRACT_DIR/tailscale" ]]; then
  TMP_TGZ="$TS_DIR/tailscale_${TS_VERSION}_${TS_ARCH}.tgz"
  curl -fsSL "$TS_TGZ" -o "$TMP_TGZ"
  tar -xzf "$TMP_TGZ" -C "$TS_DIR"
fi

if [[ -f "$TS_PID_FILE" ]] && kill -0 "$(cat "$TS_PID_FILE")" >/dev/null 2>&1; then
  echo "tailscaled already running with pid $(cat "$TS_PID_FILE")"
else
  nohup "$TS_EXTRACT_DIR/tailscaled" \
    --tun=userspace-networking \
    --state="$TS_STATE_FILE" \
    --socket="$TS_SOCKET" \
    >"$TS_LOG" 2>&1 </dev/null &
  echo $! > "$TS_PID_FILE"
  sleep 3
fi

"$TS_EXTRACT_DIR/tailscale" --socket="$TS_SOCKET" status --json >"$STATUS_JSON_FILE" 2>/dev/null || true

BACKEND_STATE="$(
  "$PYTHON_BIN" - "$STATUS_JSON_FILE" <<'PY'
import json
import pathlib
import sys

text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").strip()
if not text:
    print("")
else:
    print(json.loads(text).get("BackendState", ""))
PY
)"

AUTH_URL="$(
  "$PYTHON_BIN" - "$STATUS_JSON_FILE" <<'PY'
import json
import pathlib
import sys

text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").strip()
if not text:
    print("")
else:
    print(json.loads(text).get("AuthURL", ""))
PY
)"

if [[ "$BACKEND_STATE" != "Running" ]]; then
  "$TS_EXTRACT_DIR/tailscale" \
    --socket="$TS_SOCKET" \
    up \
    --json \
    --hostname="$TS_HOSTNAME" \
    --timeout="$TS_UP_TIMEOUT" >"$UP_JSON_FILE" 2>&1 || true

  UP_AUTH_URL="$(
    "$PYTHON_BIN" - "$UP_JSON_FILE" <<'PY'
import json
import pathlib
import re
import sys

text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
auth_url = ""

try:
    payload = json.loads(text)
    auth_url = payload.get("AuthURL", "")
except json.JSONDecodeError:
    match = re.search(r"https://login\.tailscale\.com/\S+", text)
    if match:
        auth_url = match.group(0).rstrip('",')

print(auth_url)
PY
  )"

  if [[ -z "$AUTH_URL" && -n "$UP_AUTH_URL" ]]; then
    AUTH_URL="$UP_AUTH_URL"
  fi

  if [[ -n "$AUTH_URL" ]]; then
    printf '%s\n' "$AUTH_URL" > "$AUTH_URL_FILE"
    echo "Tailscale login required. Open:"
    echo "  $AUTH_URL"
    echo "Saved to: $AUTH_URL_FILE"
  else
    rm -f "$AUTH_URL_FILE"
  fi
fi

echo
echo "tailscaled socket: $TS_SOCKET"
echo "tailscaled pid: $(cat "$TS_PID_FILE")"
echo "tailscale status:"
"$TS_EXTRACT_DIR/tailscale" --socket="$TS_SOCKET" status || true

echo
if [[ -f "$AUTH_URL_FILE" ]]; then
  echo "If login is still required, open:"
  cat "$AUTH_URL_FILE"
  echo
fi
echo "After auth, run:"
echo "  $TS_EXTRACT_DIR/tailscale --socket=$TS_SOCKET serve --bg --https=443 http://127.0.0.1:${UI_PORT}"
