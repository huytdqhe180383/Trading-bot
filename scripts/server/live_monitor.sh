#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-trading-bot}"
APP_DIR="${APP_DIR:-$HOME/trading-bot}"
RESULTS_DIR="${RESULTS_DIR:-$APP_DIR/results/daily}"
STDOUT_LOG="${STDOUT_LOG:-$APP_DIR/logs/live_stdout.log}"
STDERR_LOG="${STDERR_LOG:-$APP_DIR/logs/live_stderr.log}"
FOLLOW_MODE="${1:-}"

latest_session_dir() {
  if [[ ! -d "$RESULTS_DIR" ]]; then
    return 1
  fi
  find "$RESULTS_DIR" -mindepth 2 -maxdepth 2 -type d | sort | tail -n 1
}

print_section() {
  local title="$1"
  printf '\n==== %s ====\n' "$title"
}

print_snapshot() {
  clear
  printf 'Trading Bot Monitor | %s\n' "$(date -Is)"
  printf 'Service: %s\n' "$SERVICE_NAME"
  printf 'Host: %s\n' "$(hostname)"

  print_section "systemd"
  systemctl --no-pager --full status "$SERVICE_NAME" 2>/dev/null | sed -n '1,18p' || true

  print_section "resource usage"
  free -h || true
  df -h "$APP_DIR" || true

  local session_dir=""
  session_dir="$(latest_session_dir || true)"
  if [[ -n "$session_dir" && -d "$session_dir" ]]; then
    print_section "latest session"
    printf '%s\n' "$session_dir"

    if [[ -f "$session_dir/live_session_summary.json" ]]; then
      sed -n '1,120p' "$session_dir/live_session_summary.json"
    fi

    local decision_csv
    decision_csv="$(find "$session_dir" -maxdepth 1 -type f -name 'live_trade_decisions_*.csv' | sort | tail -n 1)"
    if [[ -n "${decision_csv:-}" && -f "$decision_csv" ]]; then
      print_section "recent decisions"
      tail -n 15 "$decision_csv"
    fi
  else
    print_section "latest session"
    printf 'No live session folder found under %s\n' "$RESULTS_DIR"
  fi

  if [[ -f "$STDERR_LOG" ]]; then
    print_section "stderr tail"
    tail -n 20 "$STDERR_LOG"
  fi
}

if [[ "$FOLLOW_MODE" == "--follow" ]]; then
  while true; do
    print_snapshot
    sleep 15
  done
else
  print_snapshot
  printf '\nTip: run with --follow for auto-refresh every 15 seconds.\n'
fi
