"""Run cost-stress backtests for existing RL model directories.

This runner does not train.  It replays already-trained model folders through
the normal backtest path while overriding the selected realism profile's fee,
slippage, and latency assumptions.  The output is a cheap robustness screen:
if a candidate only wins at one cost assumption, it is not ready to become an
agent-trustworthy RL source.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DAILY = ROOT / "results" / "daily"
DEFAULT_PIPELINE = "rl_only"
DEFAULT_REALISM_PROFILE = "live_like"
DEFAULT_METHOD = "dynamic_weighted"
DEFAULT_PROFILES = (
    "live_like_1x:0.0012:0.0018:1",
    "live_like_2x:0.0024:0.0036:1",
    "live_like_3x:0.0036:0.0054:1",
)
ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


@dataclass(frozen=True)
class ModelSpec:
    label: str
    models_dir: Path


@dataclass(frozen=True)
class CostProfile:
    label: str
    fee: float
    slippage: float
    latency_steps: int


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run RL model cost-stress backtests.")
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        help="Model spec as label=path. Repeat for multiple model directories.",
    )
    parser.add_argument(
        "--profiles",
        default=",".join(DEFAULT_PROFILES),
        help="Comma-separated cost profiles as label:fee:slippage:latency_steps.",
    )
    parser.add_argument("--pipeline", default=DEFAULT_PIPELINE, choices=["rl_only", "rl_kronos", "rl_tradingagents", "rl_full"])
    parser.add_argument("--realism-profile", default=DEFAULT_REALISM_PROFILE, choices=["baseline", "live_like"])
    parser.add_argument(
        "--method",
        default=DEFAULT_METHOD,
        choices=["mean", "voting", "weighted", "dynamic_weighted", "regime_weighted", "imca"],
    )
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--run-label", default="rl_cost_stress")
    parser.add_argument(
        "--step-turnover-cap-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Forward per-step turnover cap enable/disable to backtest.py.",
    )
    parser.add_argument("--step-turnover-cap-normal", type=float, default=None)
    parser.add_argument("--step-turnover-cap-stress", type=float, default=None)
    parser.add_argument("--step-turnover-cap-crisis", type=float, default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def parse_model_specs(values: list[str]) -> list[ModelSpec]:
    specs: list[ModelSpec] = []
    for raw in values:
        if "=" not in raw:
            raise ValueError(f"Invalid model spec {raw!r}; expected label=path.")
        label, path = raw.split("=", 1)
        label = label.strip()
        if not label:
            raise ValueError(f"Invalid model spec {raw!r}; label is empty.")
        models_dir = Path(path.strip())
        if not str(models_dir):
            raise ValueError(f"Invalid model spec {raw!r}; path is empty.")
        specs.append(ModelSpec(label=label, models_dir=models_dir))
    if not specs:
        raise ValueError("At least one --model label=path is required.")
    return specs


def parse_cost_profiles(raw: str) -> list[CostProfile]:
    profiles: list[CostProfile] = []
    for part in str(raw).split(","):
        text = part.strip()
        if not text:
            continue
        pieces = [piece.strip() for piece in text.split(":")]
        if len(pieces) != 4:
            raise ValueError(f"Invalid cost profile {text!r}; expected label:fee:slippage:latency_steps.")
        label, fee_raw, slippage_raw, latency_raw = pieces
        if not label:
            raise ValueError(f"Invalid cost profile {text!r}; label is empty.")
        fee = float(fee_raw)
        slippage = float(slippage_raw)
        latency_steps = int(latency_raw)
        if fee < 0 or slippage < 0 or latency_steps < 0:
            raise ValueError(f"Invalid cost profile {text!r}; fee, slippage, and latency must be non-negative.")
        profiles.append(CostProfile(label=label, fee=fee, slippage=slippage, latency_steps=latency_steps))
    if not profiles:
        raise ValueError("At least one cost profile is required.")
    return profiles


def create_cost_stress_dir(
    *,
    results_daily: Path = RESULTS_DAILY,
    run_label: str = "rl_cost_stress",
    run_date: str | None = None,
) -> Path:
    day = run_date or datetime.now().strftime("%Y-%m-%d")
    base = Path(results_daily) / day / run_label
    base.mkdir(parents=True, exist_ok=True)
    existing = [int(child.name) for child in base.iterdir() if child.is_dir() and child.name.isdigit()]
    out = base / str(max(existing, default=0) + 1)
    out.mkdir(parents=False, exist_ok=False)
    return out


def build_backtest_command(
    *,
    models_dir: Path,
    profile: CostProfile,
    pipeline: str = DEFAULT_PIPELINE,
    realism_profile: str = DEFAULT_REALISM_PROFILE,
    method: str = DEFAULT_METHOD,
    step_turnover_cap_enabled: bool | None = None,
    step_turnover_cap_normal: float | None = None,
    step_turnover_cap_stress: float | None = None,
    step_turnover_cap_crisis: float | None = None,
) -> list[str]:
    command = [
        sys.executable,
        "backtest.py",
        "--pipeline",
        pipeline,
        "--realism-profile",
        realism_profile,
        "--method",
        method,
        "--model-dir",
        str(models_dir),
        "--fee-override",
        str(profile.fee),
        "--slippage-override",
        str(profile.slippage),
        "--latency-steps-override",
        str(profile.latency_steps),
        "--autosave-profit-threshold",
        "999999",
    ]
    if step_turnover_cap_enabled is True:
        command.append("--step-turnover-cap-enabled")
    elif step_turnover_cap_enabled is False:
        command.append("--no-step-turnover-cap-enabled")
    for flag, value in [
        ("--step-turnover-cap-normal", step_turnover_cap_normal),
        ("--step-turnover-cap-stress", step_turnover_cap_stress),
        ("--step-turnover-cap-crisis", step_turnover_cap_crisis),
    ]:
        if value is not None:
            if value < 0:
                raise ValueError(f"{flag} must be non-negative")
            command.extend([flag, str(value)])
    return command


def build_evidence_command(*, metrics_path: Path, metadata_path: Path, statistical_report_path: Path, output_path: Path) -> list[str]:
    return [
        sys.executable,
        "scripts/build_rl_evidence.py",
        "--metrics-path",
        str(metrics_path),
        "--metadata-path",
        str(metadata_path),
        "--statistical-report-path",
        str(statistical_report_path),
        "--output-path",
        str(output_path),
    ]


def run_command(command: list[str], *, stdout_path: Path, stderr_path: Path, dry_run: bool = False) -> None:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    if dry_run:
        stdout_path.write_text("DRY RUN: " + json.dumps(command) + "\n", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        subprocess.run(command, cwd=ROOT, stdout=stdout, stderr=stderr, check=True)


def parse_backtest_session_dir(*, stdout_path: Path, stderr_path: Path) -> Path:
    text = ""
    for path in (stdout_path, stderr_path):
        if path.exists():
            text += "\n" + path.read_text(encoding="utf-8", errors="replace")
    text = ANSI_ESCAPE_RE.sub("", text)
    match = re.search(r"Backtest session output directory -> (?P<path>.+)", text)
    if not match:
        raise RuntimeError(f"Could not parse backtest session directory from {stdout_path} / {stderr_path}")
    return Path(match.group("path").strip())


def read_metrics(metrics_path: Path) -> dict[str, float | str | None]:
    if not Path(metrics_path).exists():
        return {}
    raw = pd.read_csv(metrics_path, index_col=0)["value"].to_dict()
    return {str(key): _parse_scalar(value) for key, value in raw.items()}


def build_summary_row(
    *,
    model: ModelSpec,
    profile: CostProfile,
    scenario_dir: Path,
    backtest_session_dir: Path,
    evidence_path: Path,
    metrics: dict[str, Any],
) -> dict[str, Any]:
    return {
        "model_label": model.label,
        "models_dir": str(model.models_dir),
        "cost_profile": profile.label,
        "fee": profile.fee,
        "slippage": profile.slippage,
        "latency_steps": profile.latency_steps,
        "scenario_dir": str(scenario_dir),
        "backtest_session_dir": str(backtest_session_dir),
        "evidence_path": str(evidence_path),
        "code_commit": _current_git_commit(),
        "total_return_pct": metrics.get("total_return_pct"),
        "annualised_return_pct": metrics.get("annualised_return_pct"),
        "sharpe_ratio": metrics.get("sharpe_ratio"),
        "sortino_ratio": metrics.get("sortino_ratio"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "profit_factor": metrics.get("profit_factor"),
        "total_trades_count": metrics.get("total_trades_count"),
        "trade_count": metrics.get("trade_count"),
        "trade_win_rate_pct": metrics.get("trade_win_rate_pct"),
        "trade_profit_factor": metrics.get("trade_profit_factor"),
        "trade_expectancy_pct": metrics.get("trade_expectancy_pct"),
    }


def write_cost_stress_summary(output_dir: Path, rows: list[dict[str, Any]]) -> Path:
    out = Path(output_dir) / "cost_stress_summary.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    return out


def run_cost_stress(args: argparse.Namespace) -> Path:
    models = parse_model_specs(args.model)
    profiles = parse_cost_profiles(args.profiles)
    output_dir = Path(args.output_dir) if args.output_dir else create_cost_stress_dir(run_label=args.run_label)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_rows: list[dict[str, Any]] = []

    for model in models:
        for profile in profiles:
            scenario_dir = output_dir / model.label / profile.label
            scenario_dir.mkdir(parents=True, exist_ok=True)
            backtest_stdout = scenario_dir / "backtest_stdout.log"
            backtest_stderr = scenario_dir / "backtest_stderr.log"
            run_command(
                build_backtest_command(
                    models_dir=model.models_dir,
                    profile=profile,
                    pipeline=args.pipeline,
                    realism_profile=args.realism_profile,
                    method=args.method,
                    step_turnover_cap_enabled=args.step_turnover_cap_enabled,
                    step_turnover_cap_normal=args.step_turnover_cap_normal,
                    step_turnover_cap_stress=args.step_turnover_cap_stress,
                    step_turnover_cap_crisis=args.step_turnover_cap_crisis,
                ),
                stdout_path=backtest_stdout,
                stderr_path=backtest_stderr,
                dry_run=args.dry_run,
            )

            if args.dry_run:
                backtest_session_dir = scenario_dir / "dry_run_backtest_session"
                evidence_path = scenario_dir / "rl_evidence.json"
                metrics: dict[str, Any] = {}
            else:
                backtest_session_dir = parse_backtest_session_dir(
                    stdout_path=backtest_stdout,
                    stderr_path=backtest_stderr,
                )
                evidence_path = scenario_dir / "rl_evidence.json"
                run_command(
                    build_evidence_command(
                        metrics_path=backtest_session_dir / "backtest_metrics.csv",
                        metadata_path=backtest_session_dir / "session_metadata.json",
                        statistical_report_path=backtest_session_dir / "backtest_statistical_report.json",
                        output_path=evidence_path,
                    ),
                    stdout_path=scenario_dir / "evidence_stdout.log",
                    stderr_path=scenario_dir / "evidence_stderr.log",
                    dry_run=False,
                )
                metrics = read_metrics(backtest_session_dir / "backtest_metrics.csv")

            summary_rows.append(
                build_summary_row(
                    model=model,
                    profile=profile,
                    scenario_dir=scenario_dir,
                    backtest_session_dir=backtest_session_dir,
                    evidence_path=evidence_path,
                    metrics=metrics,
                )
            )
            write_cost_stress_summary(output_dir, summary_rows)

    return output_dir


def _parse_scalar(value: Any) -> float | str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return text


def _current_git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return ""


def main() -> None:
    output_dir = run_cost_stress(build_parser().parse_args())
    print(output_dir)


if __name__ == "__main__":
    main()
