"""
Meta-fusion policy layer:
RL base allocation + Kronos tilt + TradingAgents risk governor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from adapters import KronosSignal, TradingAgentsSignal
from risk import apply_global_constraints, normalize_weights


@dataclass
class FusionDiagnostics:
    rl_base: list[float]
    pre_risk: list[float]
    post_risk: list[float]
    kronos_tilts: dict[str, float] = field(default_factory=dict)
    trading_bias_tilt: float = 0.0
    applied_min_cash: float = 0.0
    applied_max_asset: float = 0.0
    notes: dict[str, Any] = field(default_factory=dict)


class MetaFusionAgent:
    def __init__(
        self,
        *,
        symbols: list[str],
        max_tilt_per_signal: float,
        max_portfolio_turnover: float,
        max_asset_weight: float,
        min_cash_floor: float,
    ):
        self.symbols = list(symbols)
        self.n_assets = len(self.symbols)
        self.max_tilt_per_signal = max_tilt_per_signal
        self.max_portfolio_turnover = max_portfolio_turnover
        self.max_asset_weight = max_asset_weight
        self.min_cash_floor = min_cash_floor

    def fuse(
        self,
        *,
        rl_weights: np.ndarray,
        current_weights: np.ndarray,
        kronos_signals: dict[str, KronosSignal] | None = None,
        trading_signal: TradingAgentsSignal | None = None,
    ) -> tuple[np.ndarray, FusionDiagnostics]:
        base = normalize_weights(rl_weights, self.n_assets)
        candidate = base.copy()
        kronos_tilts: dict[str, float] = {}
        has_kronos = bool(kronos_signals)
        has_trading_signal = trading_signal is not None

        if not has_kronos and not has_trading_signal:
            diagnostics = FusionDiagnostics(
                rl_base=base.tolist(),
                pre_risk=base.tolist(),
                post_risk=base.tolist(),
                kronos_tilts={},
                trading_bias_tilt=0.0,
                applied_min_cash=self.min_cash_floor,
                applied_max_asset=self.max_asset_weight,
                notes={"has_trading_signal": False, "has_kronos": False, "mode": "rl_only"},
            )
            return base, diagnostics

        if kronos_signals:
            for i, symbol in enumerate(self.symbols):
                sig = kronos_signals.get(symbol)
                if sig is None:
                    continue
                tilt = float(
                    np.clip(
                        sig.directional_score * sig.confidence * self.max_tilt_per_signal,
                        -self.max_tilt_per_signal,
                        self.max_tilt_per_signal,
                    )
                )
                candidate[i] += tilt
                candidate[-1] -= tilt
                kronos_tilts[symbol] = tilt
            candidate = normalize_weights(candidate, self.n_assets)

        trading_bias_tilt = 0.0
        applied_max_asset = self.max_asset_weight
        applied_min_cash = self.min_cash_floor

        if trading_signal is not None:
            trading_bias_tilt = float(
                np.clip(
                    trading_signal.bias_score
                    * trading_signal.confidence
                    * self.max_tilt_per_signal,
                    -self.max_tilt_per_signal,
                    self.max_tilt_per_signal,
                )
            )

            if trading_bias_tilt >= 0:
                asset_allocation = candidate[:-1].copy()
                if asset_allocation.sum() <= 1e-9:
                    asset_allocation = np.ones(self.n_assets, dtype=np.float32) / self.n_assets
                else:
                    asset_allocation = asset_allocation / asset_allocation.sum()
                shift = min(float(candidate[-1]), trading_bias_tilt)
                candidate[:-1] += asset_allocation * shift
                candidate[-1] -= shift
            else:
                downscale = min(1.0, abs(trading_bias_tilt))
                moved_to_cash = candidate[:-1] * downscale
                candidate[:-1] -= moved_to_cash
                candidate[-1] += float(moved_to_cash.sum())

            applied_max_asset = min(applied_max_asset, trading_signal.max_asset_weight)
            applied_min_cash = max(applied_min_cash, trading_signal.cash_floor)
            candidate = normalize_weights(candidate, self.n_assets)

        constrained = apply_global_constraints(
            current_weights=current_weights,
            target_weights=candidate,
            n_assets=self.n_assets,
            max_asset_weight=applied_max_asset,
            min_cash_floor=applied_min_cash,
            max_turnover=self.max_portfolio_turnover,
        )

        diagnostics = FusionDiagnostics(
            rl_base=base.tolist(),
            pre_risk=candidate.tolist(),
            post_risk=constrained.tolist(),
            kronos_tilts=kronos_tilts,
            trading_bias_tilt=trading_bias_tilt,
            applied_min_cash=applied_min_cash,
            applied_max_asset=applied_max_asset,
            notes={"has_trading_signal": has_trading_signal, "has_kronos": has_kronos},
        )
        return constrained, diagnostics
