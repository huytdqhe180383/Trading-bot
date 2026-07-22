"""Run a small RL multi-seed training/evaluation screen.

This runner is intentionally narrow: it trains fresh PPO/SAC pairs with the
rolling validation callback, evaluates each seed through the normal live-like
RL-only backtest, builds a fail-closed evidence envelope, and writes an
aggregate summary.  It is a cheap screen before spending longer training
budgets or treating any model as agent-trustworthy.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DAILY = ROOT / "results" / "daily"
DEFAULT_SEEDS = (41, 42, 43)
DEFAULT_PIPELINE = "rl_only"
DEFAULT_REALISM_PROFILE = "live_like"
DEFAULT_METHOD = "dynamic_weighted"
ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a fixed-semantics RL seed screen.")
    parser.add_argument("--seeds", default=",".join(map(str, DEFAULT_SEEDS)))
    parser.add_argument("--timesteps", type=int, default=50_000)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--validation-fraction", type=float, default=0.2)
    parser.add_argument("--validation-windows", type=int, default=5)
    parser.add_argument("--pipeline", default=DEFAULT_PIPELINE, choices=["rl_only", "rl_kronos", "rl_tradingagents", "rl_full"])
    parser.add_argument("--realism-profile", default=DEFAULT_REALISM_PROFILE, choices=["baseline", "live_like"])
    parser.add_argument(
        "--method",
        default=DEFAULT_METHOD,
        choices=["mean", "voting", "weighted", "dynamic_weighted", "regime_weighted", "imca"],
    )
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--run-label", default="rl_seed_screen")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def parse_seeds(value: str) -> list[int]:
    seeds = [int(part.strip()) for part in str(value).split(",") if part.strip()]
    if not seeds:
        raise ValueError("At least one seed is required.")
    return seeds


def create_seed_screen_dir(
    *,
    results_daily: Path = RESULTS_DAILY,
    run_label: str = "rl_seed_screen",
    run_date: str | None = None,
) -> Path:
    day = run_date or datetime.now().strftime("%Y-%m-%d")
    base = Path(results_daily) / day / run_label
    base.mkdir(parents=True, exist_ok=True)
    existing = [int(child.name) for child in base.iterdir() if child.is_dir() and child.name.isdigit()]
    out = base / str(max(existing, default=0) + 1)
    out.mkdir(parents=False, exist_ok=False)
    return out


def build_train_command(
    *,
    seed: int,
    models_dir: Path,
    timesteps: int,
    device: str,
    validation_fraction: float,
    validation_windows: int,
) -> list[str]:
    return [
        sys.executable,
        "train.py",
        "--algo",
        "ALL",
        "--timesteps",
        str(int(timesteps)),
        "--device",
        str(device),
        "--seed",
        str(int(seed)),
        "--validation-fraction",
        str(float(validation_fraction)),
        "--validation-windows",
        str(int(validation_windows)),
        "--models-dir",
        str(models_dir),
        "--skip-backtest",
    ]


def build_backtest_command(
    *,
    models_dir: Path,
    pipeline: str = DEFAULT_PIPELINE,
    realism_profile: str = DEFAULT_REALISM_PROFILE,
    method: str = DEFAULT_METHOD,
) -> list[str]:
    return [
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
        "--autosave-profit-threshold",
        "999999",
    ]


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


def copy_validation_metrics(seed_dir: Path) -> None:
    for algo in ("PPO", "SAC"):
        source = ROOT / "logs" / algo / "rolling_validation_metrics.csv"
        if source.exists():
            target = seed_dir / f"{algo.lower()}_rolling_validation_metrics.csv"
            target.write_bytes(source.read_bytes())


def read_metrics(metrics_path: Path) -> dict[str, float | str | None]:
    if not Path(metrics_path).exists():
        return {}
    raw = pd.read_csv(metrics_path, index_col=0)["value"].to_dict()
    return {str(key): _parse_scalar(value) for key, value in raw.items()}


def build_seed_summary_row(
    *,
    seed: int,
    seed_dir: Path,
    models_dir: Path,
    backtest_session_dir: Path,
    evidence_path: Path,
    metrics: dict[str, Any],
) -> dict[str, Any]:
    return {
        "seed": int(seed),
        "seed_dir": str(seed_dir),
        "models_dir": str(models_dir),
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


def write_seed_screen_summary(output_dir: Path, rows: list[dict[str, Any]]) -> Path:
    out = Path(output_dir) / "seed_screen_summary.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    return out


def run_seed_screen(args: argparse.Namespace) -> Path:
    seeds = parse_seeds(args.seeds)
    output_dir = Path(args.output_dir) if args.output_dir else create_seed_screen_dir(run_label=args.run_label)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_rows: list[dict[str, Any]] = []

    for seed in seeds:
        seed_dir = output_dir / f"seed_{seed}"
        seed_dir.mkdir(parents=True, exist_ok=True)
        models_dir = seed_dir / "models"
        train_command = build_train_command(
            seed=seed,
            models_dir=models_dir,
            timesteps=args.timesteps,
            device=args.device,
            validation_fraction=args.validation_fraction,
            validation_windows=args.validation_windows,
        )
        run_command(
            train_command,
            stdout_path=seed_dir / "training_stdout.log",
            stderr_path=seed_dir / "training_stderr.log",
            dry_run=args.dry_run,
        )
        copy_validation_metrics(seed_dir)

        backtest_command = build_backtest_command(
            models_dir=models_dir,
            pipeline=args.pipeline,
            realism_profile=args.realism_profile,
            method=args.method,
        )
        backtest_stdout = seed_dir / "backtest_stdout.log"
        backtest_stderr = seed_dir / "backtest_stderr.log"
        run_command(
            backtest_command,
            stdout_path=backtest_stdout,
            stderr_path=backtest_stderr,
            dry_run=args.dry_run,
        )

        if args.dry_run:
            backtest_session_dir = seed_dir / "dry_run_backtest_session"
            metrics: dict[str, Any] = {}
            evidence_path = seed_dir / "rl_evidence.json"
        else:
            backtest_session_dir = parse_backtest_session_dir(stdout_path=backtest_stdout, stderr_path=backtest_stderr)
            evidence_path = seed_dir / "rl_evidence.json"
            evidence_command = build_evidence_command(
                metrics_path=backtest_session_dir / "backtest_metrics.csv",
                metadata_path=backtest_session_dir / "session_metadata.json",
                statistical_report_path=backtest_session_dir / "backtest_statistical_report.json",
                output_path=evidence_path,
            )
            run_command(
                evidence_command,
                stdout_path=seed_dir / "evidence_stdout.log",
                stderr_path=seed_dir / "evidence_stderr.log",
                dry_run=False,
            )
            metrics = read_metrics(backtest_session_dir / "backtest_metrics.csv")

        summary_rows.append(
            build_seed_summary_row(
                seed=seed,
                seed_dir=seed_dir,
                models_dir=models_dir,
                backtest_session_dir=backtest_session_dir,
                evidence_path=evidence_path,
                metrics=metrics,
            )
        )
        write_seed_screen_summary(output_dir, summary_rows)

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
    output_dir = run_seed_screen(build_parser().parse_args())
    print(output_dir)


if __name__ == "__main__":
    main()
