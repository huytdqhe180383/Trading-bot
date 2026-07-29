"""Build an analyst-safe RL evidence envelope from backtest artifacts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingbot.analyst.rl_evidence import build_evidence_from_backtest  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build fail-closed RL evidence for analyst LLM context.")
    parser.add_argument("--metrics-path", type=Path, required=True)
    parser.add_argument("--metadata-path", type=Path, default=None)
    parser.add_argument("--statistical-report-path", type=Path, default=None)
    parser.add_argument("--output-path", type=Path, required=True)
    parser.add_argument("--horizon", default="research_backtest")
    parser.add_argument("--promoted", action="store_true")
    parser.add_argument("--promotion-expires-utc", default="")
    parser.add_argument("--causal-integrity-passed", action="store_true")
    parser.add_argument("--statistical-gates-passed", action="store_true")
    parser.add_argument("--calibration-passed", action="store_true")
    parser.add_argument("--prospective-shadow-passed", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    envelope = build_evidence_from_backtest(
        metrics_path=args.metrics_path,
        metadata_path=args.metadata_path,
        statistical_report_path=args.statistical_report_path,
        output_path=args.output_path,
        promoted=args.promoted,
        promotion_expires_utc=args.promotion_expires_utc,
        causal_integrity_passed=args.causal_integrity_passed,
        statistical_gates_passed=args.statistical_gates_passed,
        calibration_passed=args.calibration_passed,
        prospective_shadow_passed=args.prospective_shadow_passed,
        horizon=args.horizon,
    )
    print(f"{envelope['status']} -> {args.output_path}")


if __name__ == "__main__":
    main()
