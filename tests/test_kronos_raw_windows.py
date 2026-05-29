import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from data.kronos_windows import load_raw_ohlcv_data, window_raw_ohlcv


class KronosRawWindowTest(unittest.TestCase):
    def test_load_raw_ohlcv_data_keeps_required_columns_and_test_range(self):
        with TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            idx = pd.date_range("2025-12-31 22:00", periods=5, freq="h", tz="UTC")
            raw = pd.DataFrame(
                {
                    "open": [1, 2, 3, 4, 5],
                    "high": [2, 3, 4, 5, 6],
                    "low": [0, 1, 2, 3, 4],
                    "close": [1.5, 2.5, 3.5, 4.5, 5.5],
                    "volume": [10, 20, 30, 40, 50],
                    "num_trades": [1, 1, 1, 1, 1],
                },
                index=idx,
            )
            raw.to_parquet(raw_dir / "BTCUSDT_1h.parquet")

            loaded = load_raw_ohlcv_data(
                ["BTCUSDT"],
                raw_data_dir=raw_dir,
                start="2026-01-01",
                end="2026-01-01 02:00",
            )

        frame = loaded["BTCUSDT"]
        self.assertEqual(list(frame.columns), ["open", "high", "low", "close", "volume"])
        self.assertEqual(frame.index[0], pd.Timestamp("2026-01-01 00:00", tz="UTC"))
        self.assertEqual(frame.index[-1], pd.Timestamp("2026-01-01 02:00", tz="UTC"))

    def test_window_raw_ohlcv_aligns_to_current_timestamp(self):
        idx = pd.date_range("2026-01-01", periods=6, freq="h", tz="UTC")
        frame = pd.DataFrame(
            {
                "open": range(6),
                "high": range(1, 7),
                "low": range(6),
                "close": range(2, 8),
                "volume": range(10, 16),
            },
            index=idx,
        )

        windows = window_raw_ohlcv({"BTCUSDT": frame}, timestamp=idx[4], lookback=3)

        out = windows["BTCUSDT"]
        self.assertEqual(list(out.index), list(idx[2:5]))
        self.assertEqual(list(out.columns), ["open", "high", "low", "close", "volume"])


if __name__ == "__main__":
    unittest.main()
