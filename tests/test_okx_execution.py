import base64
import hashlib
import hmac
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from tradingbot.analyst.budget import LLMBudget
from tradingbot.analyst.store import AnalystEventStore
from tradingbot.execution.okx_client import OKXDemoClient
from tradingbot.execution.service import TradingExecutionService, validate_order_plan
from tradingbot.execution.suggestions import OrderSuggestionStore


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class OKXClientTest(unittest.TestCase):
    def test_private_requests_are_signed_with_demo_header(self):
        calls = []

        def request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return _Response({"code": "0", "data": [{"details": []}]})

        timestamp = datetime(2026, 7, 28, 12, 0, 0, 123000, tzinfo=timezone.utc)
        client = OKXDemoClient(
            api_key="test-key",
            secret_key="test-secret",
            passphrase="test-pass",
            request=request,
            now=lambda: timestamp,
        )

        client._request_json("GET", "/api/v5/account/balance", private=True)

        headers = calls[0][2]["headers"]
        expected = base64.b64encode(
            hmac.new(
                b"test-secret",
                b"2026-07-28T12:00:00.123ZGET/api/v5/account/balance",
                hashlib.sha256,
            ).digest()
        ).decode("ascii")
        self.assertEqual(headers["OK-ACCESS-SIGN"], expected)
        self.assertEqual(headers["x-simulated-trading"], "1")
        self.assertEqual(headers["OK-ACCESS-KEY"], "test-key")

    def test_market_slippage_estimate_uses_order_book_depth(self):
        client = OKXDemoClient(
            api_key="a",
            secret_key="b",
            passphrase="c",
            max_slippage_pct=0.01,
            max_order_notional_usdt=1000,
        )
        market = {
            "ticker": {"last": "100"},
            "orderbook": {
                "bids": [["99.9", "10"]],
                "asks": [["100.1", "1"], ["101", "2"]],
            },
        }
        result = client.estimate_market_slippage(
            {"side": "buy", "ord_type": "market", "size": "150", "size_unit": "quote"},
            market=market,
        )

        self.assertTrue(result["liquidity_sufficient"])
        self.assertGreater(result["estimated_slippage_pct"], 0.0)
        self.assertAlmostEqual(result["estimated_avg_price"], 100.3976, places=3)

    def test_place_market_order_sends_native_slippage_parameter(self):
        calls = []

        def request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return _Response({"code": "0", "data": [{"ordId": "123", "clOrdId": "client"}]})

        client = OKXDemoClient(api_key="a", secret_key="b", passphrase="c", request=request)
        result = client.place_order(
            {
                "inst_id": "BTC-USDT",
                "side": "buy",
                "ord_type": "market",
                "size": "50",
                "size_unit": "quote",
                "slippage_pct": "0.005",
            },
            client_order_id="client",
            exp_time_ms=1800000000000,
        )

        body = json.loads(calls[0][2]["data"])
        self.assertEqual(result["ord_id"], "123")
        self.assertEqual(body["tgtCcy"], "quote_ccy")
        self.assertEqual(body["slippagePct"], "0.005")
        self.assertEqual(body["expTime"], "1800000000000")

    def test_limit_price_is_checked_against_adverse_slippage_bound(self):
        client = OKXDemoClient(
            api_key="a",
            secret_key="b",
            passphrase="c",
            max_slippage_pct=0.005,
        )
        market = {"orderbook": {"bids": [["100", "10"]], "asks": [["100.1", "10"]]}}

        with self.assertRaises(RuntimeError):
            client.check_limit_price_slippage(
                {"ord_type": "limit", "side": "buy", "price": "101"},
                market=market,
            )


class OrderPlanValidationTest(unittest.TestCase):
    def test_market_plan_requires_explicit_slippage(self):
        with self.assertRaises(ValueError):
            validate_order_plan(
                {
                    "action": "PLACE",
                    "side": "BUY",
                    "order_type": "MARKET",
                    "size": 50,
                    "size_unit": "quote",
                    "rationale": "Momentum and available balance support a small test order.",
                },
                max_slippage_pct=0.005,
            )

    def test_live_order_plan_is_rejected_by_client_mode(self):
        with self.assertRaises(ValueError):
            OKXDemoClient(api_key="a", secret_key="b", passphrase="c", mode="live")


class TradingExecutionServiceTest(unittest.TestCase):
    def test_confirm_rechecks_context_then_submits_only_once(self):
        with TemporaryDirectory() as tmp_name:
            base = Path(tmp_name)
            event_store = AnalystEventStore(results_dir=base / "results", reports_dir=base / "report")
            llm = Mock()
            llm.model = "planner"
            llm.chat_json.return_value = {
                "action": "PLACE",
                "side": "BUY",
                "order_type": "MARKET",
                "size": 50,
                "size_unit": "quote",
                "slippage_pct": 0.002,
                "rationale": "A small demo order is supported by the current account and market context.",
                "risk_notes": "Use the configured slippage cap and confirm only once.",
                "confidence": 0.7,
            }
            analyst = Mock()
            analyst.interactive_llm_client = llm
            analyst.budget = LLMBudget(background_daily_limit=4, interactive_daily_limit=4)
            analyst.build_multi_agent_views.return_value = [{"role": "technical_analyst", "status": "ok"}]
            analyst.store = event_store

            okx = Mock()
            okx.max_slippage_pct = 0.005
            okx.max_order_notional_usdt = 100.0
            okx.fetch_account_context.side_effect = lambda **kwargs: {
                "balances": [{"ccy": "USDT", "avail_bal": "1000", "equity": "1000"}],
                "open_orders": [],
                "positions": [],
            }
            okx.fetch_market_context.return_value = {
                "instrument": {"instId": "BTC-USDT", "lotSz": "0.00001", "minSz": "0.00001", "tickSz": "0.1"},
                "ticker": {"last": "100"},
                "orderbook": {"bids": [["99.9", "10"]], "asks": [["100.1", "10"]]},
            }
            okx.fetch_instrument.return_value = okx.fetch_market_context.return_value["instrument"]
            okx.normalize_order.return_value = {
                "inst_id": "BTC-USDT",
                "side": "buy",
                "ord_type": "market",
                "size": "50",
                "size_unit": "quote",
                "slippage_pct": "0.002",
                "price": None,
                "estimated_notional_usdt": "50",
            }
            okx.estimate_market_slippage.return_value = {
                "applicable": True,
                "estimated_slippage_pct": 0.001,
            }
            okx.place_order.return_value = {"ord_id": "demo-1", "cl_ord_id": "client-1"}
            service = TradingExecutionService(
                analyst_service=analyst,
                okx_client=okx,
                suggestion_store=OrderSuggestionStore(results_dir=base / "results"),
                event_store=event_store,
                execution_enabled=True,
            )

            suggestion = service.suggest_order(symbol="BTCUSDT", instruction="Buy a small amount.", requested_by="42")
            self.assertEqual(suggestion.status, "pending")
            suggestion_id = suggestion.payload["suggestion_id"]

            submitted = service.confirm_order(suggestion_id=suggestion_id, requested_by="42")
            self.assertEqual(submitted.status, "submitted")
            okx.place_order.assert_called_once()

            duplicate = service.confirm_order(suggestion_id=suggestion_id, requested_by="42")
            self.assertEqual(duplicate.status, "error")
            okx.place_order.assert_called_once()

    def test_suggestion_is_bound_to_requesting_user(self):
        with TemporaryDirectory() as tmp_name:
            base = Path(tmp_name)
            store = OrderSuggestionStore(results_dir=base / "results")
            store.create(
                {
                    "id": "s1",
                    "requested_by": "42",
                    "status": "pending",
                    "expires_at_utc": "2999-01-01T00:00:00+00:00",
                    "order": {"inst_id": "BTC-USDT"},
                }
            )
            service = TradingExecutionService(
                analyst_service=Mock(),
                okx_client=Mock(),
                suggestion_store=store,
                event_store=AnalystEventStore(results_dir=base / "results", reports_dir=base / "report"),
                execution_enabled=True,
            )

            result = service.confirm_order(suggestion_id="s1", requested_by="99")

            self.assertEqual(result.status, "error")
            self.assertEqual(result.error_code, "requester_mismatch")


if __name__ == "__main__":
    unittest.main()
