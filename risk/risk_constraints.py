"""Risk constraint utilities for BTC/ETH/USDT portfolio vectors."""

from __future__ import annotations

import numpy as np


def normalize_weights(weights: np.ndarray, n_assets: int) -> np.ndarray:
    arr = np.asarray(weights, dtype=np.float32).copy()
    expected = n_assets + 1
    if arr.shape[0] != expected:
        raise ValueError(f"Expected {expected} weights (assets + cash), got {arr.shape[0]}.")
    arr = np.clip(arr, 0.0, None)
    total = float(arr.sum())
    if total <= 0:
        arr = np.zeros(expected, dtype=np.float32)
        arr[-1] = 1.0
        return arr
    return (arr / total).astype(np.float32)


def apply_per_asset_cap(weights: np.ndarray, max_asset_weight: float) -> np.ndarray:
    out = np.asarray(weights, dtype=np.float32).copy()
    capped_assets = np.clip(out[:-1], 0.0, max_asset_weight)
    assets_sum = float(capped_assets.sum())
    if assets_sum > 1.0:
        capped_assets = capped_assets / assets_sum
        cash = 0.0
    else:
        cash = 1.0 - assets_sum
    return np.append(capped_assets, cash).astype(np.float32)


def compute_nav_scaled_max_asset_weight(
    nav: float,
    *,
    min_nav: float,
    max_nav: float,
    min_weight: float,
    max_weight: float,
) -> float:
    low_nav = float(min(min_nav, max_nav))
    high_nav = float(max(min_nav, max_nav))
    low_weight = float(min(min_weight, max_weight))
    high_weight = float(max(min_weight, max_weight))
    if nav <= low_nav:
        return low_weight
    if nav >= high_nav:
        return high_weight
    span = max(high_nav - low_nav, 1e-9)
    x = float((nav - low_nav) / span)
    smooth = x * x * (3.0 - 2.0 * x)
    return float(low_weight + (high_weight - low_weight) * smooth)


def apply_position_cap_mode(
    *,
    weights: np.ndarray,
    n_assets: int,
    nav: float,
    position_cap_mode: str,
    base_max_asset_weight: float,
    nav_scaled_cap_min_nav: float,
    nav_scaled_cap_max_nav: float,
    nav_scaled_cap_min_weight: float,
) -> tuple[np.ndarray, float]:
    normalized = normalize_weights(weights, n_assets)
    applied_cap = float(base_max_asset_weight)
    if str(position_cap_mode).strip().lower() == "smooth_nav":
        applied_cap = compute_nav_scaled_max_asset_weight(
            nav,
            min_nav=nav_scaled_cap_min_nav,
            max_nav=nav_scaled_cap_max_nav,
            min_weight=nav_scaled_cap_min_weight,
            max_weight=base_max_asset_weight,
        )
    capped = apply_per_asset_cap(normalized, max_asset_weight=applied_cap)
    return normalize_weights(capped, n_assets), float(applied_cap)


def apply_min_cash_floor(weights: np.ndarray, min_cash_floor: float) -> np.ndarray:
    out = np.asarray(weights, dtype=np.float32).copy()
    min_cash = float(np.clip(min_cash_floor, 0.0, 1.0))
    if out[-1] >= min_cash:
        return out

    deficit = min_cash - float(out[-1])
    asset_sum = float(out[:-1].sum())
    if asset_sum <= 0:
        out[:-1] = 0.0
        out[-1] = 1.0
        return out

    reduction_scale = max((asset_sum - deficit) / asset_sum, 0.0)
    out[:-1] = out[:-1] * reduction_scale
    out[-1] = 1.0 - float(out[:-1].sum())
    return out.astype(np.float32)


def limit_turnover(
    current_weights: np.ndarray,
    target_weights: np.ndarray,
    max_turnover: float,
) -> np.ndarray:
    current = np.asarray(current_weights, dtype=np.float32)
    target = np.asarray(target_weights, dtype=np.float32)

    turnover = float(np.abs(target[:-1] - current[:-1]).sum())
    if turnover <= max_turnover:
        return target.copy()
    if turnover <= 1e-9:
        return current.copy()

    scale = float(max_turnover / turnover)
    blended_assets = current[:-1] + (target[:-1] - current[:-1]) * scale
    cash = 1.0 - float(blended_assets.sum())
    return np.append(blended_assets, cash).astype(np.float32)


def apply_global_constraints(
    *,
    current_weights: np.ndarray,
    target_weights: np.ndarray,
    n_assets: int,
    max_asset_weight: float,
    min_cash_floor: float,
    max_turnover: float,
) -> np.ndarray:
    cur = normalize_weights(current_weights, n_assets)
    tgt = normalize_weights(target_weights, n_assets)
    tgt = apply_per_asset_cap(tgt, max_asset_weight=max_asset_weight)
    tgt = apply_min_cash_floor(tgt, min_cash_floor=min_cash_floor)
    tgt = normalize_weights(tgt, n_assets)
    constrained = limit_turnover(cur, tgt, max_turnover=max_turnover)
    return normalize_weights(constrained, n_assets)


def apply_stress_risk_governor(
    *,
    weights: np.ndarray,
    n_assets: int,
    volatility_z: float,
    drawdown: float,
    vol_z_threshold: float,
    drawdown_threshold: float,
    crisis_drawdown_threshold: float,
    stress_cash_floor: float,
    crisis_cash_floor: float,
    stress_max_risk_on: float,
    crisis_max_risk_on: float,
    enabled: bool = True,
) -> tuple[np.ndarray, dict[str, float | str | bool]]:
    """Raise cash and cap risk exposure in high-volatility or drawdown regimes."""
    normalized = normalize_weights(weights, n_assets)
    diagnostics: dict[str, float | str | bool] = {
        "active": False,
        "reason": "",
        "cash_floor": float(normalized[-1]),
        "max_risk_on": float(normalized[:-1].sum()),
    }
    if not enabled:
        return normalized, diagnostics

    is_crisis = float(drawdown) <= float(crisis_drawdown_threshold)
    is_stress = (
        float(volatility_z) >= float(vol_z_threshold)
        or float(drawdown) <= float(drawdown_threshold)
    )
    if not (is_stress or is_crisis):
        return normalized, diagnostics

    cash_floor = float(crisis_cash_floor if is_crisis else stress_cash_floor)
    max_risk_on = float(crisis_max_risk_on if is_crisis else stress_max_risk_on)
    max_risk_on = min(max_risk_on, 1.0 - cash_floor)

    governed = apply_min_cash_floor(normalized, cash_floor)
    risk_on = float(governed[:-1].sum())
    if risk_on > max_risk_on and risk_on > 0:
        governed[:-1] = governed[:-1] * (max_risk_on / risk_on)
        governed[-1] = 1.0 - float(governed[:-1].sum())

    governed = normalize_weights(governed, n_assets)
    reason_parts = []
    if float(volatility_z) >= float(vol_z_threshold):
        reason_parts.append("high_volatility")
    if float(drawdown) <= float(drawdown_threshold):
        reason_parts.append("drawdown")
    if is_crisis:
        reason_parts.append("crisis_drawdown")

    diagnostics.update(
        {
            "active": True,
            "reason": ",".join(reason_parts),
            "cash_floor": cash_floor,
            "max_risk_on": max_risk_on,
        }
    )
    return governed, diagnostics
