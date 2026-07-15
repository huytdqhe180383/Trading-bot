import unittest
from unittest.mock import patch

from tradingbot.analyst.market import fetch_public_candles


class _FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "code": "0",
            "data": [
                ["1800000060000", "101", "102", "100", "101.5", "2.5"],
                ["1800000000000", "100", "101", "99", "100.5", "1.5"],
            ],
        }


class AnalystMarketTest(unittest.TestCase):
    def test_fetch_public_candles_normalizes_okx_rows_for_charting(self):
        with patch("tradingbot.analyst.market.requests.get", return_value=_FakeResponse()) as request:
            candles = fetch_public_candles("BTCUSDT", interval="1h", limit=100)

        self.assertEqual([row["time"] for row in candles], [1800000000, 1800000060])
        self.assertEqual(candles[0]["open"], 100.0)
        self.assertEqual(candles[0]["close"], 100.5)
        self.assertEqual(candles[0]["source"], "okx_public")
        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs["params"]["instId"], "BTC-USDT")
        self.assertEqual(request.call_args.kwargs["params"]["bar"], "1H")

    def test_fetch_public_candles_rejects_unapproved_symbols(self):
        with self.assertRaises(ValueError):
            fetch_public_candles("DOGEUSDT")

    def test_fetch_public_candles_rejects_unapproved_intervals(self):
        with self.assertRaises(ValueError):
            fetch_public_candles("BTCUSDT", interval="2m")


if __name__ == "__main__":
    unittest.main()
