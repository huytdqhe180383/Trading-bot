import unittest


class ApplicationEntrypointsTest(unittest.TestCase):
    def test_application_entrypoint_modules_expose_main(self):
        from tradingbot.apps import analyst, analyst_discord, backtest, live, live_report, train, ui

        self.assertTrue(callable(analyst.main))
        self.assertTrue(callable(analyst_discord.main))
        self.assertTrue(callable(backtest.main))
        self.assertTrue(callable(live.main))
        self.assertTrue(callable(live_report.main))
        self.assertTrue(callable(train.main))
        self.assertTrue(callable(ui.main))


if __name__ == "__main__":
    unittest.main()
