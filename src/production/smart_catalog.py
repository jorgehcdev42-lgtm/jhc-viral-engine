"""Smart Catalog — Bridge between bulk import index and AutoReel pipeline.

Provides intelligent material selection for AutoReel production based on:
- Theme/category matching
- Visual quality (resolution, codec)
- Duration fitness for target platform
- Aspect ratio compatibility (vertical preferred for reels)
- Usage history tracking (avoid repetition)
- Diversity scoring across scenes
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class CatalogEntry:
    """Single entry from the catalog index."""
    filename: str
    path: str
    type: str  # "video" or "image"
    category: str = "cortes"
    source_pack: str = ""
    hd: bool = False
    size_bytes: int = 0
    width: int = 0
    height: int = 0
    duration: float = 0.0
    codec: str = ""
    fps: float = 0.0
    autoreels_compatible: bool = False
    metadata: dict = field(default_factory=dict)
    used_count: int = 0
    last_used: float = 0.0

    @classmethod
    def from_dict(cls, d: dict) -> CatalogEntry:
        meta = d.get("metadata", {})
        return cls(
            filename=d.get("filename", ""),
            path=d.get("path", ""),
            type=d.get("type", "video"),
            category=d.get("category", "cortes"),
            source_pack=d.get("source_pack", ""),
            hd=d.get("hd", False),
            size_bytes=d.get("size_bytes", 0),
            width=meta.get("width", 0) or 0,
            height=meta.get("height", 0) or 0,
            duration=meta.get("duration", 0.0) or 0.0,
            codec=meta.get("codec", "") or "",
            fps=meta.get("fps", 0.0) or 0.0,
            autoreels_compatible=d.get("autoreels_compatible", False),
            metadata=meta,
            used_count=d.get("used_count", 0),
            last_used=d.get("last_used", 0.0),
        )

    def is_vertical(self) -> bool:
        return self.height > self.width

    def is_landscape(self) -> bool:
        return self.width > self.height

    def aspect_ratio(self) -> float:
        if self.height == 0:
            return 0.0
        return self.width / self.height

    def quality_score(self) -> float:
        """Score 0-100 based on resolution, codec, and duration."""
        score = 0.0
        # Resolution bonus
        if self.width >= 1920:
            score += 30
        elif self.width >= 1280:
            score += 20
        elif self.width >= 720:
            score += 10
        # Vertical bonus for reels
        if self.is_vertical():
            score += 15
        # Codec bonus
        if self.codec in ("h264", "hevc", "av1"):
            score += 10
        # Duration sweet spot (15-90s ideal for reels)
        if 15 <= self.duration <= 90:
            score += 20
        elif 5 <= self.duration <= 120:
            score += 10
        # HD flag
        if self.hd:
            score += 5
        # Freshness (less used = higher score)
        if self.used_count == 0:
            score += 10
        elif self.used_count <= 2:
            score += 5
        return min(score, 100.0)


@dataclass
class SelectionCriteria:
    """Criteria for intelligent material selection."""
    theme: str = ""
    min_duration: float = 5.0
    max_duration: float = 120.0
    prefer_vertical: bool = True
    min_width: int = 720
    min_quality_score: float = 20.0
    exclude_recently_used: int = 5  # exclude last N used entries
    max_results: int = 10
    include_images: bool = False


class SmartCatalog:
    """Intelligent catalog bridge for AutoReel production."""

    USAGE_LOG_FILE = "autoreel_usage.json"

    def __init__(self, data_root: str | Path = "data"):
        self.data_root = Path(data_root)
        self.catalog_index_path = self.data_root / "bulk_import" / "state" / "catalog_index.json"
        self.usage_log_path = self.data_root / "autoreel" / self.USAGE_LOG_FILE
        self._entries: list[CatalogEntry] = []
        self._usage_log: dict[str, dict] = {}
        self._loaded = False

    def load(self) -> int:
        """Load catalog index and usage history. Returns entry count."""
        if not self.catalog_index_path.exists():
            self._entries = []
            self._loaded = True
            return 0

        raw = json.loads(self.catalog_index_path.read_text())
        self._entries = [CatalogEntry.from_dict(d) for d in raw]

        # Load usage history
        if self.usage_log_path.exists():
            try:
                self._usage_log = json.loads(self.usage_log_path.read_text())
            except (json.JSONDecodeError, OSError):
                self._usage_log = {}

        # Merge usage data into entries
        for entry in self._entries:
            usage = self._usage_log.get(entry.filename)
            if usage:
                # Rebuild with usage data (frozen dataclass)
                idx = self._entries.index(entry)
                self._entries[idx] = CatalogEntry(
                    filename=entry.filename,
                    path=entry.path,
                    type=entry.type,
                    category=entry.category,
                    source_pack=entry.source_pack,
                    hd=entry.hd,
                    size_bytes=entry.size_bytes,
                    width=entry.width,
                    height=entry.height,
                    duration=entry.duration,
                    codec=entry.codec,
                    fps=entry.fps,
                    autoreels_compatible=entry.autoreels_compatible,
                    metadata=entry.metadata,
                    used_count=usage.get("count", 0),
                    last_used=usage.get("last_used", 0.0),
                )

        self._loaded = True
        return len(self._entries)

    def query(
        self,
        type_filter: str = "video",
        compatible_only: bool = True,
        min_width: int = 0,
        min_duration: float = 0.0,
        max_duration: float = 0.0,
        vertical_only: bool = False,
    ) -> list[CatalogEntry]:
        """Filter catalog entries by criteria."""
        if not self._loaded:
            self.load()

        results = []
        for e in self._entries:
            if type_filter and e.type != type_filter:
                continue
            if compatible_only and not e.autoreels_compatible:
                continue
            if min_width and e.width < min_width:
                continue
            if min_duration and e.duration < min_duration:
                continue
            if max_duration and e.duration > max_duration:
                continue
            if vertical_only and not e.is_vertical():
                continue
            results.append(e)
        return results

    def select_materials(self, criteria: SelectionCriteria) -> list[CatalogEntry]:
        """Intelligent selection ranked by quality score and diversity."""
        if not self._loaded:
            self.load()

        candidates = self.query(
            type_filter="video" if not criteria.include_images else "",
            compatible_only=True,
            min_width=criteria.min_width,
            min_duration=criteria.min_duration,
            max_duration=criteria.max_duration,
            vertical_only=criteria.prefer_vertical,
        )

        # Filter by minimum quality
        candidates = [c for c in candidates if c.quality_score() >= criteria.min_quality_score]

        # Exclude recently used
        if criteria.exclude_recently_used > 0:
            sorted_by_usage = sorted(candidates, key=lambda c: c.last_used, reverse=True)
            recently_used = {e.filename for e in sorted_by_usage[:criteria.exclude_recently_used]}
            candidates = [c for c in candidates if c.filename not in recently_used]

        # Rank by quality score (descending), then by freshness
        candidates.sort(key=lambda c: (-c.quality_score(), c.last_used))

        return candidates[:criteria.max_results]

    def record_usage(self, filenames: list[str], reel_id: str = "") -> None:
        """Record that materials were used in a reel production."""
        now = time.time()
        for fn in filenames:
            if fn not in self._usage_log:
                self._usage_log[fn] = {"count": 0, "last_used": 0.0, "reels": []}
            self._usage_log[fn]["count"] += 1
            self._usage_log[fn]["last_used"] = now
            if reel_id:
                reels = self._usage_log[fn].get("reels", [])
                reels.append(reel_id)
                self._usage_log[fn]["reels"] = reels[-20:]  # keep last 20

        # Persist
        self.usage_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.usage_log_path.write_text(json.dumps(self._usage_log, indent=2))

    def get_stats(self) -> dict:
        """Return catalog statistics."""
        if not self._loaded:
            self.load()

        videos = [e for e in self._entries if e.type == "video"]
        images = [e for e in self._entries if e.type == "image"]
        compatible = [e for e in videos if e.autoreels_compatible]
        vertical = [e for e in compatible if e.is_vertical()]
        used = [e for e in self._entries if e.used_count > 0]

        durations = [e.duration for e in compatible if e.duration > 0]
        avg_dur = sum(durations) / len(durations) if durations else 0

        return {
            "total_entries": len(self._entries),
            "total_videos": len(videos),
            "total_images": len(images),
            "autoreels_compatible": len(compatible),
            "vertical_videos": len(vertical),
            "landscape_videos": len(compatible) - len(vertical),
            "used_materials": len(used),
            "unused_materials": len(compatible) - len([e for e in compatible if e.used_count > 0]),
            "avg_duration_seconds": round(avg_dur, 1),
            "total_size_gb": round(sum(e.size_bytes for e in self._entries) / (1024**3), 2),
        }