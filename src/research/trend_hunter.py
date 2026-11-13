"""Trend hunting and topic validation for JHC Viral Engine.

Searches multiple sources to find trending topics, validates them
against profile editorial guidelines, and scores by engagement potential.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from src.core.profile_config import ProfileConfig

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


class TrendHunter:
    """Discovers and validates trending topics for a specific profile."""

    def __init__(self, profile: ProfileConfig) -> None:
        self.profile = profile

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
        """Discover trending topics from configured sources.

        Returns empty list when no external APIs are configured.
        Real implementation will integrate RSS, YouTube Data API, etc.
        """
        logger.info(
            "Trend discovery for profile=%s (sources: %d keywords, %d feeds)",
            self.profile.profile_id,
            len(self.profile.research_sources.keywords),
            len(self.profile.research_sources.rss_feeds),
        )
        # Placeholder — real implementation needs HTTP clients
        return []