import unittest

import pandas as pd

from metrics.performance import compute_metrics


class PerformanceTailMetricsTest(unittest.TestCase):
    def test_compute_metrics_includes_tail_risk(self):
        nav = pd.Series([100.0, 101.0, 99.0, 98.0, 103.0, 97.0, 104.0])

        metrics = compute_metrics(nav, initial_capital=100.0)

        self.assertIn("cvar_95_pct", metrics)
        self.assertIn("cvar_99_pct", metrics)
        self.assertLess(metrics["cvar_95_pct"], 0.0)
        self.assertLess(metrics["cvar_99_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
