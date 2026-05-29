"""
Meta-fusion policy layer:
RL base allocation + Kronos tilt + TradingAgents risk governor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from adapters import KronosSignal, LLMRiskSignal, TradingAgentsSignal
from risk import apply_global_constraints, normalize_weights


@dataclass
class FusionDiagnostics:
    rl_base: list[float]
    pre_risk: list[float]
    pre_constraint: list[float]
    post_risk: list[float]
    kronos_tilts: dict[str, float] = field(default_factory=dict)
    kronos_raw_scores: dict[str, float] = field(default_factory=dict)
    kronos_confidences: dict[str, float] = field(default_factory=dict)
    trading_bias_tilt: float = 0.0
    llm_risk_flag: str = "allow"
    llm_risk_confidence: float = 0.0
    llm_risk_applied: bool = False
    applied_min_cash: float = 0.0
    applied_max_asset: float = 0.0
    turnover_pre_clip: float = 0.0
    turnover_post_clip: float = 0.0
    turnover_clip_ratio: float = 1.0
    constraint_clipped: bool = False
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
        llm_risk_gate_mode: str = "de_risk",
    ):
        self.symbols = list(symbols)
        self.n_assets = len(self.symbols)
        self.max_tilt_per_signal = max_tilt_per_signal
        self.max_portfolio_turnover = max_portfolio_turnover
        self.max_asset_weight = max_asset_weight
        self.min_cash_floor = min_cash_floor
        self.llm_risk_gate_mode = str(llm_risk_gate_mode).strip().lower()

    def fuse(
        self,
        *,
        rl_weights: np.ndarray,
        current_weights: np.ndarray,
        kronos_signals: dict[str, KronosSignal] | None = None,
        trading_signal: TradingAgentsSignal | None = None,
        llm_risk_signal: LLMRiskSignal | None = None,
    ) -> tuple[np.ndarray, FusionDiagnostics]:
        base = normalize_weights(rl_weights, self.n_assets)
        candidate = base.copy()
        kronos_tilts: dict[str, float] = {}
        kronos_raw_scores: dict[str, float] = {}
        kronos_confidences: dict[str, float] = {}
        has_kronos = bool(kronos_signals)
        has_trading_signal = trading_signal is not None
        has_llm_risk = llm_risk_signal is not None

        if not has_kronos and not has_trading_signal and not has_llm_risk:
            diagnostics = FusionDiagnostics(
                rl_base=base.tolist(),
                pre_risk=base.tolist(),
                pre_constraint=base.tolist(),
                post_risk=base.tolist(),
                kronos_tilts={},
                kronos_raw_scores={},
                kronos_confidences={},
                trading_bias_tilt=0.0,
                llm_risk_flag="allow",
                llm_risk_confidence=0.0,
                llm_risk_applied=False,
                applied_min_cash=self.min_cash_floor,
                applied_max_asset=self.max_asset_weight,
                turnover_pre_clip=0.0,
                turnover_post_clip=0.0,
                turnover_clip_ratio=1.0,
                constraint_clipped=False,
                notes={"has_trading_signal": False, "has_kronos": False, "has_llm_risk": False, "mode": "rl_only"},
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
                kronos_raw_scores[symbol] = float(sig.directional_score)
                kronos_confidences[symbol] = float(sig.confidence)
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

        llm_risk_flag = "allow"
        llm_risk_confidence = 0.0
        llm_risk_applied = False
        if llm_risk_signal is not None:
            llm_risk_flag = str(llm_risk_signal.risk_flag).strip().lower()
            llm_risk_confidence = float(np.clip(llm_risk_signal.confidence, 0.0, 1.0))
            if self.llm_risk_gate_mode == "de_risk" and llm_risk_flag == "de-risk":
                target_cash = float(np.clip(0.15 + 0.65 * llm_risk_confidence, applied_min_cash, 0.95))
                if candidate[-1] < target_cash:
                    risk_on = float(candidate[:-1].sum())
                    if risk_on > 1e-9:
                        scale = max((1.0 - target_cash) / risk_on, 0.0)
                        candidate[:-1] = candidate[:-1] * scale
                        candidate[-1] = 1.0 - float(candidate[:-1].sum())
                        llm_risk_applied = True
            elif self.llm_risk_gate_mode in {"de_risk", "block"} and llm_risk_flag == "block":
                candidate[:-1] = 0.0
                candidate[-1] = 1.0
                llm_risk_applied = True
            candidate = normalize_weights(candidate, self.n_assets)

        if not has_kronos and not has_trading_signal and not llm_risk_applied:
            diagnostics = FusionDiagnostics(
                rl_base=base.tolist(),
                pre_risk=base.tolist(),
                pre_constraint=base.tolist(),
                post_risk=base.tolist(),
                kronos_tilts={},
                kronos_raw_scores={},
                kronos_confidences={},
                trading_bias_tilt=0.0,
                llm_risk_flag=llm_risk_flag,
                llm_risk_confidence=llm_risk_confidence,
                llm_risk_applied=False,
                applied_min_cash=self.min_cash_floor,
                applied_max_asset=self.max_asset_weight,
                turnover_pre_clip=0.0,
                turnover_post_clip=0.0,
                turnover_clip_ratio=1.0,
                constraint_clipped=False,
                notes={
                    "has_trading_signal": False,
                    "has_kronos": False,
                    "has_llm_risk": has_llm_risk,
                    "mode": "rl_only_passthrough",
                    "mechanism_label": "unchanged",
                },
            )
            return base, diagnostics

        pre_constraint = candidate.copy()
        turnover_pre_clip = float(np.abs(pre_constraint[:-1] - current_weights[:-1]).sum())
        constrained = apply_global_constraints(
            current_weights=current_weights,
            target_weights=candidate,
            n_assets=self.n_assets,
            max_asset_weight=applied_max_asset,
            min_cash_floor=applied_min_cash,
            max_turnover=self.max_portfolio_turnover,
        )
        turnover_post_clip = float(np.abs(constrained[:-1] - current_weights[:-1]).sum())
        turnover_clip_ratio = 1.0 if turnover_pre_clip <= 1e-9 else float(turnover_post_clip / turnover_pre_clip)
        constraint_clipped = bool(turnover_post_clip + 1e-9 < turnover_pre_clip)
        base_risk_on = float(base[:-1].sum())
        pre_risk_on = float(pre_constraint[:-1].sum())
        if constraint_clipped:
            mechanism = "constraint_clipped"
        elif pre_risk_on + 1e-6 < base_risk_on:
            mechanism = "kronos_de_risk"
        elif pre_risk_on > base_risk_on + 1e-6:
            mechanism = "kronos_re_risk"
        else:
            mechanism = "unchanged"

        diagnostics = FusionDiagnostics(
            rl_base=base.tolist(),
            pre_risk=candidate.tolist(),
            pre_constraint=pre_constraint.tolist(),
            post_risk=constrained.tolist(),
            kronos_tilts=kronos_tilts,
            kronos_raw_scores=kronos_raw_scores,
            kronos_confidences=kronos_confidences,
            trading_bias_tilt=trading_bias_tilt,
            llm_risk_flag=llm_risk_flag,
            llm_risk_confidence=llm_risk_confidence,
            llm_risk_applied=llm_risk_applied,
            applied_min_cash=applied_min_cash,
            applied_max_asset=applied_max_asset,
            turnover_pre_clip=turnover_pre_clip,
            turnover_post_clip=turnover_post_clip,
            turnover_clip_ratio=turnover_clip_ratio,
            constraint_clipped=constraint_clipped,
            notes={
                "has_trading_signal": has_trading_signal,
                "has_kronos": has_kronos,
                "has_llm_risk": has_llm_risk,
                "mechanism_label": mechanism,
            },
        )
        return constrained, diagnostics
