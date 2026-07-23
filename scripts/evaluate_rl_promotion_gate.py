"""Evaluate whether an RL candidate can be promoted for LLM-agent use.

This script consumes preserved multi-seed cost-stress summaries and writes a
machine-readable promotion decision. It does not train or backtest. Its job is
to keep the handoff from research evidence to LLM context explicit and
fail-closed.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DAILY = ROOT / "results" / "daily"
PROMOTION_GATE_SCHEMA_VERSION = "rl_promotion_gate.v1"
DEFAULT_OPERATING_PROFILE = "live_like_2x"
DEFAULT_SEVERE_PROFILE = "live_like_3x"


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    blocking: bool
    observed: Any
    threshold: Any
    reason: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate RL promotion gates from multi-seed cost-stress results.")
    parser.add_argument("--candidate-label", required=True)
    parser.add_argument("--cost-stress-by-seed", type=Path, required=True)
    parser.add_argument("--validation-best", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--run-label", default="rl_promotion_gate")
    parser.add_argument("--min-seeds", type=int, default=5)
    parser.add_argument("--operating-profile", default=DEFAULT_OPERATING_PROFILE)
    parser.add_argument("--severe-profile", default=DEFAULT_SEVERE_PROFILE)
    parser.add_argument("--min-operating-return-pct", type=float, default=0.0)
    parser.add_argument("--min-operating-sharpe", type=float, default=0.0)
    parser.add_argument("--max-operating-drawdown-pct", type=float, default=-40.0)
    parser.add_argument("--min-severe-return-pct", type=float, default=0.0)
    parser.add_argument("--min-severe-sharpe", type=float, default=0.0)
    parser.add_argument("--required-evidence-status", default="VERIFIED")
    parser.add_argument("--run-date", default=None)
    return parser


def create_promotion_gate_dir(
    *,
    results_daily: Path = RESULTS_DAILY,
    run_label: str = "rl_promotion_gate",
    run_date: str | None = None,
) -> Path:
    day = run_date or datetime.now().strftime("%Y-%m-%d")
    base = Path(results_daily) / day / "rl_promotion_gate" / run_label
    base.mkdir(parents=True, exist_ok=True)
    existing = [int(child.name) for child in base.iterdir() if child.is_dir() and child.name.isdigit()]
    out = base / str(max(existing, default=0) + 1)
    out.mkdir(parents=False, exist_ok=False)
    return out


def evaluate_promotion_gate(args: argparse.Namespace) -> Path:
    cost_path = Path(args.cost_stress_by_seed)
    costs = _read_cost_stress_by_seed(cost_path)
    output_dir = Path(args.output_dir) if args.output_dir else create_promotion_gate_dir(
        run_label=args.run_label,
        run_date=args.run_date,
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    gates = build_gate_results(
        costs,
        min_seeds=args.min_seeds,
        operating_profile=args.operating_profile,
        severe_profile=args.severe_profile,
        min_operating_return_pct=args.min_operating_return_pct,
        min_operating_sharpe=args.min_operating_sharpe,
        max_operating_drawdown_pct=args.max_operating_drawdown_pct,
        min_severe_return_pct=args.min_severe_return_pct,
        min_severe_sharpe=args.min_severe_sharpe,
        required_evidence_status=args.required_evidence_status,
    )
    blocking_failures = [gate for gate in gates if gate.blocking and not gate.passed]
    status = "PROMOTED" if not blocking_failures else "NOT_PROMOTED"
    llm_evidence_status = "VERIFIED" if status == "PROMOTED" else "ABSTAIN"
    validation_diagnostics = _validation_diagnostics(Path(args.validation_best)) if args.validation_best else {}
    report = {
        "schema_version": PROMOTION_GATE_SCHEMA_VERSION,
        "candidate_label": args.candidate_label,
        "status": status,
        "llm_evidence_status": llm_evidence_status,
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "summary": _summary(status, blocking_failures),
        "blocking_failures": [gate.name for gate in blocking_failures],
        "gates": [asdict(gate) for gate in gates],
        "aggregate": _aggregate_costs(costs),
        "validation_diagnostics": validation_diagnostics,
        "provenance": {
            "cost_stress_by_seed": str(cost_path),
            "validation_best": str(args.validation_best) if args.validation_best else "",
            "code_commit": _current_git_commit(),
            "thresholds": {
                "min_seeds": int(args.min_seeds),
                "operating_profile": args.operating_profile,
                "severe_profile": args.severe_profile,
                "min_operating_return_pct": float(args.min_operating_return_pct),
                "min_operating_sharpe": float(args.min_operating_sharpe),
                "max_operating_drawdown_pct": float(args.max_operating_drawdown_pct),
                "min_severe_return_pct": float(args.min_severe_return_pct),
                "min_severe_sharpe": float(args.min_severe_sharpe),
                "required_evidence_status": str(args.required_evidence_status),
            },
        },
        "llm_instructions": [
            "Treat llm_evidence_status ABSTAIN as no RL opinion.",
            "Do not infer trades, allocations, quantities, or leverage from this promotion artifact.",
            "Use PROMOTED only as permission to load a separate sanitized RL evidence envelope.",
        ],
    }
    write_gate_summary_csv(output_dir / "promotion_gate_summary.csv", gates)
    (output_dir / "promotion_gate_report.json").write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_dir


def build_gate_results(
    costs: pd.DataFrame,
    *,
    min_seeds: int,
    operating_profile: str,
    severe_profile: str,
    min_operating_return_pct: float,
    min_operating_sharpe: float,
    max_operating_drawdown_pct: float,
    min_severe_return_pct: float,
    min_severe_sharpe: float,
    required_evidence_status: str,
) -> list[GateResult]:
    seeds = sorted({int(seed) for seed in costs["seed"].dropna().unique()})
    required_profiles = [operating_profile, severe_profile]
    profile_seed_counts = {
        profile: int(costs[costs["cost_profile"] == profile]["seed"].nunique())
        for profile in required_profiles
    }
    required_rows = costs[costs["cost_profile"].isin(required_profiles)].copy()
    gates = [
        GateResult(
            name="min_seed_count",
            passed=len(seeds) >= int(min_seeds),
            blocking=True,
            observed={"seed_count": len(seeds), "seeds": seeds},
            threshold={">=": int(min_seeds)},
            reason="Promotion needs a larger multi-seed sample.",
        ),
        GateResult(
            name="required_profiles_present",
            passed=all(count == len(seeds) and len(seeds) > 0 for count in profile_seed_counts.values()),
            blocking=True,
            observed=profile_seed_counts,
            threshold={profile: len(seeds) for profile in required_profiles},
            reason="Every seed must have all required operating and severe cost profiles.",
        ),
        GateResult(
            name="metrics_complete",
            passed=_metrics_complete(required_rows),
            blocking=True,
            observed=_missing_metric_counts(required_rows),
            threshold={"missing_required_metric_values": 0},
            reason="Promotion requires complete return, Sharpe, drawdown, evidence, and promoted fields.",
        ),
    ]
    gates.extend(
        [
            _profile_min_gate(
                costs,
                profile=operating_profile,
                column="total_return_pct",
                threshold=min_operating_return_pct,
                name="operating_return_all_seeds",
                reason="Every seed must be profitable at the operating cost stress.",
            ),
            _profile_min_gate(
                costs,
                profile=operating_profile,
                column="sharpe_ratio",
                threshold=min_operating_sharpe,
                name="operating_sharpe_all_seeds",
                reason="Every seed must have positive risk-adjusted performance at the operating cost stress.",
            ),
            _profile_min_gate(
                costs,
                profile=operating_profile,
                column="max_drawdown_pct",
                threshold=max_operating_drawdown_pct,
                name="operating_drawdown_all_seeds",
                reason="Every seed must stay within the operating drawdown limit.",
            ),
            _profile_min_gate(
                costs,
                profile=severe_profile,
                column="total_return_pct",
                threshold=min_severe_return_pct,
                name="severe_return_all_seeds",
                reason="Every seed must survive the severe cost stress.",
            ),
            _profile_min_gate(
                costs,
                profile=severe_profile,
                column="sharpe_ratio",
                threshold=min_severe_sharpe,
                name="severe_sharpe_all_seeds",
                reason="Every seed must keep non-negative Sharpe under severe cost stress.",
            ),
            _evidence_status_gate(required_rows, required_status=required_evidence_status),
            _promoted_column_gate(required_rows),
        ]
    )
    gates.append(_code_commit_consistency_gate(costs))
    return gates


def write_gate_summary_csv(path: Path, gates: list[GateResult]) -> Path:
    rows = [
        {
            "name": gate.name,
            "passed": gate.passed,
            "blocking": gate.blocking,
            "observed": json.dumps(gate.observed, ensure_ascii=True, sort_keys=True),
            "threshold": json.dumps(gate.threshold, ensure_ascii=True, sort_keys=True),
            "reason": gate.reason,
        }
        for gate in gates
    ]
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _read_cost_stress_by_seed(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    data = pd.read_csv(path)
    required = {
        "seed",
        "cost_profile",
        "total_return_pct",
        "sharpe_ratio",
        "max_drawdown_pct",
        "evidence_status",
        "promoted",
    }
    missing = sorted(required - set(data.columns))
    if missing:
        raise ValueError(f"Missing required cost-stress columns: {', '.join(missing)}")
    for column in ["seed", "total_return_pct", "sharpe_ratio", "max_drawdown_pct"]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data["evidence_status"] = data["evidence_status"].fillna("").astype(str).str.upper()
    return data


def _profile_min_gate(
    costs: pd.DataFrame,
    *,
    profile: str,
    column: str,
    threshold: float,
    name: str,
    reason: str,
) -> GateResult:
    rows = costs[costs["cost_profile"] == profile]
    values = pd.to_numeric(rows[column], errors="coerce").dropna()
    observed_min = float(values.min()) if not values.empty else None
    return GateResult(
        name=name,
        passed=observed_min is not None and observed_min >= float(threshold),
        blocking=True,
        observed={"profile": profile, "metric": column, "min": observed_min},
        threshold={">=": float(threshold)},
        reason=reason,
    )


def _evidence_status_gate(rows: pd.DataFrame, *, required_status: str) -> GateResult:
    statuses = sorted({str(item).upper() for item in rows["evidence_status"].dropna().unique()})
    required = str(required_status).upper()
    return GateResult(
        name="all_evidence_verified",
        passed=bool(statuses) and statuses == [required],
        blocking=True,
        observed={"statuses": statuses},
        threshold={"all_statuses_equal": required},
        reason="LLM-agent promotion requires sanitized evidence envelopes to be verified, not abstained.",
    )


def _promoted_column_gate(rows: pd.DataFrame) -> GateResult:
    values = [_boolish(value) for value in rows["promoted"].tolist()]
    promoted_count = sum(1 for value in values if value is True)
    return GateResult(
        name="all_artifacts_marked_promoted",
        passed=bool(values) and promoted_count == len(values),
        blocking=True,
        observed={"promoted_count": promoted_count, "row_count": len(values)},
        threshold={"promoted_count_equals_row_count": True},
        reason="All source evidence artifacts must carry promoted=true before LLM-agent use.",
    )


def _code_commit_consistency_gate(costs: pd.DataFrame) -> GateResult:
    if "code_commit" not in costs.columns:
        commits: list[str] = []
    else:
        commits = sorted({str(item) for item in costs["code_commit"].dropna().unique() if str(item).strip()})
    return GateResult(
        name="code_commit_consistency",
        passed=len(commits) <= 1,
        blocking=False,
        observed={"commit_count": len(commits), "commits": commits},
        threshold={"commit_count": "<= 1"},
        reason="Mixed code commits are allowed as diagnostics, but promotion reports should explain them.",
    )


def _metrics_complete(rows: pd.DataFrame) -> bool:
    return all(count == 0 for count in _missing_metric_counts(rows).values())


def _missing_metric_counts(rows: pd.DataFrame) -> dict[str, int]:
    required = [
        "total_return_pct",
        "sharpe_ratio",
        "max_drawdown_pct",
        "evidence_status",
        "promoted",
    ]
    missing: dict[str, int] = {}
    for column in required:
        if column not in rows.columns:
            missing[column] = int(len(rows))
            continue
        missing[column] = int(rows[column].isna().sum() + (rows[column].astype(str).str.strip() == "").sum())
    return missing


def _aggregate_costs(costs: pd.DataFrame) -> dict[str, Any]:
    profiles: dict[str, Any] = {}
    for profile, group in costs.groupby("cost_profile"):
        profile_data: dict[str, Any] = {"seed_count": int(group["seed"].nunique())}
        for column in ["total_return_pct", "sharpe_ratio", "max_drawdown_pct"]:
            values = pd.to_numeric(group[column], errors="coerce").dropna()
            profile_data[column] = {
                "mean": _finite_or_none(values.mean()),
                "min": _finite_or_none(values.min()),
                "max": _finite_or_none(values.max()),
            }
        profiles[str(profile)] = profile_data
    return {
        "seed_count": int(costs["seed"].nunique()),
        "profiles": profiles,
    }


def _validation_diagnostics(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "status": "missing"}
    data = pd.read_csv(path)
    diagnostics: dict[str, Any] = {"path": str(path), "rows": int(len(data))}
    if {"algo", "timesteps", "selection_score"}.issubset(data.columns):
        selected: dict[str, Any] = {}
        for algo, group in data.groupby("algo"):
            selected[str(algo)] = {
                "timesteps": sorted(int(item) for item in group["timesteps"].dropna().unique()),
                "mean_selection_score": _finite_or_none(pd.to_numeric(group["selection_score"], errors="coerce").mean()),
            }
        diagnostics["selected_by_algo"] = selected
    return diagnostics


def _summary(status: str, blocking_failures: list[GateResult]) -> str:
    if status == "PROMOTED":
        return "RL candidate passed configured promotion gates."
    names = ", ".join(gate.name for gate in blocking_failures)
    return f"RL candidate is not promoted; blocking gates failed: {names}."


def _boolish(value: Any) -> bool | None:
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n", ""}:
        return False
    return None


def _finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except Exception:
        return None
    return number if math.isfinite(number) else None


def _current_git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return ""


def main() -> None:
    output_dir = evaluate_promotion_gate(build_parser().parse_args())
    print(output_dir)


if __name__ == "__main__":
    main()
