"""Shared artifact/session helpers for live, backtest, and reports."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd


def _json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    return str(value)


def create_numbered_daily_dir(
    root_dir: Path,
    run_date: str | None = None,
    *,
    tz_name: str | None = None,
) -> Path:
    """Create root/daily/YYYY-MM-DD/N without overwriting prior sessions."""
    if run_date:
        day = run_date
    elif tz_name:
        day = datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d")
    else:
        day = datetime.now().strftime("%Y-%m-%d")

    daily_dir = Path(root_dir) / "daily" / day
    daily_dir.mkdir(parents=True, exist_ok=True)
    existing_numbers = [
        int(child.name)
        for child in daily_dir.iterdir()
        if child.is_dir() and child.name.isdigit()
    ]
    session_dir = daily_dir / str(max(existing_numbers, default=0) + 1)
    session_dir.mkdir(parents=True, exist_ok=False)
    return session_dir


def write_json_artifact(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, default=_json_default, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def append_csv_row(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([row]).to_csv(
        path,
        mode="a",
        header=not path.exists(),
        index=False,
    )


def write_live_session_summary(session_dir: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    df = pd.DataFrame(rows)
    summary = {
        "rows": int(len(df)),
        "ok_rows": int((df.get("status", pd.Series(dtype=str)) == "ok").sum()) if "status" in df else 0,
        "blocked_rows": int((df.get("status", pd.Series(dtype=str)) == "blocked").sum()) if "status" in df else 0,
        "orders_submitted": int(df.get("orders_submitted", pd.Series(dtype=float)).fillna(0).sum()) if "orders_submitted" in df else 0,
        "orders_filled": int(df.get("orders_filled", pd.Series(dtype=float)).fillna(0).sum()) if "orders_filled" in df else 0,
        "max_nav": float(df.get("nav", pd.Series(dtype=float)).max()) if "nav" in df else 0.0,
        "min_nav": float(df.get("nav", pd.Series(dtype=float)).min()) if "nav" in df else 0.0,
        "last_nav": float(df.get("nav", pd.Series(dtype=float)).iloc[-1]) if "nav" in df and len(df) else 0.0,
        "last_status": str(df.get("status", pd.Series(dtype=str)).iloc[-1]) if "status" in df and len(df) else "",
    }
    write_json_artifact(Path(session_dir) / "live_session_summary.json", summary)


def iter_live_decision_csvs(results_dir: Path) -> Iterable[Path]:
    daily_root = Path(results_dir) / "daily"
    if not daily_root.exists():
        return []
    return sorted(daily_root.glob("*/*/live_trade_decisions_*.csv"))


def load_live_decisions(results_dir: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for csv_path in iter_live_decision_csvs(results_dir):
        try:
            df = pd.read_csv(csv_path)
        except Exception:
            continue
        if df.empty or "timestamp_utc" not in df.columns:
            continue
        df["source_csv"] = str(csv_path)
        df["session_dir"] = str(csv_path.parent)
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out["timestamp_utc"] = pd.to_datetime(out["timestamp_utc"], utc=True, errors="coerce")
    return out.dropna(subset=["timestamp_utc"]).sort_values("timestamp_utc").reset_index(drop=True)

