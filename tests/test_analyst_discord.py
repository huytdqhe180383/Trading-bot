import unittest

from tradingbot.analyst.discord_bot import DiscordAnalystBot, DiscordAnalystConfig, DiscordNotifier
from tradingbot.analyst.models import AnalystEvent
from tradingbot.analyst.news import _parse_okx_announcement_html, format_news_message


class DiscordAnalystTest(unittest.TestCase):
    def test_allowlist_enforces_user_and_channel(self):
        config = DiscordAnalystConfig(
            bot_token="token",
            application_id="app",
            guild_id="guild",
            alert_channel_id="10",
            analyst_channel_id="20",
            allowed_user_ids=frozenset({"1"}),
        )
        bot = DiscordAnalystBot(service=None, config=config)

        bot.require_allowed(user_id=1, channel_id=20)
        with self.assertRaises(PermissionError):
            bot.require_allowed(user_id=2, channel_id=20)
        with self.assertRaises(PermissionError):
            bot.require_allowed(user_id=1, channel_id=30)

    def test_format_error_event_does_not_invent_recommendation(self):
        config = DiscordAnalystConfig("", "", "", "10", "20", frozenset({"1"}))
        bot = DiscordAnalystBot(service=None, config=config)
        event = AnalystEvent(
            event_type="analysis",
            status="error",
            title="BTC analyst update",
            message="LLM unavailable: timeout",
        )

        text = bot.format_event(event)

        self.assertIn("Status: error", text)
        self.assertNotIn("Recommendation:", text)

    def test_notifier_sends_bot_message_with_action_buttons(self):
        calls = []

        class Response:
            def raise_for_status(self):
                return None

        def post(url, **kwargs):
            calls.append((url, kwargs))
            return Response()

        config = DiscordAnalystConfig("token", "app", "guild", "10", "20", frozenset({"1"}))
        event = AnalystEvent(
            id="abc123",
            event_type="analysis",
            status="ok",
            title="BTC analyst update",
            message="No decisive edge.",
            recommendation="HOLD",
        )

        sent = DiscordNotifier(config=config, post=post).send_event(event)

        self.assertTrue(sent)
        self.assertEqual(calls[0][0], "https://discord.com/api/v10/channels/10/messages")
        payload = calls[0][1]["json"]
        self.assertIn("components", payload)
        button_ids = [item["custom_id"] for item in payload["components"][0]["components"]]
        self.assertEqual(
            button_ids,
            ["analyst:explain:abc123", "analyst:validate:abc123", "analyst:news:abc123"],
        )

    def test_okx_announcement_parser_formats_news(self):
        items = _parse_okx_announcement_html(
            '<a href="/help/okx-to-support-btc-network-update">OKX to support BTC network update</a>'
            '<a href="/help/okx-to-list-eth-contract">OKX to list ETH contract</a>'
        )

        message = format_news_message([item.to_dict() for item in items], symbol="BTCUSDT")

        self.assertIn("Latest OKX announcements", message)
        self.assertIn("OKX to support BTC network update", message)


if __name__ == "__main__":
    unittest.main()
