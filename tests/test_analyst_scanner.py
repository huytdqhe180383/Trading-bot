import unittest
from datetime import datetime, timezone

from tradingbot.analyst.scanner import _cadence_key


class AnalystScannerTest(unittest.TestCase):
    def test_cadence_key_groups_five_minute_windows(self):
        first = datetime(2026, 7, 15, 12, 4, 59, tzinfo=timezone.utc)
        second = datetime(2026, 7, 15, 12, 5, 0, tzinfo=timezone.utc)

        self.assertEqual(_cadence_key(first, "5m"), "2026-07-15T12:00")
        self.assertEqual(_cadence_key(second, "5m"), "2026-07-15T12:05")

    def test_cadence_key_supports_hourly_windows(self):
        now = datetime(2026, 7, 15, 13, 59, tzinfo=timezone.utc)

        self.assertEqual(_cadence_key(now, "2h"), "2026-07-15T12")


if __name__ == "__main__":
    unittest.main()
