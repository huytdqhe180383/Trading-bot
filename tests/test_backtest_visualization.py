import tempfile
import unittest
from pathlib import Path

import pandas as pd

from metrics.performance import plot_ensemble_method_comparison


class BacktestVisualizationTest(unittest.TestCase):
    def test_plot_ensemble_method_comparison_writes_all_methods(self):
        comparison = pd.DataFrame(
            [
                {"method": "mean", "total_return_pct": 1.0, "sharpe_ratio": 0.1, "max_drawdown_pct": -5.0},
                {"method": "weighted", "total_return_pct": 2.0, "sharpe_ratio": 0.2, "max_drawdown_pct": -4.0},
                {
                    "method": "dynamic_weighted",
                    "total_return_pct": 3.0,
                    "sharpe_ratio": 0.3,
                    "max_drawdown_pct": -3.0,
                },
            ]
        )
        index = pd.date_range("2026-01-01", periods=3, freq="h")
        equity_curves = {
            "mean": pd.Series([100.0, 101.0, 102.0], index=index),
            "weighted": pd.Series([100.0, 102.0, 104.0], index=index),
            "dynamic_weighted": pd.Series([100.0, 103.0, 106.0], index=index),
        }

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "method_comparison.png"
            plotted = plot_ensemble_method_comparison(comparison, equity_curves, save_path=out)

            self.assertEqual(plotted, ["mean", "weighted", "dynamic_weighted"])
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
