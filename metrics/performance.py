"""
Metrics Layer – performance.py
================================
Computes all quantitative performance metrics for a given
portfolio value series.  Covers profitability, risk, and
operational categories as agreed in the project plan.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")    # headless – no display required
import matplotlib.pyplot as plt
import seaborn as sns

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import INITIAL_CAPITAL, KPI_TARGETS


# ─────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────

def _returns(nav: pd.Series) -> pd.Series:
    return nav.pct_change().dropna()


def _log_returns(nav: pd.Series) -> pd.Series:
    return np.log(nav / nav.shift(1)).dropna()


def _drawdown_series(nav: pd.Series) -> pd.Series:
    """Compute running drawdown from peak."""
    roll_max = nav.cummax()
    return (nav - roll_max) / roll_max


# ─────────────────────────────────────────────
# CORE METRICS
# ─────────────────────────────────────────────

def _total_return(nav: pd.Series, initial: float) -> float:
    return (nav.iloc[-1] / initial - 1.0) * 100.0


def _annualised_return(nav: pd.Series, periods_per_year: int = 8760) -> float:
    """Annualised return assuming hourly data (8760 h/yr)."""
    n = len(nav)
    if n < 2:
        return 0.0
    total = nav.iloc[-1] / nav.iloc[0]
    return (total ** (periods_per_year / n) - 1.0) * 100.0


def _sharpe_ratio(nav: pd.Series, periods_per_year: int = 8760, rf: float = 0.0) -> float:
    r = _log_returns(nav)
    excess = r - rf / periods_per_year
    if excess.std() == 0:
        return 0.0
    return float((excess.mean() / excess.std()) * np.sqrt(periods_per_year))


def _sortino_ratio(nav: pd.Series, periods_per_year: int = 8760, rf: float = 0.0) -> float:
    r = _log_returns(nav)
    excess = r - rf / periods_per_year
    downside = excess[excess < 0]
    if len(downside) == 0 or downside.std() == 0:
        return 0.0
    return float((excess.mean() / downside.std()) * np.sqrt(periods_per_year))


def _max_drawdown(nav: pd.Series) -> float:
    return float(_drawdown_series(nav).min() * 100.0)


def _recovery_factor(nav: pd.Series, initial: float) -> float:
    tr = _total_return(nav, initial)
    mdd = abs(_max_drawdown(nav))
    return float(tr / mdd) if mdd > 0 else float("inf")


def _ulcer_index(nav: pd.Series) -> float:
    """Quadratic mean of drawdowns (measures depth and duration of DD)."""
    dd = _drawdown_series(nav) * 100
    return float(np.sqrt((dd**2).mean()))


def _calmar_ratio(nav: pd.Series) -> float:
    ann_ret = _annualised_return(nav)
    mdd = abs(_max_drawdown(nav))
    return ann_ret / mdd if mdd > 0 else 0.0


def _average_drawdown_duration(nav: pd.Series) -> float:
    """Mean number of steps spent in drawdown."""
    dd = _drawdown_series(nav)
    in_dd = (dd < 0).astype(int)
    # Count contiguous drawdown periods
    durations = []
    current   = 0
    for val in in_dd:
        if val:
            current += 1
        elif current:
            durations.append(current)
            current = 0
    if current:
        durations.append(current)
    return float(np.mean(durations)) if durations else 0.0


def _win_rate(nav: pd.Series) -> float:
    """% of steps with positive return."""
    r = _returns(nav)
    return float((r > 0).sum() / len(r) * 100.0) if len(r) > 0 else 0.0


def _profit_factor(nav: pd.Series) -> float:
    r = _returns(nav)
    gross_profit = r[r > 0].sum()
    gross_loss   = abs(r[r < 0].sum())
    return float(gross_profit / gross_loss) if gross_loss > 0 else float("inf")


def _expectancy(nav: pd.Series) -> float:
    """Average expected return per step."""
    return float(_returns(nav).mean() * 100.0)


def _avg_win_loss_ratio(nav: pd.Series) -> float:
    r = _returns(nav)
    avg_win  = r[r > 0].mean() if (r > 0).any() else 0.0
    avg_loss = abs(r[r < 0].mean()) if (r < 0).any() else 1e-9
    return float(avg_win / avg_loss) if avg_loss > 0 else 0.0


def _time_in_market(nav: pd.Series, threshold: float = 0.0) -> float:
    """
    % of steps where the portfolio had non-trivial exposure to assets.
    Proxy: steps with positive log-return (rough indicator of market exposure).
    """
    r = _log_returns(nav)
    exposed = (r > threshold).sum()
    return float(exposed / len(r) * 100.0) if len(r) > 0 else 0.0


def _information_ratio(nav: pd.Series, benchmark_nav: pd.Series | None = None) -> float:
    """
    Information Ratio vs a simple Buy-and-Hold benchmark.
    If no benchmark provided, we approximate using the first asset's cumulative
    return (assumes the portfolio's initial holdings = 1 unit of BTC).
    Requires a benchmark_nav of same length.
    """
    if benchmark_nav is None or len(benchmark_nav) != len(nav):
        return float("nan")
    active_returns = _log_returns(nav) - _log_returns(benchmark_nav)
    if active_returns.std() == 0:
        return 0.0
    return float(active_returns.mean() / active_returns.std() * np.sqrt(8760))


# ─────────────────────────────────────────────
# COMPOUND REPORT
# ─────────────────────────────────────────────

def compute_metrics(
    nav: pd.Series,
    initial_capital: float = INITIAL_CAPITAL,
    benchmark_nav: pd.Series | None = None,
    trades_count: int | None = None,
) -> dict[str, float]:
    """Compute the full suite of performance metrics."""
    metrics = {
        # Profitability
        "total_return_pct":      _total_return(nav, initial_capital),
        "annualised_return_pct": _annualised_return(nav),
        "win_rate_pct":          _win_rate(nav),
        "profit_factor":         _profit_factor(nav),
        "expectancy_pct":        _expectancy(nav),
        "avg_win_loss_ratio":    _avg_win_loss_ratio(nav),
        # Risk
        "max_drawdown_pct":      _max_drawdown(nav),
        "sharpe_ratio":          _sharpe_ratio(nav),
        "sortino_ratio":         _sortino_ratio(nav),
        "calmar_ratio":          _calmar_ratio(nav),
        "recovery_factor":       _recovery_factor(nav, initial_capital),        
        "ulcer_index":           _ulcer_index(nav),
        "avg_drawdown_duration_steps": _average_drawdown_duration(nav),
        # Operational
        "time_in_market_pct":    _time_in_market(nav),
        "information_ratio":     _information_ratio(nav, benchmark_nav),        
    }
    if trades_count is not None:
        metrics["total_trades_count"] = float(trades_count)
    return metrics
    print("\n" + "=" * 52)
    print("  BTC/ETH ENSEMBLE – PERFORMANCE REPORT")
    print("=" * 52)

    sections = {
        "PROFITABILITY": [
            "total_return_pct", "annualised_return_pct",
            "win_rate_pct", "profit_factor",
            "expectancy_pct", "avg_win_loss_ratio",
        ],
        "RISK": [
            "max_drawdown_pct", "sharpe_ratio",
            "sortino_ratio", "calmar_ratio",
            "recovery_factor", "ulcer_index",
            "avg_drawdown_duration_steps",
        ],
        "OPERATIONAL": [
            "time_in_market_pct", "information_ratio",
        ],
    }

    for section, keys in sections.items():
        print(f"\n  {section}")
        print("  " + "-" * 48)
        for k in keys:
            v = metrics.get(k, float("nan"))
            label = k.replace("_", " ").title()
            if isinstance(v, float) and not np.isnan(v):
                print(f"    {label:<40} {v:>8.4f}")
            else:
                print(f"    {label:<40} {'N/A':>8}")

    print("=" * 52 + "\n")


# ─────────────────────────────────────────────
# VISUALISATION
# ─────────────────────────────────────────────

def plot_kpi_radar(metrics: dict[str, float], targets: dict[str, float] = KPI_TARGETS, save_path: Path | None = None) -> None:
    """Plot a radar chart comparing achieved metrics against targets."""
    # Only keep keys that exist in targets
    labels = list(targets.keys())
    # Normalise achieved metrics relative to target (capped at 2.0 or 200% for visualisation)
    # Special case: Max Drawdown (we want it to be smaller, so target / achieved)
    norm_achieved = []
    norm_targets = []
    
    for k in labels:
        val = metrics.get(k, 0.0)
        tgt = targets[k]
        
        if k == "max_drawdown_pct":
            # Target is -30.0%. Achieved max_dd is e.g. -15.0%. 
            # We want -15 to be "better" (larger radius) than -30.
            # Convert to positive absolute values. target = 30. attained = 15.
            # Score = (30 / max(15, 1)) = 2.0 (Double the target performance)
            val_abs, tgt_abs = abs(val), abs(tgt)
            score = tgt_abs / max(val_abs, 1e-6)
            norm_achieved.append(min(score, 2.0))
        else:
            # Score = 1.0 means hit target. Score > 1.0 exceeded.
            score = val / max(tgt, 1e-6)
            norm_achieved.append(min(score, 2.0))
            
        norm_targets.append(1.0)  # Target ring is always 1.0

    # Number of variables
    num_vars = len(labels)
    # Compute angle for each axis
    angles = np.linspace(0, 2 * np.pi, num_vars, endpoint=False).tolist()
    # Make radar circular by appending the first value to end
    norm_achieved += norm_achieved[:1]
    norm_targets += norm_targets[:1]
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
    
    # Plot Achieved
    ax.plot(angles, norm_achieved, color="#00c8ff", linewidth=2, label="Agent Achieved")
    ax.fill(angles, norm_achieved, color="#00c8ff", alpha=0.25)
    
    # Plot Target
    ax.plot(angles, norm_targets, color="#ff7f0e", linewidth=2, linestyle="--", label="Target KPI")
    
    # Labels
    clean_labels = [lbl.replace("_", " ").title() for lbl in labels]
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(clean_labels, size=10, weight="bold")
    
    # Remove y-tick labels for cleaner look
    ax.set_yticklabels([])
    ax.legend(loc='upper right', bbox_to_anchor=(0.1, 0.1))
    ax.set_title("KPI Target Attainment Analysis", size=15, weight="bold", pad=20)
    
    if save_path:
        plt.savefig(str(save_path), dpi=150, bbox_inches="tight")
        print(f"Radar chart saved -> {save_path}")
    plt.close()


def plot_equity_curve(
    nav: pd.Series,
    benchmark_nav: pd.Series | None = None,
    save_path: Path | None = None,
) -> None:
    """Plot NAV vs. Buy-and-Hold benchmark (if provided)."""
    sns.set_theme(style="darkgrid")
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True,
                             gridspec_kw={"height_ratios": [3, 1]})

    # ── Equity curve ──────────────────────────────────────────────────────
    axes[0].plot(nav.index, nav.values, label="Ensemble Agent", color="#00c8ff", linewidth=1.5)
    if benchmark_nav is not None:
        axes[0].plot(
            benchmark_nav.index, benchmark_nav.values,
            label="Buy & Hold BTC", color="#ff7f0e", linewidth=1.2, linestyle="--"
        )
    axes[0].set_title("Portfolio NAV vs Benchmark", fontsize=14)
    axes[0].set_ylabel("Portfolio Value ($)")
    axes[0].legend()

    # ── Drawdown chart ────────────────────────────────────────────────────
    dd = _drawdown_series(nav) * 100
    axes[1].fill_between(dd.index, dd.values, 0, color="#e74c3c", alpha=0.5, label="Drawdown %")
    axes[1].set_ylabel("Drawdown (%)")
    axes[1].set_xlabel("Date")
    axes[1].legend()

    plt.tight_layout()
    if save_path:
        plt.savefig(str(save_path), dpi=150)
        print(f"Equity curve saved -> {save_path}")
    plt.close()


def plot_ensemble_method_comparison(
    comparison_df: pd.DataFrame,
    equity_curves: dict[str, pd.Series],
    save_path: Path | None = None,
) -> list[str]:
    """Plot equity curves and summary metrics for every compared ensemble method."""
    required = {"method", "total_return_pct", "sharpe_ratio", "max_drawdown_pct"}
    missing = required.difference(comparison_df.columns)
    if missing:
        raise ValueError(f"comparison_df is missing required columns: {sorted(missing)}")

    methods = [str(method) for method in comparison_df["method"].tolist()]
    sns.set_theme(style="darkgrid")
    fig, axes = plt.subplots(2, 1, figsize=(15, 10), gridspec_kw={"height_ratios": [3, 2]})

    palette = sns.color_palette("tab10", n_colors=max(len(methods), 1))
    color_by_method = dict(zip(methods, palette))

    for method in methods:
        curve = equity_curves.get(method)
        if curve is None or curve.empty:
            continue
        axes[0].plot(
            curve.index,
            curve.values,
            label=method,
            linewidth=1.5,
            color=color_by_method[method],
        )
    axes[0].set_title("Ensemble Method Equity Curves")
    axes[0].set_ylabel("Portfolio Value ($)")
    axes[0].legend(loc="best")

    x = np.arange(len(methods))
    width = 0.25
    axes[1].bar(
        x - width,
        comparison_df["total_return_pct"].astype(float),
        width,
        label="Return %",
        color="#2ca02c",
    )
    axes[1].bar(
        x,
        comparison_df["sharpe_ratio"].astype(float),
        width,
        label="Sharpe",
        color="#1f77b4",
    )
    axes[1].bar(
        x + width,
        comparison_df["max_drawdown_pct"].astype(float),
        width,
        label="Max DD %",
        color="#d62728",
    )
    axes[1].axhline(0, color="#222222", linewidth=0.8)
    axes[1].set_title("Method Metrics")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(methods, rotation=15, ha="right")
    axes[1].legend(loc="best")

    fig.tight_layout()
    if save_path:
        plt.savefig(str(save_path), dpi=150, bbox_inches="tight")
        print(f"Ensemble method comparison plot saved -> {save_path}")
    plt.close(fig)
    return methods
