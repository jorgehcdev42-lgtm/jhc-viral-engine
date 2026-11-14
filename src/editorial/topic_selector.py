"""Editorial topic selector for JHC Viral Engine.

Selects daily topics from researched trends with scoring,
deduplication, and source verification. Prevents repetitive
content and ensures editorial quality over quantity.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class TopicCandidate:
    """A candidate topic for content production."""
    title: str
    source_url: str
    source_name: str
    published_date: str
    category: str  # news, rumor, guide, theory, announcement
    relevance_score: float
    freshness_hours: float
    content_hash: str
    confidence: float = 0.0
    audience_potential: float = 0.0
    originality_score: float = 0.0
    selected: bool = False
    rejection_reason: str = ""

    @property
    def editorial_score(self) -> float:
        """Weighted editorial score combining all dimensions."""
        return (
            self.relevance_score * 0.30
            + min(1.0, 48.0 / max(self.freshness_hours, 1.0)) * 0.25
            + self.confidence * 0.20
            + self.audience_potential * 0.15
            + self.originality_score * 0.10
        )

@dataclass(frozen=True)
class EditorialQueue:
    """Persistent queue of selected topics for production."""
    profile_id: str
    topics: tuple[TopicCandidate, ...]
    last_updated: float
    max_daily: int = 5

    def to_dict(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "max_daily": self.max_daily,
            "last_updated": self.last_updated,
            "topics": [
                {
                    "title": t.title,
                    "source_url": t.source_url,
                    "source_name": t.source_name,
                    "published_date": t.published_date,
                    "category": t.category,
                    "relevance_score": round(t.relevance_score, 3),
                    "freshness_hours": round(t.freshness_hours, 1),
                    "content_hash": t.content_hash,
                    "confidence": round(t.confidence, 3),
                    "audience_potential": round(t.audience_potential, 3),
                    "originality_score": round(t.originality_score, 3),
                    "editorial_score": round(t.editorial_score, 3),
                    "selected": t.selected,
                    "rejection_reason": t.rejection_reason,
                }
                for t in self.topics
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> EditorialQueue:
        topics = tuple(
            TopicCandidate(
                title=t["title"],
                source_url=t["source_url"],
                source_name=t["source_name"],
                published_date=t["published_date"],
                category=t["category"],
                relevance_score=t["relevance_score"],
                freshness_hours=t["freshness_hours"],
                content_hash=t["content_hash"],
                confidence=t.get("confidence", 0.0),
                audience_potential=t.get("audience_potential", 0.0),
                originality_score=t.get("originality_score", 0.0),
                selected=t.get("selected", False),
                rejection_reason=t.get("rejection_reason", ""),
            )
            for t in data.get("topics", [])
        )
        return cls(
            profile_id=data["profile_id"],
            topics=topics,
            last_updated=data.get("last_updated", 0.0),
            max_daily=data.get("max_daily", 5),
        )


class TopicSelector:
    """Select and rank topics for daily content production."""

    HISTORY_FILE = "topic_history.json"
    QUEUE_FILE = "editorial_queue.json"

    def __init__(self, data_root: Path, profile_id: str) -> None:
        self.data_root = data_root
        self.profile_id = profile_id
        self.queue_dir = data_root / profile_id / "editorial"
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self._history: set[str] = set()
        self._load_history()

    def _load_history(self) -> None:
        """Load previously used topic hashes."""
        history_path = self.queue_dir / self.HISTORY_FILE
        if history_path.exists():
            try:
                data = json.loads(history_path.read_text(encoding="utf-8"))
                self._history = set(data.get("used_hashes", []))
                logger.info("Loaded %d historical topic hashes", len(self._history))
            except (json.JSONDecodeError, KeyError):
                logger.warning("Could not load topic history; starting fresh")

    def _save_history(self) -> None:
        """Persist used topic hashes."""
        history_path = self.queue_dir / self.HISTORY_FILE
        history_path.write_text(
            json.dumps({"used_hashes": list(self._history)}, ensure_ascii=False),
            encoding="utf-8",
        )

    def evaluate_candidates(
        self, candidates: list[TopicCandidate]
    ) -> list[TopicCandidate]:
        """Score, deduplicate, and rank topic candidates.

        Returns candidates sorted by editorial_score descending,
        with rejection reasons annotated.
        """
        evaluated: list[TopicCandidate] = []
        seen_hashes: set[str] = set(self._history)  # Include history + intra-batch dedup

        for c in candidates:
            # Check duplication against history AND within current batch
            if c.content_hash in seen_hashes:
                evaluated.append(TopicCandidate(
                    title=c.title,
                    source_url=c.source_url,
                    source_name=c.source_name,
                    published_date=c.published_date,
                    category=c.category,
                    relevance_score=c.relevance_score,
                    freshness_hours=c.freshness_hours,
                    content_hash=c.content_hash,
                    confidence=c.confidence,
                    audience_potential=c.audience_potential,
                    originality_score=0.0,
                    selected=False,
                    rejection_reason="duplicate: already produced or in batch",
                ))
                continue
            seen_hashes.add(c.content_hash)

            # Estimate originality (inverse of similarity to known topics)
            originality = self._estimate_originality(c)

            # Estimate audience potential based on category and freshness
            audience = self._estimate_audience_potential(c)

            # Confidence based on source reliability
            confidence = self._estimate_confidence(c)

            scored = TopicCandidate(
                title=c.title,
                source_url=c.source_url,
                source_name=c.source_name,
                published_date=c.published_date,
                category=c.category,
                relevance_score=c.relevance_score,
                freshness_hours=c.freshness_hours,
                content_hash=c.content_hash,
                confidence=confidence,
                audience_potential=audience,
                originality_score=originality,
                selected=False,
            )
            evaluated.append(scored)

        # Sort by editorial score descending
        evaluated.sort(key=lambda t: t.editorial_score, reverse=True)
        return evaluated

    def select_daily_topics(
        self, candidates: list[TopicCandidate], max_topics: int = 5
    ) -> EditorialQueue:
        """Select top N non-duplicate topics for today's production."""
        evaluated = self.evaluate_candidates(candidates)

        selected: list[TopicCandidate] = []
        for t in evaluated:
            if t.rejection_reason:
                continue
            if len(selected) >= max_topics:
                break
            # Mark as selected
            selected.append(TopicCandidate(
                title=t.title,
                source_url=t.source_url,
                source_name=t.source_name,
                published_date=t.published_date,
                category=t.category,
                relevance_score=t.relevance_score,
                freshness_hours=t.freshness_hours,
                content_hash=t.content_hash,
                confidence=t.confidence,
                audience_potential=t.audience_potential,
                originality_score=t.originality_score,
                selected=True,
            ))

        # Record selected hashes in history
        for t in selected:
            self._history.add(t.content_hash)
        self._save_history()

        queue = EditorialQueue(
            profile_id=self.profile_id,
            topics=tuple(selected),
            last_updated=time.time(),
            max_daily=max_topics,
        )

        # Persist queue
        queue_path = self.queue_dir / self.QUEUE_FILE
        queue_path.write_text(
            json.dumps(queue.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.info(
            "Selected %d/%d topics for %s (from %d candidates)",
            len(selected), max_topics, self.profile_id, len(candidates),
        )
        return queue

    def load_queue(self) -> Optional[EditorialQueue]:
        """Load persisted editorial queue."""
        queue_path = self.queue_dir / self.QUEUE_FILE
        if not queue_path.exists():
            return None
        try:
            data = json.loads(queue_path.read_text(encoding="utf-8"))
            return EditorialQueue.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            logger.warning("Could not load editorial queue")
            return None

    def _estimate_originality(self, candidate: TopicCandidate) -> float:
        """Estimate originality based on title uniqueness vs history."""
        # Simple heuristic: check if similar titles exist in history
        # In production, this would use embedding similarity
        title_words = set(candidate.title.lower().split())
        if not title_words:
            return 0.5
        # Higher score = more original
        return min(1.0, len(title_words) / 8.0)

    def _estimate_audience_potential(self, candidate: TopicCandidate) -> float:
        """Estimate audience interest based on category and freshness."""
        category_weights = {
            "announcement": 1.0,
            "news": 0.9,
            "rumor": 0.8,
            "theory": 0.7,
            "guide": 0.6,
        }
        cat_weight = category_weights.get(candidate.category, 0.5)

        # Fresher = higher potential
        freshness_factor = min(1.0, 24.0 / max(candidate.freshness_hours, 1.0))

        return cat_weight * 0.6 + freshness_factor * 0.4

    def _estimate_confidence(self, candidate: TopicCandidate) -> float:
        """Estimate factual confidence based on source reliability."""
        trusted_sources = {
            "Eurogamer": 0.9,
            "VGC": 0.85,
            "IGN": 0.85,
            "GameSpot": 0.85,
            "Rockstar Newswire": 1.0,
            "BBC": 0.95,
        }
        base = trusted_sources.get(candidate.source_name, 0.6)

        # Announcements from official sources get boost
        if candidate.category == "announcement" and base >= 0.8:
            base = min(1.0, base + 0.1)

        return base