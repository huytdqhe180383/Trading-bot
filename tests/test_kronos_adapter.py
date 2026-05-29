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

    def test_native_predictor_receives_timestamp_series(self):
        class FakePredictor:
            def __init__(self):
                self.x_timestamp = None
                self.y_timestamp = None

            def predict(self, **kwargs):
                self.x_timestamp = kwargs["x_timestamp"]
                self.y_timestamp = kwargs["y_timestamp"]
                return pd.DataFrame({"close": [106.0]})

        idx = pd.date_range("2026-01-01", periods=64, freq="h", tz="UTC")
        frame = pd.DataFrame(
            {
                "open": np.linspace(99.0, 104.0, len(idx)),
                "high": np.linspace(100.0, 105.0, len(idx)),
                "low": np.linspace(98.0, 103.0, len(idx)),
                "close": np.linspace(100.0, 105.0, len(idx)),
                "volume": np.linspace(10.0, 20.0, len(idx)),
            },
            index=idx,
        )
        predictor = FakePredictor()
        adapter = KronosAdapter(enabled=False)
        adapter.enabled = True
        adapter._predictor = predictor
        adapter._backend_name = "kronos"

        signal = adapter.predict_single("BTCUSDT", frame)

        self.assertIsNotNone(signal)
        self.assertIsInstance(predictor.x_timestamp, pd.Series)
        self.assertIsInstance(predictor.y_timestamp, pd.Series)
        self.assertTrue(hasattr(predictor.x_timestamp, "dt"))
        self.assertTrue(hasattr(predictor.y_timestamp, "dt"))


if __name__ == "__main__":
    unittest.main()
