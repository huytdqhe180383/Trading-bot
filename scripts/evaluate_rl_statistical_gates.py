"""Evaluate statistical reliability gates for an RL promotion candidate.

The promotion gate answers "did every preserved seed survive the configured
cost profiles?"  This script answers a narrower statistical question: how wide
is the seed-level uncertainty, and are the selection-bias diagnostics required
for LLM-agent trust actually present?

It deliberately does not fabricate Deflated Sharpe Ratio or PBO. Those values
must come from a trial registry / CSCV workflow and are supplied explicitly
when available.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DAILY = ROOT / "results" / "daily"
STATISTICAL_SCHEMA_VERSION = "rl_statistical_gates.v1"
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
    parser = argparse.ArgumentParser(description="Evaluate multi-seed RL statistical reliability gates.")
    parser.add_argument("--candidate-label", required=True)
    parser.add_argument("--cost-stress-by-seed", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--run-label", default="rl_statistical_gates")
    parser.add_argument("--run-date", default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-bootstrap", type=int, default=10_000)
    parser.add_argument("--min-statistical-seeds", type=int, default=10)
    parser.add_argument("--operating-profile", default=DEFAULT_OPERATING_PROFILE)
    parser.add_argument("--severe-profile", default=DEFAULT_SEVERE_PROFILE)
    parser.add_argument("--min-bootstrap-probability", type=float, default=0.75)
    parser.add_argument("--min-operating-return-pct", type=float, default=0.0)
    parser.add_argument("--min-operating-sharpe", type=float, default=0.0)
    parser.add_argument("--max-operating-drawdown-pct", type=float, default=-40.0)
    parser.add_argument("--min-severe-return-pct", type=float, default=0.0)
    parser.add_argument("--min-severe-sharpe", type=float, default=0.0)
    parser.add_argument("--max-severe-drawdown-pct", type=float, default=-40.0)
    parser.add_argument("--deflated-sharpe-probability", type=float, default=None)
    parser.add_argument("--min-deflated-sharpe-probability", type=float, default=0.95)
    parser.add_argument("--backtest-overfit-probability", type=float, default=None)
    parser.add_argument("--max-backtest-overfit-probability", type=float, default=0.10)
    parser.add_argument(
        "--require-selection-bias-diagnostics",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require supplied DSR/PBO diagnostics for the statistical gate to pass.",
    )
    return parser


def create_statistical_gate_dir(
    *,
    results_daily: Path = RESULTS_DAILY,
    run_label: str = "rl_statistical_gates",
    run_date: str | None = None,
) -> Path:
    day = run_date or datetime.now().strftime("%Y-%m-%d")
    base = Path(results_daily) / day / "rl_statistical_gates" / run_label
    base.mkdir(parents=True, exist_ok=True)
    existing = [int(child.name) for child in base.iterdir() if child.is_dir() and child.name.isdigit()]
    out = base / str(max(existing, default=0) + 1)
    out.mkdir(parents=False, exist_ok=False)
    return out


def evaluate_statistical_gates(args: argparse.Namespace) -> Path:
    costs = _read_cost_stress_by_seed(Path(args.cost_stress_by_seed))
    output_dir = Path(args.output_dir) if args.output_dir else create_statistical_gate_dir(
        run_label=args.run_label,
        run_date=args.run_date,
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    profile_stats = build_profile_statistics(
        costs,
        profiles=[args.operating_profile, args.severe_profile],
        seed=int(args.seed),
        n_bootstrap=int(args.n_bootstrap),
    )
    gates = build_gate_results(
        costs,
        profile_stats,
        min_statistical_seeds=int(args.min_statistical_seeds),
        operating_profile=args.operating_profile,
        severe_profile=args.severe_profile,
        min_bootstrap_probability=float(args.min_bootstrap_probability),
        min_operating_return_pct=float(args.min_operating_return_pct),
        min_operating_sharpe=float(args.min_operating_sharpe),
        max_operating_drawdown_pct=float(args.max_operating_drawdown_pct),
        min_severe_return_pct=float(args.min_severe_return_pct),
        min_severe_sharpe=float(args.min_severe_sharpe),
        max_severe_drawdown_pct=float(args.max_severe_drawdown_pct),
        seed=int(args.seed),
        n_bootstrap=int(args.n_bootstrap),
        deflated_sharpe_probability=args.deflated_sharpe_probability,
        min_deflated_sharpe_probability=float(args.min_deflated_sharpe_probability),
        backtest_overfit_probability=args.backtest_overfit_probability,
        max_backtest_overfit_probability=float(args.max_backtest_overfit_probability),
        require_selection_bias_diagnostics=bool(args.require_selection_bias_diagnostics),
    )
    blocking_failures = [gate for gate in gates if gate.blocking and not gate.passed]
    status = "PASSED" if not blocking_failures else "FAILED"
    report = {
        "schema_version": STATISTICAL_SCHEMA_VERSION,
        "candidate_label": args.candidate_label,
        "status": status,
        "statistical_gates_passed": status == "PASSED",
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "method": "nonparametric_seed_bootstrap",
        "summary": _summary(status, blocking_failures),
        "blocking_failures": [gate.name for gate in blocking_failures],
        "parameters": {
            "seed": int(args.seed),
            "n_bootstrap": int(args.n_bootstrap),
            "min_statistical_seeds": int(args.min_statistical_seeds),
            "operating_profile": args.operating_profile,
            "severe_profile": args.severe_profile,
            "min_bootstrap_probability": float(args.min_bootstrap_probability),
            "require_selection_bias_diagnostics": bool(args.require_selection_bias_diagnostics),
            "thresholds": {
                "min_operating_return_pct": float(args.min_operating_return_pct),
                "min_operating_sharpe": float(args.min_operating_sharpe),
                "max_operating_drawdown_pct": float(args.max_operating_drawdown_pct),
                "min_severe_return_pct": float(args.min_severe_return_pct),
                "min_severe_sharpe": float(args.min_severe_sharpe),
                "max_severe_drawdown_pct": float(args.max_severe_drawdown_pct),
                "min_deflated_sharpe_probability": float(args.min_deflated_sharpe_probability),
                "max_backtest_overfit_probability": float(args.max_backtest_overfit_probability),
            },
        },
        "sample": {
            "seed_count": int(costs["seed"].nunique()),
            "row_count": int(len(costs)),
            "profiles": {
                profile: int(costs[costs["cost_profile"] == profile]["seed"].nunique())
                for profile in [args.operating_profile, args.severe_profile]
            },
        },
        "profiles": profile_stats,
        "selection_bias": {
            "deflated_sharpe_probability": _finite_or_none(args.deflated_sharpe_probability),
            "deflated_sharpe_available": args.deflated_sharpe_probability is not None,
            "backtest_overfit_probability": _finite_or_none(args.backtest_overfit_probability),
            "backtest_overfit_probability_available": args.backtest_overfit_probability is not None,
            "caveat": "DSR/PBO are not inferred from the cost-stress table; supply them from the trial-registry/CSCV workflow.",
        },
        "gate_status": {
            "statistical_gates": "passed" if status == "PASSED" else "failed",
            "statistical_gates_passed": status == "PASSED",
            "blocking_failures": [gate.name for gate in blocking_failures],
        },
        "gates": [asdict(gate) for gate in gates],
        "provenance": {
            "cost_stress_by_seed": str(args.cost_stress_by_seed),
        },
        "caveats": [
            "Seed bootstrap estimates uncertainty over the observed trained seeds only.",
            "The report does not replace causal-integrity, calibration, or prospective-shadow gates.",
            "DSR/PBO must come from a preserved trial registry and temporal cross-validation; missing values fail closed by default.",
        ],
    }
    write_gate_summary_csv(output_dir / "statistical_gate_summary.csv", gates)
    (output_dir / "rl_statistical_report.json").write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_dir


def build_profile_statistics(
    costs: pd.DataFrame,
    *,
    profiles: list[str],
    seed: int,
    n_bootstrap: int,
) -> dict[str, Any]:
    rng = np.random.default_rng(int(seed))
    stats: dict[str, Any] = {}
    for profile in profiles:
        rows = costs[costs["cost_profile"] == profile].copy()
        profile_stats: dict[str, Any] = {
            "seed_count": int(rows["seed"].nunique()),
            "metrics": {},
        }
        for metric in ["total_return_pct", "sharpe_ratio", "max_drawdown_pct"]:
            values = pd.to_numeric(rows[metric], errors="coerce").dropna().to_numpy(dtype=np.float64)
            samples = _bootstrap_means(values, rng=rng, n_bootstrap=n_bootstrap)
            profile_stats["metrics"][metric] = {
                "observed": _observed_distribution(values),
                "bootstrap_mean_ci": _percentile_interval(samples),
                "bootstrap_probability_mean_ge_zero": _probability(samples >= 0.0),
            }
        stats[profile] = profile_stats
    return stats


def build_gate_results(
    costs: pd.DataFrame,
    profile_stats: dict[str, Any],
    *,
    min_statistical_seeds: int,
    operating_profile: str,
    severe_profile: str,
    min_bootstrap_probability: float,
    min_operating_return_pct: float,
    min_operating_sharpe: float,
    max_operating_drawdown_pct: float,
    min_severe_return_pct: float,
    min_severe_sharpe: float,
    max_severe_drawdown_pct: float,
    seed: int,
    n_bootstrap: int,
    deflated_sharpe_probability: float | None,
    min_deflated_sharpe_probability: float,
    backtest_overfit_probability: float | None,
    max_backtest_overfit_probability: float,
    require_selection_bias_diagnostics: bool,
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
            name="min_statistical_seed_count",
            passed=len(seeds) >= int(min_statistical_seeds),
            blocking=True,
            observed={"seed_count": len(seeds), "seeds": seeds},
            threshold={">=": int(min_statistical_seeds)},
            reason="Statistical promotion needs more independent seeds than a cheap screen.",
        ),
        GateResult(
            name="required_profiles_present",
            passed=all(count == len(seeds) and len(seeds) > 0 for count in profile_seed_counts.values()),
            blocking=True,
            observed=profile_seed_counts,
            threshold={profile: len(seeds) for profile in required_profiles},
            reason="Every seed must have all required cost profiles.",
        ),
        GateResult(
            name="metrics_complete",
            passed=_metrics_complete(required_rows),
            blocking=True,
            observed=_missing_metric_counts(required_rows),
            threshold={"missing_required_metric_values": 0},
            reason="Statistical gates require complete return, Sharpe, and drawdown metrics.",
        ),
    ]
    gates.extend(
        [
            _bootstrap_probability_gate(
                profile_stats,
                profile=operating_profile,
                metric="total_return_pct",
                threshold=min_operating_return_pct,
                min_probability=min_bootstrap_probability,
                costs=costs,
                seed=seed,
                n_bootstrap=n_bootstrap,
                name="operating_bootstrap_return_probability",
                reason="Operating-profile bootstrapped mean return must clear the profitability threshold with enough probability.",
            ),
            _bootstrap_probability_gate(
                profile_stats,
                profile=operating_profile,
                metric="sharpe_ratio",
                threshold=min_operating_sharpe,
                min_probability=min_bootstrap_probability,
                costs=costs,
                seed=seed + 1,
                n_bootstrap=n_bootstrap,
                name="operating_bootstrap_sharpe_probability",
                reason="Operating-profile bootstrapped mean Sharpe must clear the threshold with enough probability.",
            ),
            _bootstrap_probability_gate(
                profile_stats,
                profile=operating_profile,
                metric="max_drawdown_pct",
                threshold=max_operating_drawdown_pct,
                min_probability=min_bootstrap_probability,
                costs=costs,
                seed=seed + 2,
                n_bootstrap=n_bootstrap,
                name="operating_bootstrap_drawdown_probability",
                reason="Operating-profile bootstrapped mean drawdown must stay within the configured limit.",
            ),
            _bootstrap_probability_gate(
                profile_stats,
                profile=severe_profile,
                metric="total_return_pct",
                threshold=min_severe_return_pct,
                min_probability=min_bootstrap_probability,
                costs=costs,
                seed=seed + 3,
                n_bootstrap=n_bootstrap,
                name="severe_bootstrap_return_probability",
                reason="Severe-profile bootstrapped mean return must clear the survivability threshold with enough probability.",
            ),
            _bootstrap_probability_gate(
                profile_stats,
                profile=severe_profile,
                metric="sharpe_ratio",
                threshold=min_severe_sharpe,
                min_probability=min_bootstrap_probability,
                costs=costs,
                seed=seed + 4,
                n_bootstrap=n_bootstrap,
                name="severe_bootstrap_sharpe_probability",
                reason="Severe-profile bootstrapped mean Sharpe must clear the threshold with enough probability.",
            ),
            _bootstrap_probability_gate(
                profile_stats,
                profile=severe_profile,
                metric="max_drawdown_pct",
                threshold=max_severe_drawdown_pct,
                min_probability=min_bootstrap_probability,
                costs=costs,
                seed=seed + 5,
                n_bootstrap=n_bootstrap,
                name="severe_bootstrap_drawdown_probability",
                reason="Severe-profile bootstrapped mean drawdown must stay within the configured limit.",
            ),
            _deflated_sharpe_gate(
                value=deflated_sharpe_probability,
                threshold=min_deflated_sharpe_probability,
                required=require_selection_bias_diagnostics,
            ),
            _pbo_gate(
                value=backtest_overfit_probability,
                threshold=max_backtest_overfit_probability,
                required=require_selection_bias_diagnostics,
            ),
        ]
    )
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
    required = {"seed", "cost_profile", "total_return_pct", "sharpe_ratio", "max_drawdown_pct"}
    missing = sorted(required - set(data.columns))
    if missing:
        raise ValueError(f"Missing required cost-stress columns: {', '.join(missing)}")
    for column in ["seed", "total_return_pct", "sharpe_ratio", "max_drawdown_pct"]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    return data


def _bootstrap_means(values: np.ndarray, *, rng: np.random.Generator, n_bootstrap: int) -> np.ndarray:
    clean = values[np.isfinite(values)]
    if clean.size == 0 or n_bootstrap <= 0:
        return np.asarray([], dtype=np.float64)
    indices = rng.integers(0, clean.size, size=(int(n_bootstrap), clean.size))
    return clean[indices].mean(axis=1)


def _observed_distribution(values: np.ndarray) -> dict[str, float | None]:
    clean = values[np.isfinite(values)]
    if clean.size == 0:
        return {"mean": None, "median": None, "min": None, "max": None}
    return {
        "mean": _finite_or_none(clean.mean()),
        "median": _finite_or_none(np.median(clean)),
        "min": _finite_or_none(clean.min()),
        "max": _finite_or_none(clean.max()),
    }


def _percentile_interval(values: np.ndarray | list[float]) -> dict[str, float | None]:
    clean = np.asarray(values, dtype=np.float64)
    clean = clean[np.isfinite(clean)]
    if clean.size == 0:
        return {"p2_5": None, "median": None, "p97_5": None}
    return {
        "p2_5": _finite_or_none(np.percentile(clean, 2.5)),
        "median": _finite_or_none(np.percentile(clean, 50.0)),
        "p97_5": _finite_or_none(np.percentile(clean, 97.5)),
    }


def _probability(mask: np.ndarray) -> float | None:
    if mask.size == 0:
        return None
    return float(np.mean(mask))


def _bootstrap_probability_gate(
    profile_stats: dict[str, Any],
    *,
    profile: str,
    metric: str,
    threshold: float,
    min_probability: float,
    costs: pd.DataFrame,
    seed: int,
    n_bootstrap: int,
    name: str,
    reason: str,
) -> GateResult:
    probability = _bootstrap_probability_against_threshold(
        costs,
        profile=profile,
        metric=metric,
        threshold=threshold,
        seed=seed,
        n_bootstrap=n_bootstrap,
    )
    metric_values = _metric_values(profile_stats, profile, metric)
    probabilities = metric_values.setdefault("bootstrap_threshold_probabilities", {})
    if isinstance(probabilities, dict):
        probabilities[str(float(threshold))] = probability
    return GateResult(
        name=name,
        passed=probability is not None and probability >= float(min_probability),
        blocking=True,
        observed={
            "profile": profile,
            "metric": metric,
            "threshold": float(threshold),
            "bootstrap_probability": probability,
        },
        threshold={">=": float(min_probability)},
        reason=reason,
    )


def _bootstrap_probability_against_threshold(
    costs: pd.DataFrame,
    *,
    profile: str,
    metric: str,
    threshold: float,
    seed: int,
    n_bootstrap: int,
) -> float | None:
    rows = costs[costs["cost_profile"] == profile]
    values = pd.to_numeric(rows[metric], errors="coerce").dropna().to_numpy(dtype=np.float64)
    samples = _bootstrap_means(values, rng=np.random.default_rng(int(seed)), n_bootstrap=n_bootstrap)
    if samples.size == 0:
        return None
    return float(np.mean(samples >= float(threshold)))


def _metric_values(profile_stats: dict[str, Any], profile: str, metric: str) -> dict[str, Any]:
    profile_data = profile_stats.get(profile, {})
    if not isinstance(profile_data, dict):
        return {}
    metrics = profile_data.get("metrics", {})
    if not isinstance(metrics, dict):
        return {}
    metric_data = metrics.get(metric, {})
    return metric_data if isinstance(metric_data, dict) else {}


def _deflated_sharpe_gate(*, value: float | None, threshold: float, required: bool) -> GateResult:
    observed = _finite_or_none(value)
    return GateResult(
        name="deflated_sharpe_probability",
        passed=(not required and observed is None) or (observed is not None and observed >= float(threshold)),
        blocking=required,
        observed=observed,
        threshold={">=": float(threshold), "required": bool(required)},
        reason="Deflated Sharpe probability must be supplied from trial-count corrected statistics.",
    )


def _pbo_gate(*, value: float | None, threshold: float, required: bool) -> GateResult:
    observed = _finite_or_none(value)
    return GateResult(
        name="backtest_overfit_probability",
        passed=(not required and observed is None) or (observed is not None and observed <= float(threshold)),
        blocking=required,
        observed=observed,
        threshold={"<=": float(threshold), "required": bool(required)},
        reason="Backtest overfit probability must be supplied from CSCV/PBO diagnostics.",
    )


def _metrics_complete(rows: pd.DataFrame) -> bool:
    return all(count == 0 for count in _missing_metric_counts(rows).values())


def _missing_metric_counts(rows: pd.DataFrame) -> dict[str, int]:
    required = ["total_return_pct", "sharpe_ratio", "max_drawdown_pct"]
    missing: dict[str, int] = {}
    for column in required:
        if column not in rows.columns:
            missing[column] = int(len(rows))
            continue
        missing[column] = int(rows[column].isna().sum() + (rows[column].astype(str).str.strip() == "").sum())
    return missing


def _summary(status: str, blocking_failures: list[GateResult]) -> str:
    if status == "PASSED":
        return "RL candidate passed configured statistical gates."
    names = ", ".join(gate.name for gate in blocking_failures)
    return f"RL candidate failed statistical gates: {names}."


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except Exception:
        return None
    return number if math.isfinite(number) else None


def _finite_or_none(value: Any) -> float | None:
    return _as_float(value)


def main() -> None:
    output_dir = evaluate_statistical_gates(build_parser().parse_args())
    print(output_dir)


if __name__ == "__main__":
    main()
