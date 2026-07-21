"""RL backtest behavior diagnostics for policy-vs-execution analysis."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


EPISODE_STEM = "backtest_episode_rl_only_live_like_dynamic_weighted.parquet"
METRICS_STEM = "backtest_metrics.csv"


def read_backtest_metrics(path: Path) -> dict[str, float | str | None]:
    metrics_path = Path(path)
    if not metrics_path.exists():
        return {}
    raw = pd.read_csv(metrics_path, index_col=0)["value"].to_dict()
    return {str(key): _parse_scalar(value) for key, value in raw.items()}


def load_backtest_episode(session_dir: Path) -> pd.DataFrame:
    session = Path(session_dir)
    episode_path = session / EPISODE_STEM
    if not episode_path.exists():
        candidates = sorted(session.glob("backtest_episode_*.parquet"))
        if not candidates:
            raise FileNotFoundError(f"No backtest episode parquet found under {session}")
        episode_path = candidates[0]
    return pd.read_parquet(episode_path)


def summarize_episode_behavior(
    *,
    label: str,
    episode_df: pd.DataFrame,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one compact row describing realized and proposed RL behavior."""
    metrics = metrics or {}
    row: dict[str, Any] = {
        "label": label,
        "rows": int(len(episode_df)),
        "start": str(episode_df.index[0]) if len(episode_df) else "",
        "end": str(episode_df.index[-1]) if len(episode_df) else "",
    }
    for key in (
        "total_return_pct",
        "sharpe_ratio",
        "max_drawdown_pct",
        "profit_factor",
        "total_trades_count",
        "trade_count",
        "time_in_market_pct",
    ):
        row[key] = metrics.get(key)

    realized_risk = _sum_columns(episode_df, ("btc_weight", "eth_weight"))
    target_risk = _sum_columns(episode_df, ("target_btc_weight", "target_eth_weight"))
    rl_risk = _sum_columns(episode_df, ("rl_btc_weight", "rl_eth_weight"))
    row.update(_series_stats("realized_risk_on", realized_risk))
    row.update(_series_stats("target_risk_on", target_risk))
    row.update(_series_stats("rl_risk_on", rl_risk))
    if realized_risk is not None and target_risk is not None:
        row.update(_series_stats("risk_tracking_gap", (target_risk - realized_risk).abs()))

    for column in (
        "cash_weight",
        "target_cash_weight",
        "rl_cash_weight",
        "ppo_cash_weight",
        "sac_cash_weight",
        "turnover",
        "transaction_cost",
        "raw_action_delta",
    ):
        if column in episode_df:
            row.update(_series_stats(column, episode_df[column]))
            row[f"{column}_sum"] = _finite_or_none(pd.to_numeric(episode_df[column], errors="coerce").sum())

    for column in ("risk_exit_applied", "risk_governor_active", "reentry_locked"):
        if column in episode_df:
            bools = episode_df[column].fillna(False).astype(bool)
            row[f"{column}_rate"] = float(bools.mean()) if len(bools) else 0.0
            row[f"{column}_count"] = int(bools.sum())

    if "risk_exit_reason" in episode_df and "risk_exit_applied" in episode_df:
        exit_rows = episode_df[episode_df["risk_exit_applied"].fillna(False).astype(bool)]
        row["risk_exit_reason_counts_json"] = json.dumps(
            exit_rows["risk_exit_reason"].fillna("").astype(str).value_counts().to_dict(),
            sort_keys=True,
        )
        row["first_risk_exit_at"] = str(exit_rows.index[0]) if len(exit_rows) else ""
        row["last_risk_exit_at"] = str(exit_rows.index[-1]) if len(exit_rows) else ""

    return row


def build_monthly_behavior_table(*, label: str, episode_df: pd.DataFrame) -> pd.DataFrame:
    if episode_df.empty:
        return pd.DataFrame()
    frame = episode_df.copy()
    frame["label"] = label
    month_index = frame.index
    if isinstance(month_index, pd.DatetimeIndex) and month_index.tz is not None:
        month_index = month_index.tz_convert(None)
    frame["month"] = month_index.to_period("M").astype(str)
    frame["realized_risk_on"] = _sum_columns(frame, ("btc_weight", "eth_weight"))
    frame["target_risk_on"] = _sum_columns(frame, ("target_btc_weight", "target_eth_weight"))
    aggregations: dict[str, Any] = {
        "portfolio_value_last": ("portfolio_value", "last"),
        "rows": ("portfolio_value", "size"),
        "realized_risk_on_mean": ("realized_risk_on", "mean"),
        "target_risk_on_mean": ("target_risk_on", "mean"),
        "turnover_sum": ("turnover", "sum"),
    }
    if "cash_weight" in frame:
        aggregations["cash_weight_mean"] = ("cash_weight", "mean")
    if "risk_exit_applied" in frame:
        aggregations["risk_exit_rate"] = ("risk_exit_applied", "mean")
    out = frame.groupby(["label", "month"], as_index=False).agg(**aggregations)
    return out


def build_behavior_diagnostics(
    runs: dict[str, Path],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary_rows: list[dict[str, Any]] = []
    monthly_frames: list[pd.DataFrame] = []
    for label, session_dir in runs.items():
        episode = load_backtest_episode(session_dir)
        metrics = read_backtest_metrics(Path(session_dir) / METRICS_STEM)
        summary_rows.append(
            summarize_episode_behavior(label=label, episode_df=episode, metrics=metrics)
        )
        monthly_frames.append(build_monthly_behavior_table(label=label, episode_df=episode))
    monthly = pd.concat(monthly_frames, ignore_index=True) if monthly_frames else pd.DataFrame()
    return pd.DataFrame(summary_rows), monthly


def write_behavior_diagnostics(
    *,
    runs: dict[str, Path],
    output_dir: Path,
) -> dict[str, Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary, monthly = build_behavior_diagnostics(runs)
    summary_path = out / "rl_behavior_summary.csv"
    monthly_path = out / "rl_behavior_monthly.csv"
    summary.to_csv(summary_path, index=False)
    monthly.to_csv(monthly_path, index=False)
    return {"summary": summary_path, "monthly": monthly_path}


def _sum_columns(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.Series | None:
    if not set(columns).issubset(frame.columns):
        return None
    return sum(pd.to_numeric(frame[column], errors="coerce").fillna(0.0) for column in columns)


def _series_stats(prefix: str, values: pd.Series | None) -> dict[str, float | None]:
    if values is None:
        return {}
    series = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if series.empty:
        return {
            f"{prefix}_mean": None,
            f"{prefix}_p50": None,
            f"{prefix}_p95": None,
        }
    return {
        f"{prefix}_mean": float(series.mean()),
        f"{prefix}_p50": float(series.quantile(0.50)),
        f"{prefix}_p95": float(series.quantile(0.95)),
    }


def _parse_scalar(value: Any) -> float | str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        numeric = float(text)
    except ValueError:
        return text
    return numeric if np.isfinite(numeric) else None


def _finite_or_none(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None
