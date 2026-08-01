"""Public market snapshots for the analyst runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

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


FULL_ANALYSIS_INTERVALS = (("5m", "5m"), ("15m", "15m"), ("1h", "1H"), ("4h", "4H"), ("1d", "1D"))
SCREENING_INTERVALS = (("5m", "5m"), ("15m", "15m"), ("1h", "1H"))


def fetch_public_snapshot(symbol: str, *, timeout_secs: float = 10.0) -> dict[str, Any]:
    """Build the richer multi-timeframe evidence packet used by strong analysis."""
    return _build_snapshot(symbol, intervals=FULL_ANALYSIS_INTERVALS, limit=120, timeout_secs=timeout_secs)


def fetch_screening_snapshot(symbol: str, *, timeout_secs: float = 10.0) -> dict[str, Any]:
    """Build the smaller packet polled by the 15-second weak-model lane."""
    return _build_snapshot(symbol, intervals=SCREENING_INTERVALS, limit=60, timeout_secs=timeout_secs)


def _build_snapshot(
    symbol: str,
    *,
    intervals: Iterable[tuple[str, str]],
    limit: int,
    timeout_secs: float,
) -> dict[str, Any]:
    normalized = str(symbol or "BTCUSDT").upper()
    inst_id = OKX_SYMBOL_MAP.get(normalized, normalized.replace("USDT", "-USDT"))
    timeframes = {
        label: _summarize_candles(
            _fetch_okx_candles(inst_id=inst_id, bar=bar, limit=limit, timeout_secs=timeout_secs)
        )
        for label, bar in intervals
    }
    return {
        "source": "okx_public",
        "symbol": normalized,
        "inst_id": inst_id,
        "asof_utc": datetime.now(timezone.utc).isoformat(),
        "timeframes": timeframes,
        # Compatibility keys for older prompt/tests.
        "one_hour": timeframes.get("1h", {"available": False}),
        "fifteen_minute": timeframes.get("15m", {"available": False}),
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
    complete = [row for row in candles if len(row) < 9 or str(row[8]) == "1"]
    rows = complete or candles
    closes = [float(row[4]) for row in rows]
    highs = [float(row[2]) for row in rows]
    lows = [float(row[3]) for row in rows]
    volumes = [float(row[5]) for row in rows]
    first = closes[0]
    last = closes[-1]
    sma20 = _mean(closes[-20:]) if len(closes) >= 20 else None
    ema50 = _ema(closes, 50)
    rsi14 = _rsi(closes, 14)
    atr14 = _atr(rows, 14)
    volume_baseline = _mean(volumes[-21:-1]) if len(volumes) >= 21 else None
    last_volume = volumes[-1]
    return {
        "available": True,
        "bars": len(rows),
        "last_close": last,
        "window_return_pct": ((last / first) - 1.0) * 100.0 if first else 0.0,
        "range_high": max(highs),
        "range_low": min(lows),
        "last_closed_ms": int(float(rows[-1][0])),
        "current_candle_complete": bool(len(candles[-1]) < 9 or str(candles[-1][8]) == "1"),
        "sma20": sma20,
        "ema50": ema50,
        "rsi14": rsi14,
        "atr14": atr14,
        "atr_pct": (atr14 / last * 100.0) if atr14 is not None and last else None,
        "volume_ratio_20": (last_volume / volume_baseline) if volume_baseline else None,
        "trend_state": _trend_state(last=last, sma20=sma20, ema50=ema50, closes=closes),
        "levels": _price_levels(rows, last=last),
        "last_candle": _candle_geometry(rows[-1]),
    }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    value = _mean(values[:period])
    multiplier = 2.0 / (period + 1.0)
    for current in values[period:]:
        value = (current - value) * multiplier + value
    return value


def _rsi(values: list[float], period: int) -> float | None:
    if len(values) <= period:
        return None
    changes = [current - previous for previous, current in zip(values, values[1:])]
    gains = [max(change, 0.0) for change in changes[-period:]]
    losses = [max(-change, 0.0) for change in changes[-period:]]
    average_gain = _mean(gains)
    average_loss = _mean(losses)
    if average_loss == 0.0:
        return 100.0 if average_gain > 0.0 else 50.0
    return 100.0 - (100.0 / (1.0 + average_gain / average_loss))


def _atr(rows: list[list[str]], period: int) -> float | None:
    if len(rows) <= period:
        return None
    ranges: list[float] = []
    for previous, current in zip(rows, rows[1:]):
        high = float(current[2])
        low = float(current[3])
        previous_close = float(previous[4])
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    return _mean(ranges[-period:])


def _trend_state(*, last: float, sma20: float | None, ema50: float | None, closes: list[float]) -> str:
    if sma20 is None or ema50 is None or len(closes) < 10:
        return "UNKNOWN"
    slope = closes[-1] - closes[-10]
    if last > sma20 > ema50 and slope > 0:
        return "UPTREND"
    if last < sma20 < ema50 and slope < 0:
        return "DOWNTREND"
    return "RANGE_OR_TRANSITION"


def _price_levels(rows: list[list[str]], *, last: float) -> list[dict[str, Any]]:
    if len(rows) < 5:
        return []
    pivots: list[tuple[str, float]] = []
    for index in range(2, len(rows) - 2):
        low = float(rows[index][3])
        high = float(rows[index][2])
        if all(low <= float(rows[other][3]) for other in (index - 2, index - 1, index + 1, index + 2)):
            pivots.append(("SUPPORT", low))
        if all(high >= float(rows[other][2]) for other in (index - 2, index - 1, index + 1, index + 2)):
            pivots.append(("RESISTANCE", high))
    tolerance = max(last * 0.0025, 1e-9)
    clusters: list[dict[str, Any]] = []
    for kind, price in pivots:
        match = next((item for item in clusters if item["kind"] == kind and abs(item["price"] - price) <= tolerance), None)
        if match:
            touches = int(match["touches"])
            match["price"] = (float(match["price"]) * touches + price) / (touches + 1)
            match["touches"] = touches + 1
        else:
            clusters.append({"kind": kind, "price": price, "touches": 1})
    # A pivot keeps its original structural meaning only while price remains on
    # the expected side of it. Filtering here prevents a broken support above
    # spot (or broken resistance below spot) from misleading the analyst.
    supports = sorted(
        (item for item in clusters if item["kind"] == "SUPPORT" and float(item["price"]) <= last),
        key=lambda item: abs(last - float(item["price"])),
    )[:3]
    resistances = sorted(
        (item for item in clusters if item["kind"] == "RESISTANCE" and float(item["price"]) >= last),
        key=lambda item: abs(last - float(item["price"])),
    )[:3]
    return sorted([*supports, *resistances], key=lambda item: float(item["price"]))


def _candle_geometry(row: list[str]) -> dict[str, float | str]:
    open_price, high, low, close = (float(row[index]) for index in (1, 2, 3, 4))
    candle_range = max(high - low, 1e-12)
    body_high = max(open_price, close)
    body_low = min(open_price, close)
    return {
        "direction": "BULLISH" if close > open_price else "BEARISH" if close < open_price else "DOJI",
        "body_fraction": abs(close - open_price) / candle_range,
        "upper_wick_fraction": (high - body_high) / candle_range,
        "lower_wick_fraction": (body_low - low) / candle_range,
        "close_location": (close - low) / candle_range,
    }
