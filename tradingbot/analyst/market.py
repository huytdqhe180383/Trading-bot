"""Public market snapshots for the analyst runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

OKX_SYMBOL_MAP = {
    "BTCUSDT": "BTC-USDT",
    "ETHUSDT": "ETH-USDT",
}
OKX_INTERVAL_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1H",
    "4h": "4H",
    "1d": "1D",
}
MAX_CHART_CANDLES = 1000


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


def fetch_public_candles(
    symbol: str,
    *,
    interval: str = "1h",
    limit: int = 500,
    timeout_secs: float = 10.0,
) -> list[dict[str, float | int | str]]:
    """Fetch normalized public OHLCV candles for charting.

    This intentionally uses OKX public market data only. It does not require or
    touch private exchange credentials.
    """
    normalized = str(symbol or "BTCUSDT").upper()
    if normalized not in OKX_SYMBOL_MAP:
        raise ValueError("Unsupported symbol. Supported symbols: BTCUSDT, ETHUSDT.")

    normalized_interval = str(interval or "1h").strip()
    okx_bar = OKX_INTERVAL_MAP.get(normalized_interval)
    if not okx_bar:
        raise ValueError("Unsupported interval. Supported intervals: 1m, 5m, 15m, 1h, 4h, 1d.")

    bounded_limit = max(1, min(int(limit), MAX_CHART_CANDLES))
    rows = _fetch_okx_candles(
        inst_id=OKX_SYMBOL_MAP[normalized],
        bar=okx_bar,
        limit=bounded_limit,
        timeout_secs=timeout_secs,
    )
    candles: list[dict[str, float | int | str]] = []
    for row in rows:
        if len(row) < 6:
            continue
        timestamp_ms = int(float(row[0]))
        candles.append(
            {
                "time": timestamp_ms // 1000,
                "timestamp_ms": timestamp_ms,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
                "symbol": normalized,
                "source": "okx_public",
            }
        )
    return candles


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
