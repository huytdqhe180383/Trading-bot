import unittest

import pandas as pd

from train import split_train_validation


class TrainHygieneTest(unittest.TestCase):
    def test_split_train_validation_is_chronological(self):
        idx = pd.date_range("2024-01-01", periods=10, freq="h", tz="UTC")
        data = {
            "BTCUSDT": pd.DataFrame({"x": range(10)}, index=idx),
            "ETHUSDT": pd.DataFrame({"x": range(10, 20)}, index=idx),
        }

        train_data, validation_data = split_train_validation(data, 0.2)

        self.assertEqual(len(train_data["BTCUSDT"]), 8)
        self.assertEqual(len(validation_data["BTCUSDT"]), 2)
        self.assertLess(train_data["BTCUSDT"].index[-1], validation_data["BTCUSDT"].index[0])
        self.assertEqual(validation_data["ETHUSDT"]["x"].tolist(), [18, 19])


if __name__ == "__main__":
    unittest.main()
