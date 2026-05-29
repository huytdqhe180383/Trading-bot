import unittest

import numpy as np

from adapters.kronos_adapter import KronosSignal
from adapters.llm_risk_gate_adapter import LLMRiskSignal
from adapters.tradingagents_adapter import TradingAgentsSignal
from agents.meta_fusion_agent import MetaFusionAgent


class MetaFusionAgentTest(unittest.TestCase):
    def test_fusion_applies_constraints_and_stays_normalized(self):
        fusion = MetaFusionAgent(
            symbols=["BTCUSDT", "ETHUSDT"],
            max_tilt_per_signal=0.05,
            max_portfolio_turnover=0.25,
            max_asset_weight=0.75,
            min_cash_floor=0.05,
        )
        rl = np.array([0.55, 0.35, 0.10], dtype=np.float32)
        current = np.array([0.40, 0.20, 0.40], dtype=np.float32)

        kronos = {
            "BTCUSDT": KronosSignal("BTCUSDT", 0.01, 0.8, 0.5, "kronos"),
            "ETHUSDT": KronosSignal("ETHUSDT", -0.005, 0.9, -0.4, "kronos"),
        }
        ta = TradingAgentsSignal(
            bias_score=-0.4,
            confidence=0.9,
            max_asset_weight=0.6,
            cash_floor=0.2,
            high_risk=True,
            source="tradingagents:shopai",
            rationale="risk off",
        )

        weights, diag = fusion.fuse(
            rl_weights=rl,
            current_weights=current,
            kronos_signals=kronos,
            trading_signal=ta,
        )

        self.assertAlmostEqual(float(weights.sum()), 1.0, places=6)
        self.assertGreaterEqual(float(weights[-1]), 0.2)
        self.assertLessEqual(float(weights[0]), 0.6)
        self.assertLessEqual(float(weights[1]), 0.6)
        self.assertIn("BTCUSDT", diag.kronos_tilts)
        self.assertIn("BTCUSDT", diag.kronos_confidences)
        self.assertEqual(len(diag.pre_constraint), 3)
        self.assertGreaterEqual(diag.turnover_pre_clip, diag.turnover_post_clip)

    def test_unavailable_external_signals_leave_rl_unchanged(self):
        fusion = MetaFusionAgent(
            symbols=["BTCUSDT", "ETHUSDT"],
            max_tilt_per_signal=0.05,
            max_portfolio_turnover=1.0,
            max_asset_weight=0.95,
            min_cash_floor=0.0,
        )
        rl = np.array([0.55, 0.35, 0.10], dtype=np.float32)

        weights, diag = fusion.fuse(
            rl_weights=rl,
            current_weights=rl,
            kronos_signals={},
            trading_signal=None,
        )

        np.testing.assert_allclose(weights, rl, atol=1e-6)
        self.assertFalse(diag.notes["has_kronos"])
        self.assertFalse(diag.notes["has_trading_signal"])

    def test_llm_risk_gate_block_sets_cash(self):
        fusion = MetaFusionAgent(
            symbols=["BTCUSDT", "ETHUSDT"],
            max_tilt_per_signal=0.05,
            max_portfolio_turnover=1.0,
            max_asset_weight=0.95,
            min_cash_floor=0.0,
            llm_risk_gate_mode="block",
        )
        rl = np.array([0.5, 0.45, 0.05], dtype=np.float32)
        signal = LLMRiskSignal(
            risk_flag="block",
            confidence=0.9,
            rationale="stress",
            source="llm_risk_gate:ollama",
        )
        weights, diag = fusion.fuse(
            rl_weights=rl,
            current_weights=rl,
            kronos_signals=None,
            trading_signal=None,
            llm_risk_signal=signal,
        )
        self.assertAlmostEqual(float(weights[-1]), 1.0, places=6)
        self.assertTrue(diag.llm_risk_applied)
        self.assertEqual(diag.llm_risk_flag, "block")

    def test_llm_allow_passthrough_matches_rl_only(self):
        fusion = MetaFusionAgent(
            symbols=["BTCUSDT", "ETHUSDT"],
            max_tilt_per_signal=0.05,
            max_portfolio_turnover=0.25,
            max_asset_weight=0.8,
            min_cash_floor=0.05,
            llm_risk_gate_mode="de_risk",
        )
        rl = np.array([0.52, 0.46, 0.02], dtype=np.float32)
        signal = LLMRiskSignal(
            risk_flag="allow",
            confidence=0.7,
            rationale="neutral",
            source="llm_risk_gate:ollama",
        )
        weights, diag = fusion.fuse(
            rl_weights=rl,
            current_weights=np.array([0.0, 0.0, 1.0], dtype=np.float32),
            llm_risk_signal=signal,
            kronos_signals=None,
            trading_signal=None,
        )
        np.testing.assert_allclose(weights, rl, atol=1e-6)
        self.assertFalse(diag.llm_risk_applied)


if __name__ == "__main__":
    unittest.main()
