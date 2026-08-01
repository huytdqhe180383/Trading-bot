import unittest
from unittest.mock import patch

from tradingbot.analyst import news


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class XNewsLayerTest(unittest.TestCase):
    def setUp(self):
        news._x_user_id_cache.clear()

    def test_fetches_bounded_original_posts_from_official_account(self):
        calls = []

        def get(url, **kwargs):
            calls.append((url, kwargs))
            if url.endswith("/users/by/username/bls_gov"):
                return _Response({"data": {"id": "123"}})
            if url.endswith("/users/123/tweets"):
                return _Response(
                    {
                        "data": [
                            {"id": "p1", "text": "CPI release is now available.", "created_at": "2026-08-01T12:00:00Z"},
                            {"id": "p2", "text": "More release context.", "created_at": "2026-08-01T11:00:00Z"},
                            {"id": "p3", "text": "This item exceeds the requested cap.", "created_at": "2026-08-01T10:00:00Z"},
                        ]
                    }
                )
            self.fail(f"Unexpected X request: {url}")

        items = news.fetch_x_official_posts(
            bearer_token="test-token",
            accounts=("@BLS_gov",),
            posts_per_account=2,
            request_get=get,
        )

        self.assertEqual([item["title"] for item in items], ["CPI release is now available.", "More release context."])
        self.assertEqual(items[0]["source"], "x:@bls_gov")
        self.assertEqual(items[0]["url"], "https://x.com/bls_gov/status/p1")
        timeline_call = calls[1]
        self.assertEqual(timeline_call[1]["params"]["max_results"], 5)
        self.assertEqual(timeline_call[1]["params"]["exclude"], "retweets,replies")
        self.assertEqual(timeline_call[1]["headers"]["Authorization"], "Bearer test-token")

    def test_no_bearer_token_makes_no_network_requests(self):
        def get(*args, **kwargs):
            self.fail("X API must not be called without a bearer token.")

        self.assertEqual(
            news.fetch_x_official_posts(
                bearer_token="",
                accounts=("BLS_gov",),
                request_get=get,
            ),
            [],
        )

    def test_invalid_and_duplicate_accounts_are_not_requested(self):
        calls = []

        def get(url, **kwargs):
            calls.append(url)
            if url.endswith("/users/by/username/ecb"):
                return _Response({"data": {"id": "456"}})
            return _Response({"data": []})

        news.fetch_x_official_posts(
            bearer_token="test-token",
            accounts=("not/a-handle", "@ECB", "ecb"),
            request_get=get,
        )

        self.assertEqual(calls, ["https://api.x.com/2/users/by/username/ecb", "https://api.x.com/2/users/456/tweets"])

    def test_crypto_news_layer_merges_x_alert_posts_with_other_sources(self):
        x_item = {
            "title": "Federal Reserve statement released.",
            "url": "https://x.com/federalreserve/status/p1",
            "source": "x:@federalreserve",
            "published_at": "2026-08-01T12:00:00Z",
        }
        with patch("tradingbot.analyst.news.requests.get", side_effect=RuntimeError("rss unavailable")), patch(
            "tradingbot.analyst.news.fetch_x_official_posts", return_value=[x_item]
        ) as fetch_x:
            items = news.fetch_crypto_news(symbol="ALL", limit=8)

        self.assertEqual(items, [x_item])
        fetch_x.assert_called_once()


if __name__ == "__main__":
    unittest.main()
