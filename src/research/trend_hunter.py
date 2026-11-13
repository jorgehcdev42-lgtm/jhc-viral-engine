"""Trend hunting and topic validation for JHC Viral Engine.

Searches multiple sources to find trending topics, validates them
against profile editorial guidelines, and scores by engagement potential.
Integrates RSS feeds via stdlib-only rss_source module.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.core.profile_config import ProfileConfig
from src.research.rss_source import fetch_rss, NewsStore, NewsItem

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TopicValidation:
    """Result of validating a content topic."""
    is_valid: bool
    reason: str = ""
    confidence: float = 0.0
    sources_checked: int = 0


@dataclass(frozen=True)
class TrendingTopic:
    """A discovered trending topic with metadata."""
    title: str
    source: str
    url: str
    relevance_score: float
    freshness_hours: float
    engagement_potential: str  # low/medium/high/viral
    summary: str = ""
    category: str = "news"
    verification_state: str = "unverified"
    confidence: float = 0.0


# Known official GTA 6 / Rockstar RSS feeds
DEFAULT_RSS_FEEDS: dict[str, tuple[tuple[str, str], ...]] = {
    "gta6": (
        ("Eurogamer", "https://www.eurogamer.net/?format=rss"),
        ("VGC", "https://www.videogameschronicle.com/feed"),
        # Rockstar Newswire feed returns 404 as of 2026-11; kept for reference
        # ("Rockstar Newswire", "https://www.rockstargames.com/newswire/feed"),
    ),
    "marvel-dc": (),
}


class TrendHunter:
    """Discovers and validates trending topics for a specific profile."""

    def __init__(self, profile: ProfileConfig, data_root: Path | str = "data") -> None:
        self.profile = profile
        self.data_root = Path(data_root)
        self.store = NewsStore(self.data_root, profile.profile_id)

    async def validate_topic(self, topic: str) -> TopicValidation:
        """Check if a topic is suitable for this profile's editorial guidelines."""
        if not topic or len(topic.strip()) < 3:
            return TopicValidation(is_valid=False, reason="Topic too short")

        # Check against banned topics FIRST (before keyword matching)
        topic_lower = topic.lower()
        for banned in self.profile.editorial.banned_topics:
            if banned.lower() in topic_lower:
                return TopicValidation(
                    is_valid=False,
                    reason=f"Topic matches banned pattern: {banned}",
                    sources_checked=0,
                )

        # Check keyword relevance
        keywords = [k.lower() for k in self.profile.research_sources.keywords]
        matched = sum(1 for kw in keywords if kw in topic_lower)
        if matched == 0 and keywords:
            return TopicValidation(
                is_valid=False,
                reason="No keyword match with profile research sources",
                confidence=0.0,
                sources_checked=len(keywords),
            )

        confidence = min(1.0, matched / max(len(keywords), 1))
        return TopicValidation(
            is_valid=True,
            reason=f"Matched {matched} keywords",
            confidence=confidence,
            sources_checked=len(keywords),
        )

    async def discover_trends(self, limit: int = 10) -> list[TrendingTopic]:
        """Discover trending topics from configured RSS feeds.

        Fetches real RSS feeds, deduplicates via NewsStore,
        scores by freshness and keyword relevance.
        Returns empty list only on total network failure.
        """
        profile_id = self.profile.profile_id
        feeds = DEFAULT_RSS_FEEDS.get(profile_id, ())

        # Also include any RSS feeds configured in the profile
        for feed_url in self.profile.research_sources.rss_feeds:
            # Avoid duplicates
            existing_urls = {f[1] for f in feeds}
            if feed_url not in existing_urls:
                feeds = feeds + ((f"{profile_id}-custom", feed_url),)

        if not feeds:
            logger.warning("No RSS feeds configured for profile %s", profile_id)
            return []

        all_items: list[NewsItem] = []
        for source_name, feed_url in feeds:
            items = fetch_rss(feed_url, source_name)
            all_items.extend(items)

        if not all_items:
            logger.warning("All RSS fetches failed for profile %s", profile_id)
            return []

        # Deduplicate and persist
        new_count = self.store.add_items(all_items)
        logger.info(
            "Fetched %d items (%d new) for profile %s",
            len(all_items), new_count, profile_id,
        )

        # Score and rank
        scored: list[TrendingTopic] = []
        keywords = [k.lower() for k in self.profile.research_sources.keywords]

        for item in all_items:
            title_lower = item.title.lower()
            keyword_matches = sum(1 for kw in keywords if kw in title_lower)
            relevance = min(1.0, keyword_matches / max(len(keywords), 1))

            # Freshness bonus: newer = higher score
            freshness = item.freshness_hours
            if freshness <= 24:
                freshness_score = 1.0
            elif freshness <= 72:
                freshness_score = 0.7
            elif freshness <= 168:  # 1 week
                freshness_score = 0.4
            else:
                freshness_score = 0.1

            combined_score = (relevance * 0.6) + (freshness_score * 0.4)

            # Determine engagement potential
            if combined_score >= 0.8:
                potential = "viral"
            elif combined_score >= 0.5:
                potential = "high"
            elif combined_score >= 0.3:
                potential = "medium"
            else:
                potential = "low"

            # Classify content type
            category = item.category
            title_l = item.title.lower()
            if any(w in title_l for w in ("trailer", "reveal", "announce")):
                category = "announcement"
            elif any(w in title_l for w in ("leak", "rumor", "speculation")):
                category = "rumor"
            elif any(w in title_l for w in ("guide", "tip", "how to")):
                category = "guide"
            elif any(w in title_l for w in ("theory", "analysis", "deep dive")):
                category = "theory"

            scored.append(TrendingTopic(
                title=item.title,
                source=item.source,
                url=item.url,
                relevance_score=round(combined_score, 3),
                freshness_hours=round(freshness, 1),
                engagement_potential=potential,
                summary=item.summary[:200],
                category=category,
                verification_state=item.verification_state,
                confidence=relevance,
            ))

        # Sort by combined score descending
        scored.sort(key=lambda t: t.relevance_score, reverse=True)
        return scored[:limit]

    def get_cached_news(self) -> list[dict]:
        """Return all cached news items from the store."""
        return self.store.get_all()

    def cached_news_count(self) -> int:
        """Return count of cached news items."""
        return self.store.count()