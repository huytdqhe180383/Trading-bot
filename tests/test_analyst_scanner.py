import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from tradingbot.analyst.models import AnalystEvent
from tradingbot.analyst.scanner import AnalystScanner, _cadence_key, _is_significant


class _FakeService:
    def __init__(self):
        self.calls = []

    def run_update(self, **kwargs):
        self.calls.append(kwargs)
        return AnalystEvent(
            event_type=kwargs["analysis_mode"],
            status="ok",
            title="test",
            message="test",
            symbol=kwargs["symbol"],
            role="main_analyst",
            recommendation="AVOID",
        )


class AnalystScannerTest(unittest.TestCase):
    def test_paused_scanner_does_not_start_timeframe_or_legacy_work(self):
        service = _FakeService()
        scanner = AnalystScanner(service=service, symbols=("BTCUSDT",), paused=True)

        self.assertEqual(scanner.run_once(), [])
        self.assertEqual(service.calls, [])

    def test_each_cycle_uses_weak_screening_and_only_one_strong_call_per_cadence(self):
        service = _FakeService()
        scanner = AnalystScanner(service=service, symbols=("BTCUSDT",), background_analysis_cadence="15m")
        snapshot = {"fifteen_minute": {"window_return_pct": 0.1}, "one_hour": {"window_return_pct": 0.2}}

        with patch("tradingbot.analyst.scanner.fetch_screening_snapshot", return_value=snapshot), patch(
            "tradingbot.analyst.scanner.fetch_public_snapshot", return_value={"timeframes": {}}
        ):
            scanner.run_once()
            scanner.run_once()

        self.assertEqual([call["scope"] for call in service.calls], ["screening", "scheduled", "screening"])
        self.assertEqual([call["analysis_mode"] for call in service.calls], ["screening", "scheduled", "screening"])

    def test_provider_error_is_never_sent_to_discord_even_during_a_risk_trigger(self):
        event = AnalystEvent(
            event_type="screening",
            status="error",
            title="ETHUSDT weak screening",
            message="LLM unavailable: invalid token",
            symbol="ETHUSDT",
            role="main_analyst",
        )

        self.assertFalse(_is_significant(event, trigger="15m_drop"))

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
