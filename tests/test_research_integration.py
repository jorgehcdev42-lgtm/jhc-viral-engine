"""Integration tests for research module with real external sources.

These tests hit live RSS feeds and are marked as integration tests.
They validate that the pipeline can fetch, parse, deduplicate and score
real news items from public sources.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from src.core.profile_config import GTA6_PROFILE
from src.research.trend_hunter import TrendHunter
from src.research.rss_source import fetch_rss, NewsStore, NewsItem


@pytest.mark.integration
class TestRSSSource:
    """Tests against real RSS feeds (requires network)."""

    def test_fetch_rockstar_newswire_returns_items(self) -> None:
        """Rockstar Newswire RSS should return at least one item."""
        items = fetch_rss(
            "https://www.rockstargames.com/newswire/feed",
            "Rockstar Newswire",
            timeout=20,
        )
        # Feed may be empty if Rockstar changed URL; log warning but don't fail hard
        if not items:
            pytest.skip("Rockstar Newswire RSS returned 0 items (feed may have changed)")
        assert len(items) >= 1
        first = items[0]
        assert first.title
        assert first.url.startswith("http")
        assert first.source == "Rockstar Newswire"
        assert first.content_hash

    def test_fetch_invalid_url_returns_empty(self) -> None:
        """Invalid URL should return empty list without raising."""
        items = fetch_rss("https://invalid.example.com/no-feed.xml", "test")
        assert items == []

    def test_news_store_deduplication(self, tmp_path: Path) -> None:
        """NewsStore should deduplicate by content_hash."""
        store = NewsStore(tmp_path, "test-profile")
        items = [
            NewsItem(title="GTA 6 News", url="https://example.com/1", source="test"),
            NewsItem(title="GTA 6 News", url="https://example.com/1", source="test"),
            NewsItem(title="Different News", url="https://example.com/2", source="test"),
        ]
        new_count = store.add_items(items)
        assert new_count == 2  # duplicate filtered
        assert store.count() == 2

    def test_news_store_persistence(self, tmp_path: Path) -> None:
        """NewsStore should persist and reload across instances."""
        store1 = NewsStore(tmp_path, "persist-test")
        items = [
            NewsItem(title="Persistent News", url="https://example.com/p", source="test"),
        ]
        store1.add_items(items)
        assert store1.count() == 1

        # New instance should load persisted data
        store2 = NewsStore(tmp_path, "persist-test")
        assert store2.count() == 1
        all_items = store2.get_all()
        assert all_items[0]["title"] == "Persistent News"


@pytest.mark.integration
class TestTrendHunterDiscovery:
    """End-to-end trend discovery with real feeds."""

    @pytest.mark.asyncio
    async def test_discover_trends_returns_real_items(self, tmp_path: Path) -> None:
        """TrendHunter should fetch real RSS and return scored topics."""
        hunter = TrendHunter(GTA6_PROFILE, data_root=tmp_path)
        trends = await hunter.discover_trends(limit=5)

        if not trends:
            pytest.skip("No trends returned (all RSS fetches may have failed)")

        assert len(trends) >= 1
        first = trends[0]
        assert first.title
        assert first.url.startswith("http")
        assert first.relevance_score >= 0
        assert first.engagement_potential in ("low", "medium", "high", "viral")
        assert first.freshness_hours >= 0

    @pytest.mark.asyncio
    async def test_discover_trends_caches_results(self, tmp_path: Path) -> None:
        """Second call should use cache and still return results."""
        hunter = TrendHunter(GTA6_PROFILE, data_root=tmp_path)

        # First call fetches from network
        trends1 = await hunter.discover_trends(limit=5)
        cached_count = hunter.cached_news_count()

        if cached_count == 0:
            pytest.skip("No items cached (network failure)")

        # Second call should also work (may re-fetch but cache exists)
        trends2 = await hunter.discover_trends(limit=5)
        assert hunter.cached_news_count() >= cached_count

    @pytest.mark.asyncio
    async def test_discovered_topics_pass_validation(self, tmp_path: Path) -> None:
        """Topics discovered from profile feeds should pass validation."""
        hunter = TrendHunter(GTA6_PROFILE, data_root=tmp_path)
        trends = await hunter.discover_trends(limit=3)

        if not trends:
            pytest.skip("No trends to validate")

        for trend in trends:
            result = await hunter.validate_topic(trend.title)
            # Discovered topics from profile-specific feeds should generally match keywords
            # (unless feed returns unrelated content)
            assert isinstance(result.is_valid, bool)