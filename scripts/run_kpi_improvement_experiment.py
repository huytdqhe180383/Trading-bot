"""Run the audit-aware KPI improvement experiment phases.

The runner restores the immutable 107% checkpoint before each seed so seed
comparisons do not accidentally chain-train on top of the previous seed.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import signal
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RESULTS_DAILY = ROOT / "results" / "daily"
REPORT_DAILY = ROOT / "report" / "daily"
BASELINE_BACKUP = ROOT / "results" / "important" / "model_backups" / "2026-05-24_107pct_baseline"
METHODS = ["dynamic_weighted", "regime_weighted", "mean", "weighted"]
SEEDS = [42, 1337, 2026]
RUN_TIMEOUT_SECONDS: float | None = 3 * 60 * 60
RUN_POLL_SECONDS = 20 * 60
PHASE1_PPO_STEPS = 200_000
PHASE1_SAC_STEPS = 50_000
PHASE2_QUICK_PPO_STEPS = 60_000
PHASE2_QUICK_SAC_STEPS = 15_000
PHASE2_FULL_PPO_STEPS = 80_000
PHASE2_FULL_SAC_STEPS = 20_000


@dataclass(frozen=True)
class Variant:
    name: str
    env: dict[str, str]


VARIANT_A = Variant(
    name="variant_a_balanced_conservative",
    env={
        "SLIPPAGE_MODEL": "vol_scaled",
        "SLIPPAGE_VOL_WINDOW": "24",
        "SLIPPAGE_VOL_SCALAR": "10",
        "SLIPPAGE_VOL_CAP_MULT": "3",
        "KILL_SWITCH_ENABLED_EVAL": "true",
        "KILL_SWITCH_DRAWDOWN_THRESHOLD": "-0.15",
        "STEP_TURNOVER_CAP_ENABLED": "true",
        "STEP_TURNOVER_CAP_NORMAL": "0.20",
        "STEP_TURNOVER_CAP_STRESS": "0.12",
        "STEP_TURNOVER_CAP_CRISIS": "0.08",
    },
)

VARIANT_B = Variant(
    name="variant_b_balanced_light_retune",
    env={
        **VARIANT_A.env,
        "REWARD_TURNOVER_WEIGHT": "1.35",
        "REWARD_MISSED_OPPORTUNITY_WEIGHT": "0.30",
        "RISK_GOVERNOR_STRESS_CASH_FLOOR": "0.30",
        "RISK_GOVERNOR_CRISIS_CASH_FLOOR": "0.50",
        "RISK_GOVERNOR_STRESS_MAX_RISK_ON": "0.70",
        "RISK_GOVERNOR_CRISIS_MAX_RISK_ON": "0.50",
    },
)


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _parse_csv_subset(raw: str, allowed: list, *, item_type):
    values = []
    allowed_set = set(allowed)
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        value = item_type(token)
        if value not in allowed_set:
            raise ValueError(f"Unsupported value {value!r}; allowed values are: {allowed}")
        values.append(value)
    return values or list(allowed)


def _kill_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except Exception:
            process.terminate()


def _run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    dry_run: bool = False,
    timeout_seconds: float | None = None,
    poll_seconds: float | None = None,
) -> None:
    printable = " ".join(command)
    print(f"[run] {printable}")
    if dry_run:
        return
    process_env = os.environ.copy()
    process_env["PYTHONUNBUFFERED"] = "1"
    if env:
        process_env.update(env)
    timeout = RUN_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    poll = RUN_POLL_SECONDS if poll_seconds is None else poll_seconds
    if timeout is not None and timeout <= 0:
        timeout = None
    if poll <= 0:
        poll = 60
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    preexec_fn = None if os.name == "nt" else os.setsid
    start = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=process_env,
        creationflags=creationflags,
        preexec_fn=preexec_fn,
    )
    try:
        while True:
            return_code = process.poll()
            if return_code is not None:
                if return_code != 0:
                    raise subprocess.CalledProcessError(return_code, command)
                return
            elapsed = time.monotonic() - start
            if timeout is not None and elapsed >= timeout:
                print(f"[timeout] pid={process.pid} elapsed={elapsed:.1f}s command={printable}")
                _kill_process_tree(process)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise subprocess.TimeoutExpired(command, timeout)
            print(f"[wait] pid={process.pid} elapsed={elapsed / 60:.1f}m command={printable}", flush=True)
            if timeout is None:
                sleep_for = poll
            else:
                sleep_for = min(poll, max(0.1, timeout - elapsed))
            time.sleep(sleep_for)
    except BaseException:
        _kill_process_tree(process)
        raise


def _next_daily_experiment_dir() -> Path:
    base = RESULTS_DAILY / _today() / "kpi_improvement_experiment"
    base.mkdir(parents=True, exist_ok=True)
    nums = [int(p.name) for p in base.iterdir() if p.is_dir() and p.name.isdigit()]
    out = base / str(max(nums, default=0) + 1)
    out.mkdir(parents=True, exist_ok=False)
    return out


def _resolve_output_dir(output_id: int | None) -> Path:
    if output_id is None:
        return _next_daily_experiment_dir()
    out = RESULTS_DAILY / _today() / "kpi_improvement_experiment" / str(output_id)
    out.mkdir(parents=True, exist_ok=True)
    return out


def _latest_session_dir(before: set[Path]) -> Path:
    day_dir = RESULTS_DAILY / _today()
    candidates = [
        p
        for p in day_dir.iterdir()
        if p.is_dir() and p.name.isdigit() and p not in before
    ]
    if not candidates:
        raise RuntimeError("Backtest did not create a new daily session directory.")
    return max(candidates, key=lambda p: int(p.name))


def _session_dirs() -> set[Path]:
    day_dir = RESULTS_DAILY / _today()
    if not day_dir.exists():
        return set()
    return {p for p in day_dir.iterdir() if p.is_dir() and p.name.isdigit()}


def restore_baseline_models(algos: tuple[str, ...] = ("PPO", "SAC")) -> None:
    sources = {
        "PPO": BASELINE_BACKUP / "models" / "PPO" / "ppo_best.zip",
        "SAC": BASELINE_BACKUP / "models" / "SAC" / "sac_best.zip",
    }
    for algo in algos:
        if algo not in sources:
            raise ValueError(f"Unsupported algorithm for restore: {algo}")
        if not sources[algo].exists():
            raise FileNotFoundError(f"Missing baseline checkpoint backup for {algo} under {BASELINE_BACKUP}")
    targets = []
    for algo in algos:
        filename = "ppo_best.zip" if algo == "PPO" else "sac_best.zip"
        targets.append((sources[algo], ROOT / "models" / algo / filename))
    for src, dst in targets:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def snapshot_seed_models(seed_dir: Path) -> None:
    model_dir = seed_dir / "models"
    for algo, filename in [("PPO", "ppo_best.zip"), ("SAC", "sac_best.zip")]:
        src = ROOT / "models" / algo / filename
        if src.exists():
            dst = model_dir / algo / filename
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def train_pair(
    *,
    seed: int,
    ppo_steps: int,
    sac_steps: int,
    algos: tuple[str, ...],
    env: dict[str, str] | None,
    dry_run: bool,
) -> None:
    if "PPO" in algos:
        _run(
            [
                sys.executable,
                "train.py",
                "--algo",
                "PPO",
                "--resume",
                "--timesteps",
                str(ppo_steps),
                "--seed",
                str(seed),
                "--validation-fraction",
                "0.2",
                "--skip-backtest",
            ],
            env=env,
            dry_run=dry_run,
        )
    if "SAC" in algos:
        _run(
            [
                sys.executable,
                "train.py",
                "--algo",
                "SAC",
                "--resume",
                "--timesteps",
                str(sac_steps),
                "--seed",
                str(seed),
                "--validation-fraction",
                "0.2",
                "--disable-eval-callback",
                "--skip-backtest",
            ],
            env=env,
            dry_run=dry_run,
        )


def evaluate_methods(
    *,
    output_dir: Path,
    phase: str,
    seed: int,
    variant: str,
    env: dict[str, str] | None,
    dry_run: bool,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for method in METHODS:
        before = _session_dirs()
        _run(
            [
                sys.executable,
                "backtest.py",
                "--pipeline",
                "rl_only",
                "--realism-profile",
                "live_like",
                "--method",
                method,
            ],
            env=env,
            dry_run=dry_run,
        )
        if dry_run:
            continue
        session_dir = _latest_session_dir(before)
        metrics = pd.read_csv(session_dir / "backtest_metrics.csv", index_col=0)["value"].to_dict()
        rows.append(
            {
                "phase": phase,
                "variant": variant,
                "seed": seed,
                "method": method,
                "session_dir": str(session_dir.relative_to(ROOT)),
                **metrics,
            }
        )
    if rows:
        out_path = output_dir / f"{phase}_{variant}_seed_{seed}_metrics.csv"
        pd.DataFrame(rows).to_csv(out_path, index=False)
    return rows


def rank_score(row: dict[str, object]) -> tuple[float, float, float, float]:
    return (
        float(row.get("sharpe_ratio") or -999.0),
        float(row.get("sortino_ratio") or -999.0),
        float(row.get("calmar_ratio") or -999.0),
        float(row.get("max_drawdown_pct") or -999.0),
    )


def _merge_rows(existing: list[dict[str, object]], new_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    merged: dict[tuple[object, object, object, object], dict[str, object]] = {}
    for row in existing + new_rows:
        key = (row.get("phase"), row.get("variant"), row.get("seed"), row.get("method"))
        merged[key] = row
    return list(merged.values())


def _load_existing_summary(summary_path: Path) -> list[dict[str, object]]:
    if not summary_path.exists():
        return []
    return pd.read_csv(summary_path).to_dict(orient="records")


def write_summary(output_dir: Path, rows: list[dict[str, object]]) -> Path:
    summary_path = output_dir / "experiment_metrics.csv"
    merged_rows = _merge_rows(_load_existing_summary(summary_path), rows)
    if merged_rows:
        with summary_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(merged_rows[0].keys()), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(merged_rows)
    return summary_path


def write_report(output_dir: Path, rows: list[dict[str, object]], args: argparse.Namespace) -> Path:
    report_dir = REPORT_DAILY / _today()
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"kpi_improvement_experiment_{output_dir.name}.md"
    summary_path = output_dir / "experiment_metrics.csv"
    combined_rows = _merge_rows(_load_existing_summary(summary_path), rows)
    by_phase = pd.DataFrame(combined_rows) if combined_rows else pd.DataFrame()
    best_line = "No completed metric rows yet."
    if not by_phase.empty:
        best = max(combined_rows, key=rank_score)
        best_line = (
            f"Best completed row: phase `{best['phase']}`, variant `{best['variant']}`, "
            f"seed `{best['seed']}`, method `{best['method']}`, "
            f"Sharpe `{float(best['sharpe_ratio']):.4f}`, "
            f"return `{float(best['total_return_pct']):.2f}%`, "
            f"max DD `{float(best['max_drawdown_pct']):.2f}%`."
        )
    lines = [
        "# KPI Improvement Experiment",
        "",
        f"- Created: {_today()}",
        f"- Results directory: `{output_dir.relative_to(ROOT)}`",
        f"- Phase requested: `{args.phase}`",
        f"- Baseline checkpoint source: `{BASELINE_BACKUP.relative_to(ROOT)}`",
        f"- Methods: `{', '.join(METHODS)}`",
        f"- Seeds: `{', '.join(map(str, SEEDS))}`",
        "",
        "## Status",
        "",
        best_line,
        "",
        "## Notes",
        "",
        "- Each seed restores the immutable 107% checkpoint before training.",
        "- Phase 1 uses flat slippage and disabled eval kill switch to isolate resume-only effects.",
        "- Phase 2 enables volatility-scaled slippage, eval kill switch, and step turnover caps.",
        "- Promotion still requires manual review against the clean Phase 0 baseline gates.",
    ]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def run_phase1(
    output_dir: Path,
    *,
    dry_run: bool,
    start_seed: int | None,
    only_seed: int | None,
    algos: tuple[str, ...],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    phase_dir = output_dir / "phase1_resume_expansion"
    phase_dir.mkdir(parents=True, exist_ok=True)
    for seed in SEEDS:
        if only_seed is not None and seed != only_seed:
            continue
        if start_seed is not None and seed < start_seed:
            continue
        if not dry_run:
            restore_baseline_models(algos)
        train_pair(
            seed=seed,
            ppo_steps=PHASE1_PPO_STEPS,
            sac_steps=PHASE1_SAC_STEPS,
            algos=algos,
            env=None,
            dry_run=dry_run,
        )
        seed_dir = phase_dir / f"seed_{seed}"
        seed_dir.mkdir(parents=True, exist_ok=True)
        if not dry_run:
            snapshot_seed_models(seed_dir)
        rows.extend(
            evaluate_methods(
                output_dir=phase_dir,
                phase="phase1_resume_expansion",
                seed=seed,
                variant="flat_resume_only",
                env=None,
                dry_run=dry_run,
            )
        )
    return rows


def run_phase2_quick(output_dir: Path, *, dry_run: bool) -> tuple[str | None, list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    phase_dir = output_dir / "phase2_quick_screen"
    phase_dir.mkdir(parents=True, exist_ok=True)
    for variant in [VARIANT_A, VARIANT_B]:
        if not dry_run:
            restore_baseline_models()
        train_pair(
            seed=42,
            ppo_steps=PHASE2_QUICK_PPO_STEPS,
            sac_steps=PHASE2_QUICK_SAC_STEPS,
            algos=("PPO", "SAC"),
            env=variant.env,
            dry_run=dry_run,
        )
        variant_dir = phase_dir / variant.name
        variant_dir.mkdir(parents=True, exist_ok=True)
        if not dry_run:
            snapshot_seed_models(variant_dir / "seed_42")
        rows.extend(
            evaluate_methods(
                output_dir=phase_dir,
                phase="phase2_quick_screen",
                seed=42,
                variant=variant.name,
                env=variant.env,
                dry_run=dry_run,
            )
        )
    if dry_run or not rows:
        return None, rows
    challenger_rows = [r for r in rows if r["method"] == "regime_weighted"]
    winner = max(challenger_rows or rows, key=rank_score)["variant"]
    (phase_dir / "winner.json").write_text(json.dumps({"winner": winner}, indent=2), encoding="utf-8")
    return str(winner), rows


def run_phase2_full(output_dir: Path, winner: str, *, dry_run: bool) -> list[dict[str, object]]:
    variant = VARIANT_A if winner == VARIANT_A.name else VARIANT_B
    rows: list[dict[str, object]] = []
    phase_dir = output_dir / "phase2_full_validation"
    phase_dir.mkdir(parents=True, exist_ok=True)
    for seed in SEEDS:
        if not dry_run:
            restore_baseline_models()
        train_pair(
            seed=seed,
            ppo_steps=PHASE2_FULL_PPO_STEPS,
            sac_steps=PHASE2_FULL_SAC_STEPS,
            algos=("PPO", "SAC"),
            env=variant.env,
            dry_run=dry_run,
        )
        seed_dir = phase_dir / variant.name / f"seed_{seed}"
        seed_dir.mkdir(parents=True, exist_ok=True)
        if not dry_run:
            snapshot_seed_models(seed_dir)
        rows.extend(
            evaluate_methods(
                output_dir=phase_dir,
                phase="phase2_full_validation",
                seed=seed,
                variant=variant.name,
                env=variant.env,
                dry_run=dry_run,
            )
        )
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=["phase1", "phase2-quick", "phase2-full", "all"],
        default="all",
    )
    parser.add_argument(
        "--phase2-winner",
        choices=[VARIANT_A.name, VARIANT_B.name],
        default=None,
        help="Required for --phase phase2-full when not running quick screen first.",
    )
    parser.add_argument(
        "--output-id",
        type=int,
        default=None,
        help="Reuse an existing results/daily/<date>/kpi_improvement_experiment/<N> directory.",
    )
    parser.add_argument(
        "--start-seed",
        type=int,
        default=None,
        choices=SEEDS,
        help="Skip earlier seeds when resuming Phase 1.",
    )
    parser.add_argument(
        "--only-seed",
        type=int,
        default=None,
        choices=SEEDS,
        help="Run only one Phase 1 seed. Useful for targeted SAC-only reruns.",
    )
    parser.add_argument(
        "--algos",
        default="PPO,SAC",
        help="Comma-separated algorithms to run for Phase 1 resume logic, e.g. SAC or PPO,SAC.",
    )
    parser.add_argument(
        "--seeds",
        default=",".join(map(str, SEEDS)),
        help="Comma-separated seed subset for phase runs.",
    )
    parser.add_argument(
        "--methods",
        default=",".join(METHODS),
        help="Comma-separated method subset for evaluations.",
    )
    parser.add_argument(
        "--command-timeout-minutes",
        type=float,
        default=180.0,
        help="Per child command timeout. Use 0 to disable.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=1200.0,
        help="Heartbeat interval while child commands run. Default is 20 minutes.",
    )
    parser.add_argument("--phase1-ppo-steps", type=int, default=PHASE1_PPO_STEPS)
    parser.add_argument("--phase1-sac-steps", type=int, default=PHASE1_SAC_STEPS)
    parser.add_argument("--phase2-quick-ppo-steps", type=int, default=PHASE2_QUICK_PPO_STEPS)
    parser.add_argument("--phase2-quick-sac-steps", type=int, default=PHASE2_QUICK_SAC_STEPS)
    parser.add_argument("--phase2-full-ppo-steps", type=int, default=PHASE2_FULL_PPO_STEPS)
    parser.add_argument("--phase2-full-sac-steps", type=int, default=PHASE2_FULL_SAC_STEPS)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> None:
    global METHODS, SEEDS, RUN_TIMEOUT_SECONDS, RUN_POLL_SECONDS
    global PHASE1_PPO_STEPS, PHASE1_SAC_STEPS
    global PHASE2_QUICK_PPO_STEPS, PHASE2_QUICK_SAC_STEPS
    global PHASE2_FULL_PPO_STEPS, PHASE2_FULL_SAC_STEPS

    args = build_parser().parse_args()
    SEEDS = _parse_csv_subset(args.seeds, SEEDS, item_type=int)
    METHODS = _parse_csv_subset(args.methods, METHODS, item_type=str)
    RUN_TIMEOUT_SECONDS = None if args.command_timeout_minutes <= 0 else args.command_timeout_minutes * 60
    RUN_POLL_SECONDS = args.poll_seconds
    PHASE1_PPO_STEPS = args.phase1_ppo_steps
    PHASE1_SAC_STEPS = args.phase1_sac_steps
    PHASE2_QUICK_PPO_STEPS = args.phase2_quick_ppo_steps
    PHASE2_QUICK_SAC_STEPS = args.phase2_quick_sac_steps
    PHASE2_FULL_PPO_STEPS = args.phase2_full_ppo_steps
    PHASE2_FULL_SAC_STEPS = args.phase2_full_sac_steps

    output_dir = _resolve_output_dir(args.output_id)
    rows: list[dict[str, object]] = []
    winner = args.phase2_winner
    phase1_algos = tuple(
        algo.strip().upper()
        for algo in args.algos.split(",")
        if algo.strip()
    )
    invalid_algos = sorted(set(phase1_algos).difference({"PPO", "SAC"}))
    if invalid_algos:
        raise ValueError(f"Unsupported algorithms: {invalid_algos}")

    if args.phase in {"phase1", "all"}:
        rows.extend(
            run_phase1(
                output_dir,
                dry_run=args.dry_run,
                start_seed=args.start_seed,
                only_seed=args.only_seed,
                algos=phase1_algos,
            )
        )

    if args.phase in {"phase2-quick", "all"}:
        winner, quick_rows = run_phase2_quick(output_dir, dry_run=args.dry_run)
        rows.extend(quick_rows)

    if args.phase in {"phase2-full", "all"}:
        if not winner:
            raise ValueError("--phase2-winner is required for phase2-full without a quick-screen winner.")
        rows.extend(run_phase2_full(output_dir, winner, dry_run=args.dry_run))

    if args.dry_run:
        print(f"[dry-run] output directory would be: {output_dir}")
        return

    summary_path = write_summary(output_dir, rows)
    report_path = write_report(output_dir, rows, args)
    print(f"[summary] {summary_path}")
    print(f"[report] {report_path}")


if __name__ == "__main__":
    main()
