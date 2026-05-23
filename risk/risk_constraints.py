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
