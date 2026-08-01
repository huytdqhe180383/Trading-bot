"""Public news snapshots for Discord and the operator-facing news layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from email.utils import parsedate_to_datetime
import re
from typing import Any, Callable
from xml.etree import ElementTree

import requests
from config import (
    X_NEWS_ACCOUNTS,
    X_NEWS_API_BASE_URL,
    X_NEWS_BEARER_TOKEN,
    X_NEWS_POSTS_PER_ACCOUNT,
)

NEWS_FEEDS = (
    ("coindesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("cointelegraph", "https://cointelegraph.com/rss"),
    ("decrypt", "https://decrypt.co/feed"),
)
X_ACCOUNT_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,15}$")
X_POST_FIELDS = "created_at,referenced_tweets"
_x_user_id_cache: dict[str, str] = {}


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    published_at: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def fetch_crypto_news(*, symbol: str = "ALL", limit: int = 8, timeout_secs: float = 10.0) -> list[dict[str, str]]:
    """Fetch RSS headlines plus configured official-X alert posts.

    X posts are only fetched through the authenticated X API when a bearer token
    is configured. They remain alerts: an official release website is still the
    source of record for actual economic values and revisions.
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

    items.extend(
        NewsItem(**item)
        for item in fetch_x_official_posts(
            bearer_token=X_NEWS_BEARER_TOKEN,
            accounts=X_NEWS_ACCOUNTS,
            posts_per_account=X_NEWS_POSTS_PER_ACCOUNT,
            api_base_url=X_NEWS_API_BASE_URL,
            timeout_secs=timeout_secs,
        )
    )

    filtered = _filter_items(_dedupe(items), symbol=symbol)
    filtered.sort(key=lambda item: item.published_at, reverse=True)
    return [item.to_dict() for item in filtered[: max(1, int(limit))]]


def build_news_snapshot(*, symbol: str = "ALL", limit: int = 8) -> dict[str, Any]:
    try:
        items = fetch_crypto_news(symbol=symbol, limit=limit)
        return {
            "status": "ok",
            "source": "public_crypto_rss+x_official" if X_NEWS_BEARER_TOKEN else "public_crypto_rss",
            "items": items,
            "note": _news_source_note(),
        }
    except Exception as exc:
        return {
            "status": "error",
            "source": "public_crypto_rss",
            "items": [],
            "error": str(exc),
        }


def fetch_x_official_posts(
    *,
    bearer_token: str,
    accounts: tuple[str, ...] | list[str],
    posts_per_account: int = 2,
    api_base_url: str = "https://api.x.com/2",
    timeout_secs: float = 10.0,
    request_get: Callable[..., Any] = requests.get,
) -> list[dict[str, str]]:
    """Fetch recent original posts from configured official X accounts.

    The function intentionally uses the documented X API rather than scraping
    web pages. Individual account failures are isolated so RSS remains useful
    during API, entitlement, or rate-limit failures.
    """
    token = str(bearer_token or "").strip()
    if not token:
        return []

    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "btc-eth-trading-news/1.0",
    }
    normalized_accounts = _normalize_x_accounts(accounts)
    base_url = str(api_base_url or "https://api.x.com/2").rstrip("/")
    requested_posts = max(1, min(100, int(posts_per_account)))
    # The X endpoint requires at least five results, but the news layer should
    # remain small. Fetch the minimum accepted page and keep the requested cap.
    max_results = max(5, requested_posts)
    items: list[NewsItem] = []

    for account in normalized_accounts:
        try:
            user_id = _lookup_x_user_id(
                account=account,
                api_base_url=base_url,
                headers=headers,
                timeout_secs=timeout_secs,
                request_get=request_get,
            )
            response = request_get(
                f"{base_url}/users/{user_id}/tweets",
                params={
                    "max_results": max_results,
                    "tweet.fields": X_POST_FIELDS,
                    "exclude": "retweets,replies",
                },
                headers=headers,
                timeout=timeout_secs,
            )
            response.raise_for_status()
            for post in response.json().get("data", [])[:requested_posts]:
                item = _x_post_to_news_item(post, account=account)
                if item is not None:
                    items.append(item)
        except Exception:
            continue

    return [item.to_dict() for item in _dedupe(items)]


def _lookup_x_user_id(
    *,
    account: str,
    api_base_url: str,
    headers: dict[str, str],
    timeout_secs: float,
    request_get: Callable[..., Any],
) -> str:
    cached = _x_user_id_cache.get(account)
    if cached:
        return cached
    response = request_get(
        f"{api_base_url}/users/by/username/{account}",
        headers=headers,
        timeout=timeout_secs,
    )
    response.raise_for_status()
    user_id = str(response.json().get("data", {}).get("id", "")).strip()
    if not user_id:
        raise ValueError(f"X user lookup returned no id for @{account}.")
    _x_user_id_cache[account] = user_id
    return user_id


def _x_post_to_news_item(post: Any, *, account: str) -> NewsItem | None:
    if not isinstance(post, dict):
        return None
    post_id = str(post.get("id", "")).strip()
    text = _clean(str(post.get("text", "")))
    if not post_id or not text:
        return None
    return NewsItem(
        title=text,
        url=f"https://x.com/{account}/status/{post_id}",
        source=f"x:@{account}",
        published_at=str(post.get("created_at", "")).strip(),
    )


def _normalize_x_accounts(accounts: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_account in accounts:
        account = str(raw_account or "").strip().removeprefix("@").lower()
        if not X_ACCOUNT_PATTERN.fullmatch(account) or account in seen:
            continue
        seen.add(account)
        normalized.append(account)
    return tuple(normalized)


def _news_source_note() -> str:
    rss_note = "Public RSS headlines from CoinDesk, Cointelegraph, and Decrypt."
    if not X_NEWS_BEARER_TOKEN:
        return f"{rss_note} Official X alert posts are disabled until X_NEWS_BEARER_TOKEN is configured."
    return (
        f"{rss_note} Recent original posts from configured official X accounts are alert-only; "
        "verify releases and revisions on the issuer's website."
    )


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
        return f"No recent public news or official alerts found for {symbol.upper()}."
    lines = [f"Latest public news and official alerts for {symbol.upper()}:"]
    for idx, item in enumerate(items, 1):
        source = item.get("source", "news")
        title = item.get("title", "Untitled")
        url = item.get("url", "")
        lines.append(f"{idx}. [{source}] {title} - {url}")
    return "\n".join(lines)
