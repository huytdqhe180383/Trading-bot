"""OKX-sourced public announcement snapshots for analyst news."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, asdict
from typing import Any

import requests

OKX_ANNOUNCEMENTS_URL = "https://www.okx.com/help/section/announcements-latest-announcements"


@dataclass
class NewsItem:
    title: str
    url: str
    source: str = "okx_announcements"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def fetch_okx_announcements(*, symbol: str = "ALL", limit: int = 5, timeout_secs: float = 10.0) -> list[dict[str, str]]:
    """Fetch recent OKX Help Center announcements.

    OKX exposes trading/market APIs, but not a documented general crypto-news
    API. For OKX-sourced news, use their public announcements page.
    """
    response = requests.get(
        OKX_ANNOUNCEMENTS_URL,
        headers={"User-Agent": "tradingbot-analyst/1.0"},
        timeout=timeout_secs,
    )
    response.raise_for_status()
    items = _parse_okx_announcement_html(response.text)
    filtered = _filter_items(items, symbol=symbol)
    return [item.to_dict() for item in filtered[: max(1, int(limit))]]


def _parse_okx_announcement_html(raw_html: str) -> list[NewsItem]:
    article_pattern = re.compile(
        r'<li class="index_articleItem__[^>]*>\s*'
        r'<a href="(?P<href>/help/[^"]+)".*?'
        r'<div class="[^"]*index_articleTitle__[^"]*">(?P<title>.*?)</div>.*?'
        r'Published on (?P<date>[^<]+)</span>',
        re.IGNORECASE | re.DOTALL,
    )
    seen: set[str] = set()
    items: list[NewsItem] = []
    for match in article_pattern.finditer(raw_html):
        href = html.unescape(match.group("href")).strip()
        title = _clean_title(match.group("title"))
        if _skip_title(title) or href in seen:
            continue
        seen.add(href)
        items.append(NewsItem(title=f"{title} ({match.group('date').strip()})", url=f"https://www.okx.com{href}"))
    if items:
        return items

    pattern = re.compile(r'href="(?P<href>/help/[^"]+)"[^>]*>(?P<title>[^<]{8,160})</a>', re.IGNORECASE)
    for match in pattern.finditer(raw_html):
        href = html.unescape(match.group("href")).strip()
        title = _clean_title(match.group("title"))
        if _skip_title(title) or href in seen:
            continue
        seen.add(href)
        items.append(NewsItem(title=title, url=f"https://www.okx.com{href}"))
    if items:
        return items

    # Next.js pages can hide content in JSON blobs; this fallback catches the
    # same help article paths with nearby title strings without depending on a
    # private OKX API.
    blob_pattern = re.compile(r'"title"\s*:\s*"(?P<title>[^"]{8,160})".{0,500}?"url"\s*:\s*"(?P<href>/help/[^"]+)"')
    for match in blob_pattern.finditer(raw_html):
        href = html.unescape(match.group("href")).strip()
        title = html.unescape(match.group("title")).strip()
        if href and href not in seen:
            seen.add(href)
            items.append(NewsItem(title=title, url=f"https://www.okx.com{href}"))
    return items


def _clean_title(value: str) -> str:
    title = re.sub(r"<[^>]+>", "", value)
    title = html.unescape(title).strip()
    return re.sub(r"\s+", " ", title)


def _skip_title(title: str) -> bool:
    if not title:
        return True
    generic = {"announcements", "latest announcements", "api announcements"}
    return title.strip().lower() in generic


def _filter_items(items: list[NewsItem], *, symbol: str) -> list[NewsItem]:
    normalized = str(symbol or "ALL").upper()
    if normalized in {"ALL", ""}:
        return items
    tokens = {normalized, normalized.replace("USDT", ""), normalized.replace("-USDT", "")}
    filtered = [item for item in items if any(token and token in item.title.upper() for token in tokens)]
    return filtered or items


def format_news_message(items: list[dict[str, Any]], *, symbol: str) -> str:
    if not items:
        return f"No recent OKX announcements found for {symbol.upper()}."
    lines = [f"Latest OKX announcements for {symbol.upper()}:"]
    for idx, item in enumerate(items, 1):
        lines.append(f"{idx}. {item.get('title', 'Untitled')} - {item.get('url', '')}")
    return "\n".join(lines)
