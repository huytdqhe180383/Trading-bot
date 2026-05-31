"""Summarize live trading decisions by local day or rolling window."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from config import BASE_DIR, LIVE_SESSION_TIMEZONE, RESULTS_DIR
from tradingbot.runtime.artifacts import load_live_decisions


def summarize_frame(df: pd.DataFrame, tz_name: str) -> dict[str, object]:
    if df.empty:
        return {
            "rows": 0,
            "orders_submitted": 0,
            "orders_filled": 0,
            "statuses": {},
        }
    out: dict[str, object] = {
        "rows": int(len(df)),
        "orders_submitted": int(df.get("orders_submitted", pd.Series(dtype=float)).fillna(0).sum()),
        "orders_filled": int(df.get("orders_filled", pd.Series(dtype=float)).fillna(0).sum()),
        "statuses": df.get("status", pd.Series(dtype=str)).value_counts().to_dict() if "status" in df else {},
        "first_timestamp_utc": df["timestamp_utc"].iloc[0].isoformat(),
        "last_timestamp_utc": df["timestamp_utc"].iloc[-1].isoformat(),
        "timezone": tz_name,
    }
    if "timestamp_local" in df.columns:
        out["first_timestamp_local"] = str(df["timestamp_local"].iloc[0])
        out["last_timestamp_local"] = str(df["timestamp_local"].iloc[-1])
    if "nav" in df.columns:
        start_nav = float(df["nav"].iloc[0])
        end_nav = float(df["nav"].iloc[-1])
        out["start_nav"] = start_nav
        out["end_nav"] = end_nav
        out["min_nav"] = float(df["nav"].min())
        out["max_nav"] = float(df["nav"].max())
        out["unrealized_pnl_usd"] = end_nav - start_nav
        out["unrealized_pnl_pct"] = ((end_nav / start_nav) - 1.0) * 100.0 if start_nav else 0.0
        out["pnl_usd"] = out["unrealized_pnl_usd"]
        out["pnl_pct"] = out["unrealized_pnl_pct"]
    if "btc_weight" in df.columns:
        out["avg_btc_weight"] = float(df["btc_weight"].mean())
    if "eth_weight" in df.columns:
        out["avg_eth_weight"] = float(df["eth_weight"].mean())
    if "cash_weight" in df.columns:
        out["avg_cash_weight"] = float(df["cash_weight"].mean())
    out["session_dirs"] = sorted(df["session_dir"].dropna().unique().tolist()) if "session_dir" in df.columns else []
    return out


def _report_columns(df: pd.DataFrame) -> list[str]:
    return [
        c
        for c in [
            "timestamp_utc",
            "timestamp_local",
            "cycle",
            "nav",
            "unrealized_pnl_usd",
            "unrealized_pnl_pct",
            "pnl_usd",
            "pnl_pct",
            "btc_weight",
            "eth_weight",
            "cash_weight",
            "orders_submitted",
            "orders_filled",
            "status",
            "safety_gate_reasons",
        ]
        if c in df.columns
    ]


def print_report(df: pd.DataFrame, tz_name: str, title: str) -> None:
    print(f"== {title} ==")
    summary = summarize_frame(df, tz_name)
    print(json.dumps(summary, indent=2))
    if df.empty:
        return
    print("\nRecent rows:")
    print(df[_report_columns(df)].tail(20).to_csv(index=False))


def build_report_markdown(df: pd.DataFrame, tz_name: str, title: str) -> str:
    summary = summarize_frame(df, tz_name)
    lines = [f"# {title}", "", "## Summary", "", "```json", json.dumps(summary, indent=2), "```"]
    if not df.empty:
        lines.extend(
            [
                "",
                "## Recent Rows",
                "",
                "```csv",
                df[_report_columns(df)].tail(20).to_csv(index=False).strip(),
                "```",
            ]
        )
    return "\n".join(lines) + "\n"


def export_report(
    df: pd.DataFrame,
    tz_name: str,
    title: str,
    report_date: str,
    *,
    report_root: Path | None = None,
) -> tuple[Path, Path]:
    root = Path(report_root) if report_root is not None else BASE_DIR / "report"
    daily_dir = root / "daily" / report_date
    daily_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9._-]+", "_", title.lower()).strip("_")
    json_path = daily_dir / f"{slug}.json"
    md_path = daily_dir / f"{slug}.md"
    json_path.write_text(json.dumps(summarize_frame(df, tz_name), indent=2), encoding="utf-8")
    md_path.write_text(build_report_markdown(df, tz_name, title), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Summarize live paper-trading decisions by local day or rolling window.")
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--tz", default=LIVE_SESSION_TIMEZONE)
    parser.add_argument("--date", default=None, help="Local YYYY-MM-DD day to report. Defaults to today in --tz.")
    parser.add_argument("--last-hours", type=float, default=None, help="Rolling window in hours, e.g. 24.")
    parser.add_argument("--full-history", action="store_true", help="Summarize the entire live decision history available under results/daily.")
    parser.add_argument("--export", action="store_true", help="Also export compact JSON/Markdown under report/daily/<date>/")
    args = parser.parse_args(argv)

    tz = ZoneInfo(args.tz)
    df = load_live_decisions(args.results_dir)
    if df.empty:
        print("No live decision CSVs found.")
        return
    df["timestamp_local"] = df["timestamp_utc"].dt.tz_convert(tz)

    if args.full_history:
        title = f"Live report: full history ({args.tz})"
        print_report(df, args.tz, title)
        if args.export:
            export_date = df["timestamp_local"].iloc[-1].strftime("%Y-%m-%d")
            json_path, md_path = export_report(df, args.tz, title, export_date)
            print(f"Exported: {json_path}")
            print(f"Exported: {md_path}")
        return

    if args.last_hours is not None:
        end_ts = df["timestamp_utc"].max()
        start_ts = end_ts - pd.Timedelta(hours=float(args.last_hours))
        report_df = df[df["timestamp_utc"] >= start_ts].copy()
        title = f"Live report: last {args.last_hours:g} hours"
        print_report(report_df, args.tz, title)
        if args.export:
            export_date = end_ts.tz_convert(tz).strftime("%Y-%m-%d")
            json_path, md_path = export_report(report_df, args.tz, title, export_date)
            print(f"Exported: {json_path}")
            print(f"Exported: {md_path}")
        return

    report_date = args.date or pd.Timestamp.now(tz=tz).strftime("%Y-%m-%d")
    report_df = df[df["timestamp_local"].dt.strftime("%Y-%m-%d") == report_date].copy()
    title = f"Live report: {report_date} ({args.tz})"
    print_report(report_df, args.tz, title)
    if args.export:
        json_path, md_path = export_report(report_df, args.tz, title, report_date)
        print(f"Exported: {json_path}")
        print(f"Exported: {md_path}")

