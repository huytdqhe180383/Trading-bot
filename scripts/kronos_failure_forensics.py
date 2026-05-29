"""
Deterministic Kronos failure forensics.

Compares rl_only vs rl_kronos runs step-by-step and produces attribution artifacts.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _find_latest_decision_file(day_dir: Path, pipeline: str) -> Path:
    pattern = f"trade_decisions_{pipeline}_live_like_dynamic_weighted.csv"
    files = list(day_dir.rglob(pattern))
    if not files:
        raise FileNotFoundError(f"No decision logs found for pipeline={pipeline} under {day_dir}")
    return max(files, key=lambda p: p.stat().st_mtime)


def _load_episode_from_decisions(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "timestamp" not in df.columns:
        raise ValueError(f"Missing timestamp column in {path}")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values("timestamp").reset_index(drop=True)


def _label_mechanism(row: pd.Series) -> str:
    if bool(row.get("fusion_constraint_clipped_kr", False)):
        return "constraint_clipped"
    delta_risk_on = float(row.get("delta_target_btc_weight", 0.0)) + float(row.get("delta_target_eth_weight", 0.0))
    if delta_risk_on < -0.01:
        return "kronos_de_risk"
    if delta_risk_on > 0.01:
        return "kronos_re_risk"
    if float(row.get("delta_turnover", 0.0)) > 0.0 and float(row.get("next_gap_change", 0.0)) < 0.0:
        return "high_churn_no_gain"
    return "unchanged"


def run_forensics(
    *,
    rl_only_path: Path,
    rl_kronos_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    rl = _load_episode_from_decisions(rl_only_path)
    kr = _load_episode_from_decisions(rl_kronos_path)

    merged = rl.merge(kr, on="timestamp", suffixes=("_rl", "_kr"))
    if merged.empty:
        raise RuntimeError("Merged decision frame is empty.")

    base_cols = [
        "portfolio_value",
        "target_btc_weight",
        "target_eth_weight",
        "target_cash_weight",
        "turnover",
        "transaction_cost",
    ]
    for col in base_cols:
        merged[f"delta_{col}"] = merged[f"{col}_kr"] - merged[f"{col}_rl"]

    merged["nav_gap"] = merged["portfolio_value_kr"] - merged["portfolio_value_rl"]
    merged["nav_gap_pct"] = (merged["portfolio_value_kr"] / merged["portfolio_value_rl"] - 1.0) * 100.0
    merged["next_gap_change"] = merged["nav_gap"].shift(-1) - merged["nav_gap"]
    merged["month"] = merged["timestamp"].dt.to_period("M").astype(str)
    merged["mechanism_label"] = merged.apply(_label_mechanism, axis=1)

    output_dir.mkdir(parents=True, exist_ok=True)
    merged.to_csv(output_dir / "kronos_step_attribution.csv", index=False)

    monthly = (
        merged.dropna(subset=["next_gap_change"])
        .groupby("month", as_index=False)
        .agg(
            nav_gap_change_sum=("next_gap_change", "sum"),
            kronos_underperform_hours=("next_gap_change", lambda s: float((s < 0).sum())),
            mean_delta_target_cash=("delta_target_cash_weight", "mean"),
            mean_delta_turnover=("delta_turnover", "mean"),
        )
    )
    monthly.to_csv(output_dir / "kronos_monthly_gap_accumulation.csv", index=False)

    mechanism = (
        merged.dropna(subset=["next_gap_change"])
        .groupby("mechanism_label", as_index=False)
        .agg(
            steps=("mechanism_label", "count"),
            gap_change_sum=("next_gap_change", "sum"),
            negative_events=("next_gap_change", lambda s: float((s < 0).sum())),
            mean_delta_turnover=("delta_turnover", "mean"),
        )
        .sort_values("gap_change_sum")
    )
    mechanism.to_csv(output_dir / "kronos_mechanism_summary.csv", index=False)

    top_loss_cols = [
        "timestamp",
        "next_gap_change",
        "mechanism_label",
        "delta_target_btc_weight",
        "delta_target_eth_weight",
        "delta_target_cash_weight",
        "delta_turnover",
        "delta_transaction_cost",
        "kronos_btc_tilt_kr",
        "kronos_eth_tilt_kr",
        "kronos_btc_directional_score_kr",
        "kronos_eth_directional_score_kr",
        "kronos_btc_confidence_kr",
        "kronos_eth_confidence_kr",
        "risk_governor_reason_rl",
        "risk_governor_reason_kr",
        "fusion_post_constraint_btc_weight_kr",
        "fusion_post_constraint_eth_weight_kr",
        "fusion_post_constraint_cash_weight_kr",
    ]
    top_loss = merged.dropna(subset=["next_gap_change"]).nsmallest(100, "next_gap_change")
    top_loss[[c for c in top_loss_cols if c in top_loss.columns]].to_csv(
        output_dir / "kronos_top_loss_events.csv", index=False
    )

    total_steps = int(len(merged))
    changed_steps = int(
        (
            merged["delta_target_btc_weight"].abs()
            + merged["delta_target_eth_weight"].abs()
            + merged["delta_target_cash_weight"].abs()
        ).gt(1e-9).sum()
    )
    risk_delta = merged["delta_target_btc_weight"] + merged["delta_target_eth_weight"]
    lower_risk_on_rate = float((risk_delta < -1e-6).mean())

    summary = {
        "total_steps": total_steps,
        "kronos_changed_steps": changed_steps,
        "kronos_changed_step_rate": float(changed_steps / max(total_steps, 1)),
        "avg_delta_target_cash_weight": float(merged["delta_target_cash_weight"].mean()),
        "lower_risk_on_rate": lower_risk_on_rate,
        "turnover_delta_pct": float(
            (merged["turnover_kr"].sum() / max(merged["turnover_rl"].sum(), 1e-9) - 1.0) * 100.0
        ),
        "transaction_cost_delta_pct": float(
            (merged["transaction_cost_kr"].sum() / max(merged["transaction_cost_rl"].sum(), 1e-9) - 1.0) * 100.0
        ),
        "final_nav_gap_pct": float(merged.iloc[-1]["nav_gap_pct"]),
        "final_nav_gap_abs": float(merged.iloc[-1]["nav_gap"]),
        "nav_gap_reconstructed_abs": float(
            merged.iloc[0]["nav_gap"] + merged["next_gap_change"].dropna().sum()
        ),
        "nav_gap_reconstruction_error_abs": float(
            merged.iloc[-1]["nav_gap"] - (merged.iloc[0]["nav_gap"] + merged["next_gap_change"].dropna().sum())
        ),
        "monthly_underperform_count": int((monthly["nav_gap_change_sum"] < 0).sum()),
        "monthly_total_count": int(len(monthly)),
        "rl_only_path": str(rl_only_path),
        "rl_kronos_path": str(rl_kronos_path),
    }
    (output_dir / "kronos_forensics_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return summary


def _write_report(*, report_path: Path, summary: dict[str, Any], output_dir: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    text = f"""# Kronos Failure Forensics (MA Ignored)

Date: {datetime.now().strftime("%Y-%m-%d")}

## Locked Findings

- Kronos changed targets on `{summary["kronos_changed_steps"]}/{summary["total_steps"]}` steps (`{summary["kronos_changed_step_rate"]:.2%}`).
- Average target cash shift vs RL-only: `{summary["avg_delta_target_cash_weight"]:.4f}`.
- Kronos reduced risk-on exposure on `{summary["lower_risk_on_rate"]:.2%}` of steps.
- Turnover delta vs RL-only: `{summary["turnover_delta_pct"]:.2f}%`.
- Transaction cost delta vs RL-only: `{summary["transaction_cost_delta_pct"]:.2f}%`.
- Final NAV gap (kronos vs rl_only): `{summary["final_nav_gap_pct"]:.2f}%`.
- Months with negative gap accumulation: `{summary["monthly_underperform_count"]}/{summary["monthly_total_count"]}`.

## Artifacts

- `kronos_step_attribution.csv`
- `kronos_monthly_gap_accumulation.csv`
- `kronos_mechanism_summary.csv`
- `kronos_top_loss_events.csv`
- `kronos_forensics_summary.json`

Output directory: `{output_dir}`
"""
    report_path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic Kronos failure forensics.")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--results-root", default="results")
    parser.add_argument("--report-root", default="report")
    parser.add_argument("--rl-only-path", default="")
    parser.add_argument("--rl-kronos-path", default="")
    args = parser.parse_args()

    results_root = Path(args.results_root)
    report_root = Path(args.report_root)
    day_dir = results_root / "daily" / args.date
    if not day_dir.exists():
        raise FileNotFoundError(f"Missing results day directory: {day_dir}")

    rl_only_path = Path(args.rl_only_path) if args.rl_only_path else _find_latest_decision_file(day_dir, "rl_only")
    rl_kronos_path = (
        Path(args.rl_kronos_path) if args.rl_kronos_path else _find_latest_decision_file(day_dir, "rl_kronos")
    )

    outdir = day_dir / "kronos_failure_forensics"
    summary = run_forensics(
        rl_only_path=rl_only_path,
        rl_kronos_path=rl_kronos_path,
        output_dir=outdir,
    )
    report_path = report_root / "daily" / args.date / "kronos_failure_forensics.md"
    _write_report(report_path=report_path, summary=summary, output_dir=outdir)
    print(f"Forensics complete -> {outdir}")
    print(f"Report -> {report_path}")


if __name__ == "__main__":
    main()
