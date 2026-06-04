"""
Service layer for the private trading-bot UI.
"""

from __future__ import annotations

import json
import re
import secrets
import subprocess
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import pandas as pd

from config import (
    LIVE_SESSION_TIMEZONE,
    LOGS_DIR,
    REBALANCE_INTERVAL_SECS,
    REPORTS_DIR,
    RESULTS_DIR,
    UI_AUDIT_LOG_PATH,
    UI_CONTROL_USE_SUDO,
    UI_TARGET_SERVICE,
)
from tradingbot.reports.live_daily import load_live_decisions, summarize_frame

ALLOWED_CONTROL_ACTIONS = {"start", "stop", "restart", "status"}
ALLOWED_LOG_SOURCES = {
    "stderr": LOGS_DIR / "live_stderr.log",
    "stdout": LOGS_DIR / "live_stdout.log",
}
STRATEGY_NAV_NOTE = "Strategy NAV excludes non-strategy assets such as OKB."
LIVE_ROW_STALE_AFTER_SECS = max(REBALANCE_INTERVAL_SECS * 2, REBALANCE_INTERVAL_SECS + 900)


class InMemoryRateLimiter:
    def __init__(self, *, window_seconds: int = 60, time_func: Callable[[], float] | None = None) -> None:
        self.window_seconds = max(1, int(window_seconds))
        self._time_func = time_func or time.time
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int) -> bool:
        now = float(self._time_func())
        window_start = now - self.window_seconds
        bucket = self._events[key]
        while bucket and bucket[0] < window_start:
            bucket.popleft()
        if len(bucket) >= max(1, int(limit)):
            return False
        bucket.append(now)
        return True


def mint_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def append_ui_audit_log(
    event: str,
    *,
    outcome: str,
    details: dict[str, Any] | None = None,
    audit_log_path: Path = UI_AUDIT_LOG_PATH,
) -> None:
    payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "outcome": outcome,
        "details": details or {},
    }
    audit_log_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=True) + "\n")


def build_control_command(
    action: str,
    service_name: str = UI_TARGET_SERVICE,
    *,
    use_sudo: bool = UI_CONTROL_USE_SUDO,
) -> list[str]:
    normalized = str(action).strip().lower()
    if normalized not in ALLOWED_CONTROL_ACTIONS:
        raise ValueError(f"Unsupported control action: {action}")
    base = ["systemctl", normalized, service_name]
    if use_sudo:
        return ["sudo", "-n", *base]
    return base


def run_control_command(
    action: str,
    *,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
    service_name: str = UI_TARGET_SERVICE,
    use_sudo: bool = UI_CONTROL_USE_SUDO,
) -> dict[str, Any]:
    cmd = build_control_command(action, service_name=service_name, use_sudo=use_sudo)
    exec_runner = runner or (
        lambda command: subprocess.run(command, capture_output=True, text=True, check=False, shell=False)
    )
    result = exec_runner(cmd)
    return {
        "action": action,
        "command": cmd,
        "returncode": int(getattr(result, "returncode", 1)),
        "stdout": str(getattr(result, "stdout", "")),
        "stderr": str(getattr(result, "stderr", "")),
    }


def get_bot_service_status(
    *,
    service_name: str = UI_TARGET_SERVICE,
    status_runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    runner = status_runner or (
        lambda command: subprocess.run(command, capture_output=True, text=True, check=False, shell=False)
    )
    result = runner(
        [
            "systemctl",
            "show",
            service_name,
            "--property=ActiveState,SubState,MainPID,ExecMainStartTimestamp",
        ]
    )
    payload = {
        "service_name": service_name,
        "available": result.returncode == 0,
        "active_state": "unknown",
        "sub_state": "unknown",
        "main_pid": 0,
        "started_at": "",
        "uptime_seconds": None,
        "raw_stdout": result.stdout,
        "raw_stderr": result.stderr,
    }
    if result.returncode != 0:
        return payload

    parsed: dict[str, str] = {}
    for line in str(result.stdout).splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip()

    payload["active_state"] = parsed.get("ActiveState", "unknown")
    payload["sub_state"] = parsed.get("SubState", "unknown")
    payload["main_pid"] = int(parsed.get("MainPID", "0") or 0)
    payload["started_at"] = parsed.get("ExecMainStartTimestamp", "")

    started_at_raw = payload["started_at"]
    try:
        if started_at_raw:
            started_dt = pd.to_datetime(started_at_raw, utc=False)
            if getattr(started_dt, "tzinfo", None) is None:
                started_dt = started_dt.tz_localize(datetime.now().astimezone().tzinfo)
            uptime = datetime.now(started_dt.tzinfo) - started_dt.to_pydatetime()
            payload["uptime_seconds"] = max(0, int(uptime.total_seconds()))
    except Exception:
        payload["uptime_seconds"] = None
    return payload


def _tail_lines(path: Path, lines: int) -> str:
    if not path.exists():
        raise FileNotFoundError(str(path))
    requested = max(1, min(int(lines), 2000))
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        content = fh.readlines()
    return "".join(content[-requested:])


def read_log_source(
    source: str,
    *,
    lines: int,
    logs_dir: Path = LOGS_DIR,
    journal_runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
    service_name: str = UI_TARGET_SERVICE,
) -> dict[str, Any]:
    normalized = str(source).strip().lower()
    requested = max(1, min(int(lines), 2000))
    if normalized in ALLOWED_LOG_SOURCES:
        filename = ALLOWED_LOG_SOURCES[normalized].name
        path = Path(logs_dir) / filename
        try:
            content = _tail_lines(path, requested)
            return {"source": normalized, "content": content, "available": True, "error": ""}
        except Exception as exc:
            return {"source": normalized, "content": "", "available": False, "error": str(exc)}
    if normalized == "service":
        runner = journal_runner or (
            lambda command: subprocess.run(command, capture_output=True, text=True, check=False, shell=False)
        )
        result = runner(
            ["journalctl", "-u", service_name, "-n", str(requested), "--no-pager"]
        )
        return {
            "source": normalized,
            "content": str(result.stdout),
            "available": result.returncode == 0,
            "error": str(result.stderr),
        }
    raise ValueError(f"Unsupported log source: {source}")


def _jsonable_record(record: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in record.items():
        if isinstance(value, pd.Timestamp):
            out[key] = value.isoformat()
        elif pd.isna(value):
            out[key] = None
        else:
            out[key] = value
    return out


def _coerce_utc_timestamp(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(ts):
        return None
    return pd.Timestamp(ts)


def _format_age_text(age_seconds: int | None) -> str:
    if age_seconds is None:
        return "n/a"
    if age_seconds < 60:
        return f"{age_seconds}s"
    minutes, seconds = divmod(age_seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def build_live_freshness_payload(
    latest_row: dict[str, Any] | None,
    *,
    tz_name: str,
    now_utc: pd.Timestamp | None = None,
    stale_after_seconds: int = LIVE_ROW_STALE_AFTER_SECS,
) -> dict[str, Any]:
    now_ts = _coerce_utc_timestamp(now_utc) or pd.Timestamp.now(tz="UTC")
    latest_ts = _coerce_utc_timestamp((latest_row or {}).get("timestamp_utc"))
    if latest_ts is None:
        return {
            "status": "unavailable",
            "is_stale": True,
            "age_seconds": None,
            "age_text": "n/a",
            "stale_after_seconds": int(stale_after_seconds),
            "latest_timestamp_utc": None,
            "latest_timestamp_local": None,
            "today_has_rows": False,
        }
    age_seconds = max(0, int((now_ts - latest_ts).total_seconds()))
    latest_local = latest_ts.tz_convert(ZoneInfo(tz_name))
    today_local = now_ts.tz_convert(ZoneInfo(tz_name)).strftime("%Y-%m-%d")
    latest_local_day = latest_local.strftime("%Y-%m-%d")
    is_stale = age_seconds > int(stale_after_seconds)
    return {
        "status": "stale" if is_stale else "fresh",
        "is_stale": is_stale,
        "age_seconds": age_seconds,
        "age_text": _format_age_text(age_seconds),
        "stale_after_seconds": int(stale_after_seconds),
        "latest_timestamp_utc": latest_ts.isoformat(),
        "latest_timestamp_local": latest_local.isoformat(),
        "today_has_rows": latest_local_day == today_local,
    }


def _get_filtered_frame(
    df: pd.DataFrame,
    *,
    tz_name: str,
    mode: str,
    report_date: str | None = None,
    last_hours: float | None = None,
) -> tuple[pd.DataFrame, str, str]:
    tz = ZoneInfo(tz_name)
    local_df = df.copy()
    local_df["timestamp_local"] = local_df["timestamp_utc"].dt.tz_convert(tz)

    normalized_mode = str(mode).strip().lower()
    if normalized_mode == "full_history":
        return local_df, f"Live report: full history ({tz_name})", local_df["timestamp_local"].iloc[-1].strftime("%Y-%m-%d")
    if normalized_mode == "last_hours":
        hours = float(last_hours or 24.0)
        end_ts = local_df["timestamp_utc"].max()
        start_ts = end_ts - pd.Timedelta(hours=hours)
        out = local_df[local_df["timestamp_utc"] >= start_ts].copy()
        export_day = end_ts.tz_convert(tz).strftime("%Y-%m-%d")
        return out, f"Live report: last {hours:g} hours", export_day

    target_date = report_date or pd.Timestamp.now(tz=tz).strftime("%Y-%m-%d")
    out = local_df[local_df["timestamp_local"].dt.strftime("%Y-%m-%d") == target_date].copy()
    return out, f"Live report: {target_date} ({tz_name})", target_date


def list_compact_report_files(report_date: str, *, reports_dir: Path = REPORTS_DIR) -> list[str]:
    day_dir = Path(reports_dir) / "daily" / report_date
    if not day_dir.exists():
        return []
    return sorted(
        child.name
        for child in day_dir.iterdir()
        if child.is_file() and child.suffix.lower() in {".json", ".md"}
    )


def safe_compact_report_path(report_date: str, filename: str, *, reports_dir: Path = REPORTS_DIR) -> Path:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", report_date):
        raise ValueError("Invalid report date.")
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise ValueError("Invalid report filename.")
    resolved = (Path(reports_dir) / "daily" / report_date / filename).resolve()
    allowed_root = (Path(reports_dir) / "daily" / report_date).resolve()
    if allowed_root not in resolved.parents:
        raise ValueError("Report path escapes allowed directory.")
    if not resolved.exists():
        raise FileNotFoundError(str(resolved))
    return resolved


def build_report_payload(
    *,
    mode: str,
    tz_name: str = LIVE_SESSION_TIMEZONE,
    report_date: str | None = None,
    last_hours: float | None = None,
    results_dir: Path = RESULTS_DIR,
    reports_dir: Path = REPORTS_DIR,
    limit_rows: int = 50,
) -> dict[str, Any]:
    df = load_live_decisions(Path(results_dir))
    if df.empty:
        return {
            "title": "Live report unavailable",
            "summary": {"rows": 0, "orders_submitted": 0, "orders_filled": 0, "statuses": {}},
            "recent_rows": [],
            "export_files": [],
            "note": STRATEGY_NAV_NOTE,
        }
    filtered, title, export_day = _get_filtered_frame(
        df,
        tz_name=tz_name,
        mode=mode,
        report_date=report_date,
        last_hours=last_hours,
    )
    summary = summarize_frame(filtered, tz_name)
    recent_rows = [_jsonable_record(row) for row in filtered.tail(limit_rows).to_dict(orient="records")]
    return {
        "title": title,
        "summary": summary,
        "recent_rows": recent_rows,
        "export_files": list_compact_report_files(export_day, reports_dir=reports_dir),
        "export_day": export_day,
        "note": STRATEGY_NAV_NOTE,
    }


def build_history_payload(
    *,
    tz_name: str = LIVE_SESSION_TIMEZONE,
    results_dir: Path = RESULTS_DIR,
    limit_rows: int = 50,
    limit_sessions: int = 20,
    now_utc: pd.Timestamp | None = None,
) -> dict[str, Any]:
    df = load_live_decisions(Path(results_dir))
    if df.empty:
        return {
            "sessions": [],
            "rows": [],
            "note": STRATEGY_NAV_NOTE,
            "freshness": build_live_freshness_payload(None, tz_name=tz_name, now_utc=now_utc),
        }
    df = df.copy()
    df["timestamp_local"] = df["timestamp_utc"].dt.tz_convert(ZoneInfo(tz_name))
    rows = df.tail(limit_rows).copy()
    rows["ui_action"] = rows.get("orders_submitted", pd.Series([0] * len(rows))).fillna(0).astype(int).apply(
        lambda value: "trade" if value > 0 else "no_order"
    )
    btc_weight = rows.get("btc_weight", pd.Series([0.0] * len(rows))).fillna(0.0).astype(float)
    eth_weight = rows.get("eth_weight", pd.Series([0.0] * len(rows))).fillna(0.0).astype(float)
    rows["position_state"] = (btc_weight + eth_weight).apply(lambda value: "risk_on" if value > 0.01 else "cash")
    session_summary = (
        df.groupby("session_dir", dropna=True)
        .agg(
            first_timestamp_utc=("timestamp_utc", "min"),
            last_timestamp_utc=("timestamp_utc", "max"),
            first_nav=("nav", "first"),
            last_nav=("nav", "last"),
            rows=("timestamp_utc", "count"),
            orders_submitted=("orders_submitted", "sum"),
            orders_filled=("orders_filled", "sum"),
        )
        .reset_index()
        .tail(limit_sessions)
    )
    sessions = [_jsonable_record(row) for row in session_summary.to_dict(orient="records")]
    return {
        "sessions": sessions,
        "rows": [_jsonable_record(row) for row in rows.to_dict(orient="records")],
        "note": STRATEGY_NAV_NOTE,
        "freshness": build_live_freshness_payload(
            _jsonable_record(rows.iloc[-1].to_dict()) if not rows.empty else None,
            tz_name=tz_name,
            now_utc=now_utc,
        ),
    }


def build_dashboard_payload(
    *,
    tz_name: str = LIVE_SESSION_TIMEZONE,
    results_dir: Path = RESULTS_DIR,
    reports_dir: Path = REPORTS_DIR,
    service_name: str = UI_TARGET_SERVICE,
    status_runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
    now_utc: pd.Timestamp | None = None,
) -> dict[str, Any]:
    now_ts = _coerce_utc_timestamp(now_utc) or pd.Timestamp.now(tz="UTC")
    report_date = now_ts.tz_convert(ZoneInfo(tz_name)).strftime("%Y-%m-%d")
    status = get_bot_service_status(service_name=service_name, status_runner=status_runner)
    today = build_report_payload(
        mode="date",
        tz_name=tz_name,
        report_date=report_date,
        results_dir=results_dir,
        reports_dir=reports_dir,
    )
    full_history = build_report_payload(mode="full_history", tz_name=tz_name, results_dir=results_dir, reports_dir=reports_dir)
    latest_row = today["recent_rows"][-1] if today["recent_rows"] else (full_history["recent_rows"][-1] if full_history["recent_rows"] else None)
    freshness = build_live_freshness_payload(latest_row, tz_name=tz_name, now_utc=now_ts)
    if today["summary"].get("rows", 0) > 0:
        freshness["today_has_rows"] = True
    status["ui_state"] = "stale" if status["active_state"] == "active" and freshness["is_stale"] else status["active_state"]
    return {
        "status": status,
        "today": today,
        "full_history": full_history,
        "latest_row": latest_row,
        "freshness": freshness,
        "note": STRATEGY_NAV_NOTE,
    }
