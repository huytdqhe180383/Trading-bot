"""Small native OKX V5 client for the confirmed demo-trading path.

The existing live runner remains CCXT-backed. This client is intentionally
narrower: it signs the private account/order endpoints needed by the analyst
confirmation flow and refuses to submit outside OKX demo trading.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any, Callable
from urllib.parse import urlencode

import requests

from config import OKX_API_BASE_URL, OKX_MAX_ORDER_NOTIONAL_USDT, OKX_MAX_SLIPPAGE_PCT, TRADING_MODE


class OKXClientError(RuntimeError):
    """Raised for OKX transport, API, or local preflight failures."""


def normalize_inst_id(symbol: str) -> str:
    value = str(symbol or "").strip().upper().replace("/", "-")
    if value.endswith("USDT") and "-" not in value:
        value = f"{value[:-4]}-USDT"
    if value not in {"BTC-USDT", "ETH-USDT"}:
        raise ValueError("Only BTC-USDT and ETH-USDT spot instruments are supported.")
    return value


def _decimal(value: Any, *, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise OKXClientError(f"{field} must be numeric.") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise OKXClientError(f"{field} must be greater than zero.")
    return parsed


def _decimal_string(value: Decimal) -> str:
    text = format(value, "f")
    text = text.rstrip("0").rstrip(".")
    return text or "0"


def _round_down(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def _float_or_zero(value: Any) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else 0.0
    except (TypeError, ValueError):
        return 0.0


class OKXDemoClient:
    """Authenticated OKX V5 client restricted to the demo environment."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        secret_key: str | None = None,
        passphrase: str | None = None,
        base_url: str = OKX_API_BASE_URL,
        mode: str = TRADING_MODE,
        request: Callable[..., Any] | None = None,
        now: Callable[[], datetime] | None = None,
        max_slippage_pct: float = OKX_MAX_SLIPPAGE_PCT,
        max_order_notional_usdt: float = OKX_MAX_ORDER_NOTIONAL_USDT,
    ) -> None:
        self.mode = str(mode or "").strip().lower()
        if self.mode != "testnet":
            raise ValueError("The Discord-confirmed OKX order flow only supports TRADING_MODE=testnet.")
        self.api_key = str(api_key if api_key is not None else os.getenv("OKX_TESTNET_API_KEY", "")).strip()
        self.secret_key = str(secret_key if secret_key is not None else os.getenv("OKX_TESTNET_SECRET_KEY", "")).strip()
        self.passphrase = str(passphrase if passphrase is not None else os.getenv("OKX_TESTNET_PASSPHRASE", "")).strip()
        self.base_url = str(base_url or OKX_API_BASE_URL).rstrip("/")
        self._request = request or requests.request
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.max_slippage_pct = float(max_slippage_pct)
        self.max_order_notional_usdt = float(max_order_notional_usdt)
        if self.max_slippage_pct < 0 or self.max_slippage_pct > 0.05:
            raise ValueError("OKX_MAX_SLIPPAGE_PCT must be between 0 and 0.05.")
        if self.max_order_notional_usdt <= 0:
            raise ValueError("OKX_MAX_ORDER_NOTIONAL_USDT must be greater than zero.")

    @property
    def configured(self) -> bool:
        return all((self.api_key, self.secret_key, self.passphrase))

    def _timestamp(self) -> str:
        current = self._now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        private: bool = False,
    ) -> dict[str, Any]:
        method = str(method).upper()
        query = urlencode([(key, value) for key, value in (params or {}).items() if value is not None])
        request_path = f"{path}?{query}" if query else path
        body_text = json.dumps(body, ensure_ascii=True, separators=(",", ":")) if body else ""
        headers = {"Content-Type": "application/json", "x-simulated-trading": "1"}
        if private:
            if not self.configured:
                raise OKXClientError("OKX testnet credentials are not configured.")
            timestamp = self._timestamp()
            prehash = f"{timestamp}{method}{request_path}{body_text}"
            signature = base64.b64encode(
                hmac.new(self.secret_key.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha256).digest()
            ).decode("ascii")
            headers.update(
                {
                    "OK-ACCESS-KEY": self.api_key,
                    "OK-ACCESS-SIGN": signature,
                    "OK-ACCESS-TIMESTAMP": timestamp,
                    "OK-ACCESS-PASSPHRASE": self.passphrase,
                }
            )
        try:
            response = self._request(
                method,
                f"{self.base_url}{request_path}",
                headers=headers,
                data=body_text,
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
        except OKXClientError:
            raise
        except Exception as exc:
            raise OKXClientError(f"OKX {method} {path} request failed: {exc}") from exc
        if not isinstance(payload, dict):
            raise OKXClientError("OKX returned an invalid response envelope.")
        if str(payload.get("code", "0")) != "0":
            message = str(payload.get("msg", "unknown OKX error"))
            code = str(payload.get("code", "unknown"))
            raise OKXClientError(f"OKX error {code}: {message}")
        return payload

    def fetch_account_context(self, *, inst_id: str | None = None) -> dict[str, Any]:
        normalized = normalize_inst_id(inst_id) if inst_id else None
        balance = self._request_json("GET", "/api/v5/account/balance", private=True)
        pending = self._request_json(
            "GET",
            "/api/v5/trade/orders-pending",
            params={"instType": "SPOT", "instId": normalized},
            private=True,
        )
        positions = self._request_json(
            "GET",
            "/api/v5/account/positions",
            params={"instId": normalized},
            private=True,
        )
        return {
            "source": "okx_demo_private",
            "as_of_utc": self._timestamp(),
            "account": _account_summary(balance.get("data", [])),
            "balances": _balance_rows(balance.get("data", [])),
            "open_orders": _order_rows(pending.get("data", [])),
            "positions": _position_rows(positions.get("data", [])),
        }

    def fetch_instrument(self, inst_id: str) -> dict[str, Any]:
        normalized = normalize_inst_id(inst_id)
        payload = self._request_json(
            "GET",
            "/api/v5/public/instruments",
            params={"instType": "SPOT", "instId": normalized},
        )
        rows = payload.get("data", [])
        if not rows:
            raise OKXClientError(f"OKX instrument is unavailable: {normalized}")
        instrument = dict(rows[0])
        if str(instrument.get("state", "live")) != "live":
            raise OKXClientError(f"OKX instrument is not live: {normalized}")
        return instrument

    def fetch_market_context(self, inst_id: str, *, depth: int = 20) -> dict[str, Any]:
        normalized = normalize_inst_id(inst_id)
        instrument = self.fetch_instrument(normalized)
        ticker = self._request_json(
            "GET",
            "/api/v5/market/ticker",
            params={"instId": normalized},
        )
        books = self._request_json(
            "GET",
            "/api/v5/market/books",
            params={"instId": normalized, "sz": max(1, min(int(depth), 20))},
        )
        ticker_row = dict((ticker.get("data") or [{}])[0])
        book_row = dict((books.get("data") or [{}])[0])
        return {
            "inst_id": normalized,
            "instrument": {
                key: instrument.get(key)
                for key in ("instId", "baseCcy", "quoteCcy", "tickSz", "lotSz", "minSz", "state")
            },
            "ticker": {
                key: ticker_row.get(key)
                for key in ("last", "bidPx", "askPx", "ts")
            },
            "orderbook": {
                "asks": book_row.get("asks", []),
                "bids": book_row.get("bids", []),
                "ts": book_row.get("ts", ""),
            },
        }

    def normalize_order(
        self,
        order: dict[str, Any],
        *,
        instrument: dict[str, Any],
        market: dict[str, Any],
    ) -> dict[str, Any]:
        side = str(order.get("side", "")).strip().lower()
        ord_type = str(order.get("ord_type", order.get("order_type", ""))).strip().lower()
        size_unit = str(order.get("size_unit", "")).strip().lower()
        if side not in {"buy", "sell"}:
            raise OKXClientError("Order side must be BUY or SELL.")
        if ord_type not in {"market", "limit"}:
            raise OKXClientError("Only MARKET and LIMIT spot orders are supported.")
        if ord_type == "market" and size_unit not in {"base", "quote"}:
            raise OKXClientError("Market size_unit must be base or quote.")
        if ord_type == "limit" and size_unit != "base":
            raise OKXClientError("Limit orders must use base size units.")
        size = _decimal(order.get("size"), field="size")
        max_slippage = Decimal(str(self.max_slippage_pct))
        slippage = Decimal(str(order.get("slippage_pct", self.max_slippage_pct)))
        if not slippage.is_finite() or slippage < 0 or slippage > max_slippage or slippage > Decimal("0.05"):
            raise OKXClientError(f"slippage_pct must be between 0 and {self.max_slippage_pct:g}.")

        lot_size = _decimal(instrument.get("lotSz", "1"), field="lotSz")
        min_size = _decimal(instrument.get("minSz", "0.00000001"), field="minSz")
        tick_size = _decimal(instrument.get("tickSz", "0.00000001"), field="tickSz")
        if ord_type == "limit":
            size = _round_down(size, lot_size)
        elif size_unit == "base":
            size = _round_down(size, lot_size)
        else:
            # OKX's SPOT market-buy quote amount is not the base lot size.
            # Keep a conservative USDT-cent step for quote-sized buys.
            size = _round_down(size, Decimal("0.01"))
        if size <= 0 or (size_unit == "base" and size < min_size):
            raise OKXClientError("Order size is below the instrument minimum after precision rounding.")

        normalized: dict[str, Any] = {
            "inst_id": normalize_inst_id(str(order.get("inst_id", instrument.get("instId", "")))),
            "side": side,
            "ord_type": ord_type,
            "size": _decimal_string(size),
            "size_unit": size_unit,
            "slippage_pct": _decimal_string(slippage),
        }
        if ord_type == "limit":
            price = _round_down(_decimal(order.get("price"), field="price"), tick_size)
            if price <= 0:
                raise OKXClientError("Limit price is below the instrument tick size.")
            normalized["price"] = _decimal_string(price)
        else:
            normalized["price"] = None

        reference_price = _reference_price(market)
        notional = Decimal(normalized["size"]) * (Decimal(normalized["price"]) if normalized["price"] else reference_price)
        if size_unit == "quote" and ord_type == "market":
            notional = Decimal(normalized["size"])
        if notional < Decimal("10"):
            raise OKXClientError("Order notional must be at least 10 USDT.")
        if notional > Decimal(str(self.max_order_notional_usdt)):
            raise OKXClientError(f"Order notional exceeds the {self.max_order_notional_usdt:g} USDT safety cap.")
        normalized["estimated_notional_usdt"] = _decimal_string(notional)
        return normalized

    def estimate_market_slippage(self, order: dict[str, Any], *, market: dict[str, Any]) -> dict[str, Any]:
        if order.get("ord_type") != "market":
            return {"applicable": False, "estimated_slippage_pct": 0.0}
        side = str(order["side"]).lower()
        size = Decimal(str(order["size"]))
        size_unit = str(order["size_unit"]).lower()
        book = market.get("orderbook", {})
        levels = book.get("asks" if side == "buy" else "bids", [])
        bid = _float_or_zero((book.get("bids") or [[0]])[0][0])
        ask = _float_or_zero((book.get("asks") or [[0]])[0][0])
        if bid <= 0 or ask <= 0 or not levels:
            raise OKXClientError("OKX order book is unavailable for slippage estimation.")
        mid = (bid + ask) / 2.0
        remaining_base = size if size_unit == "base" else Decimal("0")
        remaining_quote = size if size_unit == "quote" else Decimal("0")
        consumed_base = Decimal("0")
        consumed_quote = Decimal("0")
        last_price = Decimal("0")
        for level in levels:
            if len(level) < 2:
                continue
            price = _decimal(level[0], field="orderbook price")
            available = _decimal(level[1], field="orderbook size")
            level_quote = price * available
            if remaining_base > 0:
                take_base = min(remaining_base, available)
                consumed_base += take_base
                consumed_quote += take_base * price
                remaining_base -= take_base
            else:
                take_quote = min(remaining_quote, level_quote)
                consumed_quote += take_quote
                consumed_base += take_quote / price
                remaining_quote -= take_quote
            last_price = price
            if remaining_base <= 0 and remaining_quote <= 0:
                break
        if remaining_base > 0 or remaining_quote > 0 or consumed_base <= 0:
            raise OKXClientError("Requested order size exceeds visible order-book liquidity.")
        average = consumed_quote / consumed_base
        estimated = ((average - Decimal(str(mid))) / Decimal(str(mid))) if side == "buy" else ((Decimal(str(mid)) - average) / Decimal(str(mid)))
        return {
            "applicable": True,
            "mid_price": mid,
            "estimated_avg_price": float(average),
            "worst_visible_price": float(last_price),
            "estimated_slippage_pct": max(0.0, float(estimated)),
            "liquidity_sufficient": True,
        }

    def check_limit_price_slippage(self, order: dict[str, Any], *, market: dict[str, Any]) -> None:
        """Reject an immediately marketable limit price beyond our adverse bound."""
        if order.get("ord_type") != "limit":
            return
        book = market.get("orderbook", {})
        bid = Decimal(str((book.get("bids") or [[0]])[0][0]))
        ask = Decimal(str((book.get("asks") or [[0]])[0][0]))
        if bid <= 0 or ask <= 0:
            raise OKXClientError("OKX order book is unavailable for limit-price slippage checks.")
        price = Decimal(str(order["price"]))
        bound = Decimal(str(self.max_slippage_pct))
        side = str(order["side"]).lower()
        if side == "buy" and price > ask * (Decimal("1") + bound):
            raise OKXClientError("Limit BUY price exceeds the configured adverse slippage bound.")
        if side == "sell" and price < bid * (Decimal("1") - bound):
            raise OKXClientError("Limit SELL price exceeds the configured adverse slippage bound.")

    def check_capacity(self, order: dict[str, Any], *, account: dict[str, Any], market: dict[str, Any]) -> None:
        available = {
            str(row.get("ccy", "")).upper(): _float_or_zero(row.get("avail_bal", row.get("availBal", 0)))
            for row in account.get("balances", [])
        }
        side = str(order["side"]).lower()
        inst_id = normalize_inst_id(order["inst_id"])
        base = inst_id.split("-", 1)[0]
        reference = Decimal(str(_reference_price(market)))
        size = Decimal(str(order["size"]))
        if side == "buy":
            required = size if order["size_unit"] == "quote" else size * (Decimal(str(order.get("price") or reference)))
            if available.get("USDT", 0.0) + 1e-9 < float(required):
                raise OKXClientError("Insufficient available USDT balance at confirmation time.")
        else:
            required = size if order["size_unit"] == "base" else size / reference
            if available.get(base, 0.0) + 1e-9 < float(required):
                raise OKXClientError(f"Insufficient available {base} balance at confirmation time.")

    def place_order(self, order: dict[str, Any], *, client_order_id: str, exp_time_ms: int) -> dict[str, Any]:
        body: dict[str, Any] = {
            "instId": normalize_inst_id(order["inst_id"]),
            "tdMode": "cash",
            "clOrdId": client_order_id,
            "side": str(order["side"]).lower(),
            "ordType": str(order["ord_type"]).lower(),
            "sz": str(order["size"]),
            "expTime": str(int(exp_time_ms)),
        }
        if order["ord_type"] == "limit":
            body["px"] = str(order["price"])
        else:
            body["tgtCcy"] = "quote_ccy" if order["size_unit"] == "quote" else "base_ccy"
            body["slippagePct"] = str(order["slippage_pct"])
        payload = self._request_json("POST", "/api/v5/trade/order", body=body, private=True)
        rows = payload.get("data", [])
        if not rows:
            raise OKXClientError("OKX accepted no order result.")
        result = dict(rows[0])
        if str(result.get("sCode", "0")) != "0":
            raise OKXClientError(f"OKX order rejected {result.get('sCode')}: {result.get('sMsg', '')}")
        return {"ord_id": result.get("ordId", ""), "cl_ord_id": result.get("clOrdId", client_order_id), "raw": result}


def _reference_price(market: dict[str, Any]) -> Decimal:
    ticker = market.get("ticker", {})
    for value in (ticker.get("last"), ticker.get("askPx"), ticker.get("bidPx")):
        try:
            price = Decimal(str(value))
            if price > 0:
                return price
        except (InvalidOperation, TypeError, ValueError):
            continue
    book = market.get("orderbook", {})
    bid = Decimal(str((book.get("bids") or [[0]])[0][0]))
    ask = Decimal(str((book.get("asks") or [[0]])[0][0]))
    if bid > 0 and ask > 0:
        return (bid + ask) / 2
    raise OKXClientError("No usable OKX reference price was returned.")


def _account_summary(rows: list[Any]) -> dict[str, Any]:
    row = dict(rows[0]) if rows else {}
    return {key: row.get(key) for key in ("acctLv", "totalEq", "adjEq", "availEq", "uTime")}


def _balance_rows(rows: list[Any]) -> list[dict[str, Any]]:
    details = dict(rows[0]).get("details", []) if rows else []
    output = []
    for detail in details:
        item = {
            "ccy": detail.get("ccy", ""),
            "equity": detail.get("eq", detail.get("cashBal", "0")),
            "avail_bal": detail.get("availBal", detail.get("cashBal", "0")),
            "frozen_bal": detail.get("frozenBal", "0"),
        }
        if any(_float_or_zero(item[key]) != 0 for key in ("equity", "avail_bal", "frozen_bal")):
            output.append(item)
    return output


def _order_rows(rows: list[Any]) -> list[dict[str, Any]]:
    fields = ("ordId", "clOrdId", "instId", "side", "ordType", "sz", "px", "accFillSz", "avgPx", "state", "uTime")
    return [{key: row.get(key, "") for key in fields} for row in rows]


def _position_rows(rows: list[Any]) -> list[dict[str, Any]]:
    fields = ("instId", "posSide", "pos", "availPos", "avgPx", "markPx", "upl", "uplRatio", "liqPx", "uTime")
    output = []
    for row in rows:
        item = {key: row.get(key, "") for key in fields}
        if _float_or_zero(item.get("pos")) != 0:
            output.append(item)
    return output
