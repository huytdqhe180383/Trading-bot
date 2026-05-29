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


if __name__ == "__main__":
    unittest.main()
