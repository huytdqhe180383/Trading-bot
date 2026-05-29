"""Deterministic post-policy risk overlays for champion backtest evaluation."""

from __future__ import annotations

from typing import Any

import numpy as np

from .risk_constraints import limit_turnover, normalize_weights


def apply_post_policy_overlay(
    *,
    target_weights: np.ndarray,
    current_weights: np.ndarray,
    realized_volatility: float,
    target_volatility: float,
    macro_trend: float,
    current_drawdown: float,
    persistence_turnover_cap: float,
    trend_gate_threshold: float = 0.0,
    trend_gate_multiplier: float = 0.75,
    drawdown_gate_threshold: float = -0.10,
    drawdown_gate_multiplier: float = 0.70,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Apply a low-cost de-risking overlay while preserving RL as the allocator."""
    current = normalize_weights(np.asarray(current_weights, dtype=np.float32), n_assets=len(current_weights) - 1)
    target = normalize_weights(np.asarray(target_weights, dtype=np.float32), n_assets=len(target_weights) - 1)
    adjusted = target.copy()

    target_volatility = max(float(target_volatility), 1e-9)
    realized_volatility = max(float(realized_volatility), 0.0)
    volatility_scale = min(1.0, target_volatility / max(realized_volatility, 1e-9))
    risk_on = float(adjusted[:-1].sum())
    adjusted[:-1] = adjusted[:-1] * volatility_scale
    adjusted[-1] = 1.0 - float(adjusted[:-1].sum())

    trend_gate_applied = False
    if float(macro_trend) < float(trend_gate_threshold):
        adjusted[:-1] = adjusted[:-1] * float(trend_gate_multiplier)
        adjusted[-1] = 1.0 - float(adjusted[:-1].sum())
        trend_gate_applied = True

    drawdown_gate_applied = False
    if float(current_drawdown) <= float(drawdown_gate_threshold):
        adjusted[:-1] = adjusted[:-1] * float(drawdown_gate_multiplier)
        adjusted[-1] = 1.0 - float(adjusted[:-1].sum())
        drawdown_gate_applied = True

    turnover_before = float(np.abs(adjusted[:-1] - current[:-1]).sum())
    if float(persistence_turnover_cap) > 0.0:
        adjusted = limit_turnover(
            current_weights=current,
            target_weights=adjusted,
            max_turnover=float(persistence_turnover_cap),
        )
    adjusted = normalize_weights(adjusted, n_assets=len(target_weights) - 1)
    turnover_after = float(np.abs(adjusted[:-1] - current[:-1]).sum())

    diagnostics = {
        "volatility_scale": float(volatility_scale),
        "turnover_before": turnover_before,
        "turnover_after": turnover_after,
        "trend_gate_applied": trend_gate_applied,
        "drawdown_gate_applied": drawdown_gate_applied,
        "risk_on_before": risk_on,
        "risk_on_after": float(adjusted[:-1].sum()),
    }
    return adjusted.astype(np.float32), diagnostics
