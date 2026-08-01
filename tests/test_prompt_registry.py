import unittest

from tradingbot.prompts import (
    analyst_system_prompt,
    execution_planner_system_prompt,
    portfolio_risk_gate_system_prompt,
)


class PromptRegistryTest(unittest.TestCase):
    def test_analyst_roles_share_input_and_schema_safeguards(self):
        for role in ("main_analyst", "technical_analyst", "risk_validator"):
            prompt = analyst_system_prompt(role)
            self.assertIn("untrusted data", prompt)
            self.assertIn('"recommendation":"BUY|SELL|REDUCE|HOLD|AVOID"', prompt)
            self.assertIn("ABSTAIN is no RL opinion", prompt)
        self.assertIn("non-executable schema sentinel", analyst_system_prompt("technical_analyst"))

    def test_execution_prompt_matches_the_validated_order_contract(self):
        prompt = execution_planner_system_prompt()
        self.assertIn('"action":"NO_TRADE"', prompt)
        self.assertIn('"action":"PLACE"', prompt)
        self.assertIn("same-user confirmation", prompt)
        self.assertIn("Market BUY must use quote-sized USDT", prompt)

    def test_portfolio_risk_gate_cannot_override_deterministic_controls(self):
        prompt = portfolio_risk_gate_system_prompt()
        self.assertIn("Deterministic controls are\nauthoritative", prompt)
        self.assertIn('"risk_flag":"allow|de-risk|block"', prompt)


if __name__ == "__main__":
    unittest.main()
