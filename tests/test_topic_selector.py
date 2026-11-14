"""Tests for editorial TopicSelector and queue management."""

from __future__ import annotations

import json
import shutil
import pytest
from pathlib import Path

from src.editorial.topic_selector import (
    TopicSelector,
    TopicCandidate,
    EditorialQueue,
)


@pytest.fixture
def selector(tmp_path: Path) -> TopicSelector:
    return TopicSelector(tmp_path, "test_profile")


def _make_candidate(
    title: str = "Test topic",
    source: str = "Eurogamer",
    category: str = "news",
    relevance: float = 0.8,
    freshness: float = 2.0,
    content_hash: str = "hash1",
) -> TopicCandidate:
    return TopicCandidate(
        title=title,
        source_url=f"https://{source.lower()}.com/test",
        source_name=source,
        published_date="2026-11-14",
        category=category,
        relevance_score=relevance,
        freshness_hours=freshness,
        content_hash=content_hash,
    )


class TestTopicScoring:
    """Test editorial scoring dimensions."""

    def test_editorial_score_combines_dimensions(self, selector: TopicSelector) -> None:
        c = _make_candidate(relevance=0.9, freshness=1.0, category="announcement")
        evaluated = selector.evaluate_candidates([c])
        assert len(evaluated) == 1
        score = evaluated[0].editorial_score
        assert 0.0 < score <= 1.0

    def test_fresher_topics_score_higher(self, selector: TopicSelector) -> None:
        fresh = _make_candidate(freshness=1.0, content_hash="fresh")
        stale = _make_candidate(freshness=72.0, content_hash="stale")
        evaluated = selector.evaluate_candidates([fresh, stale])
        fresh_score = next(e.editorial_score for e in evaluated if e.content_hash == "fresh")
        stale_score = next(e.editorial_score for e in evaluated if e.content_hash == "stale")
        assert fresh_score > stale_score

    def test_announcement_scores_higher_than_guide(self, selector: TopicSelector) -> None:
        ann = _make_candidate(category="announcement", content_hash="ann")
        guide = _make_candidate(category="guide", content_hash="guide")
        evaluated = selector.evaluate_candidates([ann, guide])
        ann_score = next(e.editorial_score for e in evaluated if e.content_hash == "ann")
        guide_score = next(e.editorial_score for e in evaluated if e.content_hash == "guide")
        assert ann_score > guide_score

    def test_trusted_source_higher_confidence(self, selector: TopicSelector) -> None:
        euro = _make_candidate(source="Eurogamer", content_hash="euro")
        unknown = _make_candidate(source="RandomBlog", content_hash="unknown")
        evaluated = selector.evaluate_candidates([euro, unknown])
        euro_conf = next(e.confidence for e in evaluated if e.content_hash == "euro")
        unknown_conf = next(e.confidence for e in evaluated if e.content_hash == "unknown")
        assert euro_conf > unknown_conf


class TestDeduplication:
    """Test duplicate detection within batch and against history."""

    def test_intra_batch_duplicate_rejected(self, selector: TopicSelector) -> None:
        c1 = _make_candidate(title="Original", content_hash="dup_hash")
        c2 = _make_candidate(title="Duplicate", content_hash="dup_hash")
        evaluated = selector.evaluate_candidates([c1, c2])
        rejected = [e for e in evaluated if e.rejection_reason]
        assert len(rejected) == 1
        assert "duplicate" in rejected[0].rejection_reason

    def test_history_duplicate_rejected(self, selector: TopicSelector) -> None:
        # First selection records hash
        c1 = _make_candidate(content_hash="history_hash")
        selector.select_daily_topics([c1], max_topics=5)
        # Second selection should reject same hash
        c2 = _make_candidate(title="New title same hash", content_hash="history_hash")
        evaluated = selector.evaluate_candidates([c2])
        assert len(evaluated) == 1
        assert evaluated[0].rejection_reason
        assert "duplicate" in evaluated[0].rejection_reason

    def test_different_hashes_both_accepted(self, selector: TopicSelector) -> None:
        c1 = _make_candidate(content_hash="hash_a")
        c2 = _make_candidate(content_hash="hash_b")
        evaluated = selector.evaluate_candidates([c1, c2])
        accepted = [e for e in evaluated if not e.rejection_reason]
        assert len(accepted) == 2


class TestDailySelection:
    """Test daily topic selection and queue persistence."""

    def test_respects_max_daily_limit(self, selector: TopicSelector) -> None:
        candidates = [_make_candidate(content_hash=f"h{i}") for i in range(10)]
        queue = selector.select_daily_topics(candidates, max_topics=3)
        assert len(queue.topics) == 3

    def test_queue_persisted_to_disk(self, selector: TopicSelector, tmp_path: Path) -> None:
        candidates = [_make_candidate(content_hash="persist_test")]
        selector.select_daily_topics(candidates, max_topics=5)
        queue_path = tmp_path / "test_profile" / "editorial" / "editorial_queue.json"
        assert queue_path.exists()
        data = json.loads(queue_path.read_text(encoding="utf-8"))
        assert data["profile_id"] == "test_profile"
        assert len(data["topics"]) == 1

    def test_history_persisted_to_disk(self, selector: TopicSelector, tmp_path: Path) -> None:
        candidates = [_make_candidate(content_hash="hist_test")]
        selector.select_daily_topics(candidates, max_topics=5)
        hist_path = tmp_path / "test_profile" / "editorial" / "topic_history.json"
        assert hist_path.exists()
        data = json.loads(hist_path.read_text(encoding="utf-8"))
        assert "hist_test" in data["used_hashes"]

    def test_load_queue_returns_saved_data(self, selector: TopicSelector) -> None:
        candidates = [_make_candidate(content_hash="load_test")]
        original = selector.select_daily_topics(candidates, max_topics=5)
        loaded = selector.load_queue()
        assert loaded is not None
        assert len(loaded.topics) == len(original.topics)
        assert loaded.topics[0].content_hash == "load_test"

    def test_load_queue_returns_none_when_missing(self, tmp_path: Path) -> None:
        sel = TopicSelector(tmp_path, "nonexistent")
        assert sel.load_queue() is None

    def test_selected_topics_sorted_by_score(self, selector: TopicSelector) -> None:
        low = _make_candidate(relevance=0.3, freshness=100.0, content_hash="low")
        high = _make_candidate(relevance=0.95, freshness=1.0, content_hash="high")
        queue = selector.select_daily_topics([low, high], max_topics=5)
        assert len(queue.topics) == 2
        assert queue.topics[0].editorial_score >= queue.topics[1].editorial_score


class TestEditorialQueueSerialization:
    """Test EditorialQueue to_dict/from_dict roundtrip."""

    def test_roundtrip_preserves_data(self) -> None:
        topics = (
            _make_candidate(content_hash="rt1"),
            _make_candidate(content_hash="rt2"),
        )
        queue = EditorialQueue(
            profile_id="test",
            topics=topics,
            last_updated=1234567890.0,
            max_daily=5,
        )
        data = queue.to_dict()
        restored = EditorialQueue.from_dict(data)
        assert restored.profile_id == "test"
        assert len(restored.topics) == 2
        assert restored.last_updated == 1234567890.0
        assert restored.max_daily == 5
        assert restored.topics[0].content_hash == "rt1"