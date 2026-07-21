from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


DEFAULT_ENTRY_DELTA = 0.05
DEFAULT_HOLD_DELTA = 0.03


@dataclass(frozen=True)
class RiskExitRule:
    tier: str
    max_risk_on: float
    reason: str


def normalize_weights(weights: np.ndarray) -> np.ndarray:
    normalized = np.asarray(weights, dtype=np.float32).copy()
    normalized[:-1] = np.clip(normalized[:-1], 0.0, 1.0)
    risk_on = float(normalized[:-1].sum())
    if risk_on > 1.0:
        normalized[:-1] /= risk_on
        risk_on = 1.0
    normalized[-1] = max(0.0, 1.0 - risk_on)
    return normalized.astype(np.float32)


def cap_risk_on(weights: np.ndarray, max_risk_on: float) -> np.ndarray:
    capped = normalize_weights(weights)
    risk_on = float(capped[:-1].sum())
    limit = float(np.clip(max_risk_on, 0.0, 1.0))
    if risk_on > limit and risk_on > 1e-9:
        capped[:-1] *= limit / risk_on
        capped[-1] = 1.0 - float(capped[:-1].sum())
    return normalize_weights(capped)


def classify_recommendation(
    current_weights: np.ndarray,
    target_weights: np.ndarray,
    *,
    hold_delta: float = DEFAULT_HOLD_DELTA,
    entry_delta: float = DEFAULT_ENTRY_DELTA,
) -> str:
    current = normalize_weights(current_weights)
    target = normalize_weights(target_weights)
    current_risk = float(current[:-1].sum())
    target_risk = float(target[:-1].sum())
    delta = target_risk - current_risk
    if target_risk <= 1e-6:
        return "recommend_cash"
    if abs(delta) < float(hold_delta):
        return "recommend_hold"
    if current_risk <= 1e-6 and delta >= float(entry_delta):
        return "recommend_buy"
    if delta > 0:
        return "recommend_buy"
    if delta < 0:
        return "recommend_reduce"
    return "recommend_hold"


def evaluate_hard_risk_exit(session_drawdown: float, btc_return_24h: float | None = None) -> RiskExitRule | None:
    drawdown = float(session_drawdown)
    btc_24h = None if btc_return_24h is None else float(btc_return_24h)
    eps = 1e-9
    if drawdown <= -0.12 + eps:
        return RiskExitRule("critical", 0.05, "session_drawdown<=-12%")
    if drawdown <= -0.09 + eps:
        return RiskExitRule("severe", 0.15, "session_drawdown<=-9%")
    if btc_24h is not None and btc_24h <= -0.08 + eps:
        return RiskExitRule("severe", 0.15, "btc_24h_return<=-8%")
    if drawdown <= -0.06 + eps:
        return RiskExitRule("warning", 0.35, "session_drawdown<=-6%")
    return None


class SemiAutoRiskController:
    def __init__(self) -> None:
        self.reentry_locked = False
        self._last_drawdown_exit_level = 0
        self._last_drawdown_exit_value: float | None = None
        self._last_exit_reason = ""
        self._drawdown_retrigger_buffer = 0.01
        self._drawdown_reset_threshold = -0.03

    @staticmethod
    def _tier_level(tier: str) -> int:
        return {"warning": 1, "severe": 2, "critical": 3}.get(str(tier), 0)

    @staticmethod
    def _is_drawdown_rule(rule: RiskExitRule) -> bool:
        return str(rule.reason).startswith("session_drawdown")

    def _reset_exit_memory_if_recovered(self, *, session_drawdown: float, btc_return_24h: float | None) -> None:
        if float(session_drawdown) >= self._drawdown_reset_threshold:
            self._last_drawdown_exit_level = 0
            self._last_drawdown_exit_value = None
        if btc_return_24h is not None and float(btc_return_24h) > -0.05 and self._last_exit_reason.startswith("btc_"):
            self._last_exit_reason = ""

    def _should_apply_hard_exit(
        self,
        rule: RiskExitRule,
        *,
        current_weights: np.ndarray,
        session_drawdown: float,
    ) -> bool:
        current_risk = float(normalize_weights(current_weights)[:-1].sum())
        rule_level = self._tier_level(rule.tier)
        if self._is_drawdown_rule(rule):
            if rule_level > self._last_drawdown_exit_level or self._last_drawdown_exit_value is None:
                return True
            retrigger_level = self._last_drawdown_exit_value - self._drawdown_retrigger_buffer
            return float(session_drawdown) <= retrigger_level

        if self._last_exit_reason == rule.reason and current_risk <= float(rule.max_risk_on) + 1e-6:
            return False
        return True

    def apply(
        self,
        *,
        target_weights: np.ndarray,
        current_weights: np.ndarray,
        session_drawdown: float,
        btc_return_24h: float | None,
        human_approved: bool = False,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        current = normalize_weights(current_weights)
        target = normalize_weights(target_weights)
        recommendation = classify_recommendation(current, target)
        self._reset_exit_memory_if_recovered(
            session_drawdown=session_drawdown,
            btc_return_24h=btc_return_24h,
        )
        rule = evaluate_hard_risk_exit(session_drawdown, btc_return_24h)
        diag: dict[str, Any] = {
            "semi_auto_mode": True,
            "recommendation": recommendation,
            "risk_exit_applied": False,
            "risk_exit_tier": "",
            "risk_exit_reason": "",
            "human_approval_required": False,
            "reentry_locked": self.reentry_locked,
        }
        if rule is not None and self._should_apply_hard_exit(
            rule,
            current_weights=current,
            session_drawdown=session_drawdown,
        ):
            self.reentry_locked = True
            if self._is_drawdown_rule(rule):
                self._last_drawdown_exit_level = max(self._last_drawdown_exit_level, self._tier_level(rule.tier))
                self._last_drawdown_exit_value = float(session_drawdown)
            self._last_exit_reason = rule.reason
            adjusted = cap_risk_on(current, rule.max_risk_on)
            diag.update(
                {
                    "risk_exit_applied": True,
                    "risk_exit_tier": rule.tier,
                    "risk_exit_reason": rule.reason,
                    "human_approval_required": False,
                    "reentry_locked": True,
                    "max_risk_on": rule.max_risk_on,
                }
            )
            return adjusted, diag

        current_risk = float(current[:-1].sum())
        target_risk = float(target[:-1].sum())
        needs_approval = target_risk > current_risk + DEFAULT_HOLD_DELTA
        if self.reentry_locked and target_risk > current_risk + 1e-6:
            needs_approval = True
        if needs_approval and not human_approved:
            diag["human_approval_required"] = True
            diag["reentry_locked"] = self.reentry_locked
            return current, diag
        if human_approved:
            self.reentry_locked = False
        diag["reentry_locked"] = self.reentry_locked
        return target, diag
