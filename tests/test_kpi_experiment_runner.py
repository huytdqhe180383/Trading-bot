import subprocess
import sys
import time
import unittest

from scripts import run_kpi_improvement_experiment as runner


class KpiExperimentRunnerTests(unittest.TestCase):
    def test_run_times_out_and_raises(self):
        start = time.monotonic()

        with self.assertRaises(subprocess.TimeoutExpired):
            runner._run(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                timeout_seconds=0.5,
                poll_seconds=0.1,
            )

        self.assertLess(time.monotonic() - start, 10)

    def test_parse_csv_subset_filters_known_values(self):
        parsed = runner._parse_csv_subset("42,2026", [42, 1337, 2026], item_type=int)

        self.assertEqual(parsed, [42, 2026])

    def test_risk_first_rank_prefers_trade_quality_over_return(self):
        high_return_low_quality = {
            "total_return_pct": 200.0,
            "trade_win_rate_pct": 45.0,
            "trade_profit_factor": 1.05,
            "sharpe_ratio": 1.0,
            "sortino_ratio": 1.2,
            "calmar_ratio": 1.0,
            "max_drawdown_pct": -30.0,
        }
        lower_return_higher_quality = {
            "total_return_pct": 25.0,
            "trade_win_rate_pct": 65.0,
            "trade_profit_factor": 1.35,
            "sharpe_ratio": 1.7,
            "sortino_ratio": 2.0,
            "calmar_ratio": 2.2,
            "max_drawdown_pct": -12.0,
        }

        self.assertGreater(
            runner.risk_first_rank_score(lower_return_higher_quality),
            runner.risk_first_rank_score(high_return_low_quality),
        )

    def test_promotion_gate_fails_closed_on_low_trade_win_rate(self):
        row = {
            "trade_win_rate_pct": 59.9,
            "trade_profit_factor": 1.5,
            "sharpe_ratio": 1.6,
            "sortino_ratio": 2.0,
            "calmar_ratio": 2.5,
            "max_drawdown_pct": -10.0,
            "june_plunge_max_drawdown_pct": -4.0,
        }

        passed, reasons = runner.passes_promotion_gates(row)

        self.assertFalse(passed)
        self.assertTrue(any("trade_win_rate_pct" in reason for reason in reasons))


if __name__ == "__main__":
    unittest.main()
