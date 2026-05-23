import unittest

import numpy as np
import pandas as pd

from adapters.kronos_adapter import KronosAdapter


class KronosAdapterTest(unittest.TestCase):
    def test_unavailable_backend_returns_no_signal(self):
        idx = pd.date_range("2026-01-01", periods=64, freq="h", tz="UTC")
        close = np.linspace(100.0, 105.0, len(idx))
        frame = pd.DataFrame({"close": close}, index=idx)
        frame["log_return_1h"] = np.log(frame["close"] / frame["close"].shift(1))

        adapter = KronosAdapter(enabled=False)
        signal = adapter.predict_single("BTCUSDT", frame)

        self.assertIsNone(signal)

    def test_batch_skips_unavailable_symbols(self):
        idx = pd.date_range("2026-01-01", periods=64, freq="h", tz="UTC")
        frame = pd.DataFrame({"close": np.linspace(100.0, 105.0, len(idx))}, index=idx)
        adapter = KronosAdapter(enabled=False)

        signals = adapter.predict_batch({"BTCUSDT": frame})

        self.assertEqual(signals, {})


if __name__ == "__main__":
    unittest.main()
