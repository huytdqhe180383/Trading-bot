"""Public market snapshots for the analyst runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

OKX_SYMBOL_MAP = {
    "BTCUSDT": "BTC-USDT",
    "ETHUSDT": "ETH-USDT",
}


def fetch_public_snapshot(symbol: str, *, timeout_secs: float = 10.0) -> dict[str, Any]:
    normalized = str(symbol or "BTCUSDT").upper()
    inst_id = OKX_SYMBOL_MAP.get(normalized, normalized.replace("USDT", "-USDT"))
    candles_1h = _fetch_okx_candles(inst_id=inst_id, bar="1H", limit=25, timeout_secs=timeout_secs)
    candles_15m = _fetch_okx_candles(inst_id=inst_id, bar="15m", limit=5, timeout_secs=timeout_secs)
    return {
        "source": "okx_public",
        "symbol": normalized,
        "inst_id": inst_id,
        "asof_utc": datetime.now(timezone.utc).isoformat(),
        "one_hour": _summarize_candles(candles_1h),
        "fifteen_minute": _summarize_candles(candles_15m),
    }


def _fetch_okx_candles(*, inst_id: str, bar: str, limit: int, timeout_secs: float) -> list[list[str]]:
    response = requests.get(
        "https://www.okx.com/api/v5/market/candles",
        params={"instId": inst_id, "bar": bar, "limit": int(limit)},
        timeout=timeout_secs,
    )
    response.raise_for_status()
    data = response.json()
    if str(data.get("code")) != "0":
        raise RuntimeError(f"OKX public candles failed: {data.get('msg', data.get('code'))}")
    return list(reversed(data.get("data", [])))


def _summarize_candles(candles: list[list[str]]) -> dict[str, Any]:
    if not candles:
        return {"available": False}
    closes = [float(row[4]) for row in candles]
    first = closes[0]
    last = closes[-1]
    return {
        "available": True,
        "bars": len(candles),
        "last_close": last,
        "window_return_pct": ((last / first) - 1.0) * 100.0 if first else 0.0,
        "last_closed_ms": int(float(candles[-1][0])),
    }
