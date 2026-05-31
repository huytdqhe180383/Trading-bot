"""Compatibility wrapper for the live daily report application."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import BASE_DIR
from tradingbot.reports.live_daily import (
    build_report_markdown,
    export_report as _export_report,
    load_live_decisions,
    main,
    print_report,
    summarize_frame,
)


def export_report(df, tz_name, title, report_date):
    return _export_report(df, tz_name, title, report_date, report_root=BASE_DIR / "report")


if __name__ == "__main__":
    main()
