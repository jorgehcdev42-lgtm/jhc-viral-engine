"""RSS feed source adapter for JHC Viral Engine.

Fetches and parses RSS/Atom feeds from public sources.
Uses only stdlib (xml.etree + urllib) to avoid heavy dependencies.
Falls back gracefully on network errors.
"""

from __future__ import annotations

import hashlib
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

logger = logging.getLogger(__name__)

# Common RSS/Atom namespaces
NAMESPACES = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
}


@dataclass(frozen=True)
class NewsItem:
    """Single news item from a research source."""
    title: str
    url: str
    source: str
    published_at: Optional[datetime] = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    summary: str = ""
    category: str = "news"
    relevance_score: float = 0.0
    freshness_hours: float = 0.0
    confidence: float = 0.0
    verification_state: str = "unverified"
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.content_hash:
            raw = f"{self.title}|{self.url}|{self.summary}"
            object.__setattr__(
                self, "content_hash",
                hashlib.sha256(raw.encode()).hexdigest()[:16],
            )
        if self.published_at and self.freshness_hours == 0.0:
            delta = datetime.now(timezone.utc) - self.published_at
            object.__setattr__(self, "freshness_hours", max(0.0, delta.total_seconds() / 3600))


def _parse_date(text: Optional[str]) -> Optional[datetime]:
    """Best-effort date parsing for RSS/Atom date formats."""
    if not text:
        return None
    text = text.strip()
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",      # RFC 822
        "%a, %d %b %Y %H:%M:%S %Z",      # RFC 822 variant
        "%Y-%m-%dT%H:%M:%S%z",           # ISO 8601
        "%Y-%m-%dT%H:%M:%SZ",            # ISO 8601 UTC
        "%Y-%m-%d %H:%M:%S",             # Simple
        "%Y-%m-%d",                       # Date only
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    logger.debug("Could not parse date: %s", text[:50])
    return None


def _strip_html(text: str) -> str:
    """Remove HTML tags from text (simple regex-free approach)."""
    result: list[str] = []
    in_tag = False
    for char in text:
        if char == "<":
            in_tag = True
        elif char == ">":
            in_tag = False
        elif not in_tag:
            result.append(char)
    return " ".join("".join(result).split())


def fetch_rss(url: str, source_name: str, timeout: int = 15) -> list[NewsItem]:
    """Fetch and parse an RSS/Atom feed. Returns empty list on failure."""
    try:
        req = Request(url, headers={"User-Agent": "JHC-ViralEngine/0.1"})
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    except (URLError, OSError, TimeoutError) as exc:
        logger.warning("Failed to fetch RSS %s: %s", url, exc)
        return []

    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        logger.warning("Failed to parse RSS XML from %s: %s", url, exc)
        return []

    items: list[NewsItem] = []

    # Try RSS 2.0 format
    channel = root.find("channel")
    if channel is not None:
        for item_el in channel.findall("item"):
            title = (item_el.findtext("title") or "").strip()
            link = (item_el.findtext("link") or "").strip()
            desc = _strip_html(item_el.findtext("description") or "")
            pub_date = _parse_date(
                item_el.findtext("pubDate")
                or item_el.findtext("{http://purl.org/dc/elements/1.1/}date")
            )
            category = (item_el.findtext("category") or "news").strip().lower()

            if title and link:
                items.append(NewsItem(
                    title=title,
                    url=link,
                    source=source_name,
                    published_at=pub_date,
                    summary=desc[:500],
                    category=category,
                ))

    # Try Atom format
    if not items:
        for entry in root.findall("{http://www.w3.org/2005/Atom}entry"):
            title = (entry.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
            link_el = entry.find("{http://www.w3.org/2005/Atom}link")
            link = link_el.get("href", "") if link_el is not None else ""
            summary = _strip_html(
                entry.findtext("{http://www.w3.org/2005/Atom}summary")
                or entry.findtext("{http://www.w3.org/2005/Atom}content")
                or ""
            )
            pub_date = _parse_date(
                entry.findtext("{http://www.w3.org/2005/Atom}published")
                or entry.findtext("{http://www.w3.org/2005/Atom}updated")
            )

            if title and link:
                items.append(NewsItem(
                    title=title,
                    url=link,
                    source=source_name,
                    published_at=pub_date,
                    summary=summary[:500],
                ))

    logger.info("Fetched %d items from %s (%s)", len(items), source_name, url)
    return items


class NewsStore:
    """Persistent deduplicated news storage using JSON files."""

    def __init__(self, data_root: Path, profile_id: str) -> None:
        self.store_path = data_root / profile_id / "research" / "news_store.json"
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self._items: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.store_path.exists():
            import json
            try:
                self._items = json.loads(self.store_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._items = {}

    def _save(self) -> None:
        import json
        self.store_path.write_text(
            json.dumps(self._items, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    def add_items(self, items: list[NewsItem]) -> int:
        """Add items, deduplicating by content_hash. Returns count of new items."""
        new_count = 0
        for item in items:
            if item.content_hash not in self._items:
                self._items[item.content_hash] = {
                    "title": item.title,
                    "url": item.url,
                    "source": item.source,
                    "published_at": item.published_at.isoformat() if item.published_at else None,
                    "fetched_at": item.fetched_at.isoformat(),
                    "summary": item.summary,
                    "category": item.category,
                    "relevance_score": item.relevance_score,
                    "freshness_hours": item.freshness_hours,
                    "confidence": item.confidence,
                    "verification_state": item.verification_state,
                }
                new_count += 1
        if new_count > 0:
            self._save()
        return new_count

    def get_all(self) -> list[dict]:
        return list(self._items.values())

    def count(self) -> int:
        return len(self._items)

    def has_hash(self, content_hash: str) -> bool:
        return content_hash in self._items