"""Public crypto-news snapshots for analyst prompts and Discord."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree

import requests

NEWS_FEEDS = (
    ("coindesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("cointelegraph", "https://cointelegraph.com/rss"),
    ("decrypt", "https://decrypt.co/feed"),
)


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    published_at: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def fetch_crypto_news(*, symbol: str = "ALL", limit: int = 8, timeout_secs: float = 10.0) -> list[dict[str, str]]:
    """Fetch a small multi-source public crypto-news snapshot.

    This deliberately avoids paid or key-bearing news APIs. The snapshot is
    bounded so it can be safely included in the analyst LLM prompt.
    """
    items: list[NewsItem] = []
    for source, url in NEWS_FEEDS:
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "tradingbot-analyst/1.0"},
                timeout=timeout_secs,
            )
            response.raise_for_status()
            items.extend(_parse_rss(response.text, source=source))
        except Exception:
            continue

    filtered = _filter_items(_dedupe(items), symbol=symbol)
    filtered.sort(key=lambda item: item.published_at, reverse=True)
    return [item.to_dict() for item in filtered[: max(1, int(limit))]]


def build_news_snapshot(*, symbol: str = "ALL", limit: int = 8) -> dict[str, Any]:
    try:
        items = fetch_crypto_news(symbol=symbol, limit=limit)
        return {
            "status": "ok",
            "source": "public_crypto_rss",
            "items": items,
            "note": "Public RSS headlines from CoinDesk, Cointelegraph, and Decrypt.",
        }
    except Exception as exc:
        return {
            "status": "error",
            "source": "public_crypto_rss",
            "items": [],
            "error": str(exc),
        }


def _parse_rss(raw_xml: str, *, source: str) -> list[NewsItem]:
    root = ElementTree.fromstring(raw_xml.encode("utf-8"))
    out: list[NewsItem] = []
    for item in root.findall(".//item"):
        title = _node_text(item, "title")
        link = _node_text(item, "link")
        published_raw = _node_text(item, "pubDate")
        if not title or not link:
            continue
        out.append(
            NewsItem(
                title=_clean(title),
                url=_clean(link),
                source=source,
                published_at=_normalize_pubdate(published_raw),
            )
        )
    return out


def _node_text(item: ElementTree.Element, tag: str) -> str:
    node = item.find(tag)
    if node is None or node.text is None:
        return ""
    return node.text


def _clean(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_pubdate(value: str) -> str:
    if not value:
        return ""
    try:
        return parsedate_to_datetime(value).isoformat()
    except Exception:
        return value


def _dedupe(items: list[NewsItem]) -> list[NewsItem]:
    seen: set[str] = set()
    out: list[NewsItem] = []
    for item in items:
        key = item.url or item.title.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _filter_items(items: list[NewsItem], *, symbol: str) -> list[NewsItem]:
    normalized = str(symbol or "ALL").upper()
    if normalized in {"ALL", ""}:
        return items
    asset = normalized.replace("USDT", "").replace("-USDT", "")
    aliases = {
        "BTC": {"BTC", "BITCOIN"},
        "ETH": {"ETH", "ETHER", "ETHEREUM"},
    }.get(asset, {asset})
    filtered = [item for item in items if any(alias in item.title.upper() for alias in aliases)]
    return filtered or items


def format_news_message(snapshot_or_items: dict[str, Any] | list[dict[str, Any]], *, symbol: str) -> str:
    if isinstance(snapshot_or_items, dict):
        items = list(snapshot_or_items.get("items", []))
    else:
        items = list(snapshot_or_items)
    if not items:
        return f"No recent public crypto news found for {symbol.upper()}."
    lines = [f"Latest public crypto news for {symbol.upper()}:"]
    for idx, item in enumerate(items, 1):
        source = item.get("source", "news")
        title = item.get("title", "Untitled")
        url = item.get("url", "")
        lines.append(f"{idx}. [{source}] {title} - {url}")
    return "\n".join(lines)
