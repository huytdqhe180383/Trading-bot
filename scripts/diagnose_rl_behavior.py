"""Compare RL backtest behavior across saved sessions."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingbot.reports.rl_behavior import write_behavior_diagnostics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build RL behavior diagnostics from backtest session directories.")
    parser.add_argument(
        "--run",
        action="append",
        required=True,
        help="Run descriptor in label=path form. Can be passed multiple times.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def parse_runs(items: list[str]) -> dict[str, Path]:
    runs: dict[str, Path] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"--run must use label=path form, got: {item}")
        label, raw_path = item.split("=", 1)
        label = label.strip()
        if not label:
            raise ValueError(f"--run label cannot be empty: {item}")
        runs[label] = Path(raw_path).expanduser()
    return runs


def main() -> None:
    args = build_parser().parse_args()
    paths = write_behavior_diagnostics(
        runs=parse_runs(args.run),
        output_dir=args.output_dir,
    )
    for name, path in paths.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
