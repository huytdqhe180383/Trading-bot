import unittest

from scripts.estimate_agent_cost import estimate_all_models, estimate_agent_cost


class AgentCostEstimateTest(unittest.TestCase):
    def test_estimates_single_model_from_token_rates(self):
        result = estimate_agent_cost(
            input_tokens=55_802,
            output_tokens=10_000,
            input_rate_per_million=0.75,
            output_rate_per_million=4.50,
        )

        self.assertAlmostEqual(result, 0.0868515, places=7)

    def test_includes_api_dollars_and_codex_credits_for_baseline_models(self):
        estimates = estimate_all_models(input_tokens=55_802, output_tokens=10_000)

        self.assertAlmostEqual(estimates["api_usd"]["gpt-5.4-mini"], 0.0868515, places=7)
        self.assertAlmostEqual(estimates["api_usd"]["gpt-5.4"], 0.289505, places=6)
        self.assertAlmostEqual(estimates["api_usd"]["gpt-5.5"], 0.57901, places=5)
        self.assertAlmostEqual(estimates["codex_credits"]["gpt-5.3-codex"], 5.9413375, places=7)


if __name__ == "__main__":
    unittest.main()
