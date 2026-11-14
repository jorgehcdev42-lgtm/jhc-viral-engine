"""Smart Video Selector — Contextual media selection for Reel production.

Selects relevant video clips from the SmartMediaLibrary based on
script content, scene requirements, and editorial context. Ensures
visual diversity, rights compliance, and non-repetition across productions.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.media.library import SmartMediaLibrary, MediaAsset

logger = logging.getLogger(__name__)

# Keyword-to-category mapping for GTA 6 / Vice City content
KEYWORD_CATEGORIES: dict[str, list[str]] = {
    "vice city": ["Vice City", "cenários urbanos", "praias", "ambientes"],
    "veículo": ["vehicles", "carros", "veículos", "perseguições"],
    "carro": ["vehicles", "carros", "veículos"],
    "moto": ["vehicles", "motocicleta"],
    "arma": ["armas", "weapons", "ação"],
    "tiroteio": ["armas", "ação", "cenas de ação"],
    "praia": ["praias", "cenários", "ambientes"],
    "personagem": ["Jason", "Lucia", "personagens"],
    "jason": ["Jason", "personagens"],
    "lucia": ["Lucia", "personagens"],
    "trailer": ["trailers", "cinemáticas"],
    "gameplay": ["Gameplay", "gameplay"],
    "mapa": ["cenários urbanos", "ambientes", "Vice City"],
    "lançamento": ["news", "announcement"],
    "novidade": ["news", "novidades"],
    "curiosidade": ["curiosidades", "Curiosidades"],
    "teoria": ["teorias", "Teorias"],
}

@dataclass(frozen=True)
class ClipSelection:
    """A selected video clip for a specific scene."""
    asset: MediaAsset
    scene_index: int
    relevance_score: float
    start_time: float = 0.0
    end_time: Optional[float] = None
    segment_reason: str = ""

    @property
    def duration(self) -> float:
        if self.end_time is not None:
            return self.end_time - self.start_time
        return (self.asset.duration_seconds or 0.0) - self.start_time

@dataclass
class SelectionResult:
    """Result of contextual video selection for a full script."""
    clips: list[ClipSelection] = field(default_factory=list)
    scenes_without_media: list[int] = field(default_factory=list)
    total_duration: float = 0.0
    unique_assets: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def coverage_ratio(self) -> float:
        """Ratio of scenes with media vs total scenes."""
        total = len(self.clips) + len(self.scenes_without_media)
        if total == 0:
            return 0.0
        return len(self.clips) / total

    def summary(self) -> str:
        return (
            f"Selected {len(self.clips)} clips for "
            f"{len(self.clips) + len(self.scenes_without_media)} scenes "
            f"(coverage={self.coverage_ratio:.0%}, "
            f"unique_assets={self.unique_assets}, "
            f"duration={self.total_duration:.1f}s)"
        )


class SmartVideoSelector:
    """Select contextual video clips from the media library."""

    MIN_CLIP_DURATION = 2.0
    MAX_REUSE_PER_BATCH = 2  # Max times same asset used in one batch
    RIGHTS_REQUIRED = {"authorized", "public_domain"}

    def __init__(self, library: SmartMediaLibrary) -> None:
        self.library = library
        self._batch_usage: dict[str, int] = {}  # file_path -> usage count

    def extract_keywords(self, text: str) -> list[str]:
        """Extract relevant keywords from script text for media search."""
        text_lower = text.lower()
        matched_categories: set[str] = set()

        for keyword, categories in KEYWORD_CATEGORIES.items():
            if keyword in text_lower:
                matched_categories.update(categories)

        # Also extract quoted terms and capitalized words as potential tags
        quoted = re.findall(r'"([^"]+)"', text)
        for q in quoted:
            matched_categories.add(q.strip())

        return list(matched_categories)

    def select_for_scene(
        self,
        scene_text: str,
        scene_index: int,
        target_duration: float = 5.0,
        exclude_paths: Optional[set[str]] = None,
        require_authorized: bool = False,
    ) -> Optional[ClipSelection]:
        """Select the best matching clip for a single scene.

        Args:
            scene_text: Text content of the scene
            scene_index: Position in the script sequence
            target_duration: Desired clip duration in seconds
            exclude_paths: File paths to exclude (already used)
            require_authorized: Only use assets with confirmed rights
        """
        keywords = self.extract_keywords(scene_text)
        exclude = exclude_paths or set()

        # Search by each keyword category, collect candidates
        candidates: list[MediaAsset] = []
        seen_paths: set[str] = set()

        for kw in keywords:
            results = self.library.search(query=kw, limit=10)
            for asset in results:
                if asset.file_path not in seen_paths:
                    seen_paths.add(asset.file_path)
                    candidates.append(asset)

        # If no keyword matches, try broad search
        if not candidates:
            candidates = self.library.search(limit=20)

        # Filter candidates
        filtered: list[MediaAsset] = []
        for asset in candidates:
            # Skip excluded
            if asset.file_path in exclude:
                continue
            # Skip corrupt
            if asset.is_corrupt:
                continue
            # Skip too short
            if asset.duration_seconds and asset.duration_seconds < self.MIN_CLIP_DURATION:
                continue
            # Skip overused in batch
            usage = self._batch_usage.get(asset.file_path, 0)
            if usage >= self.MAX_REUSE_PER_BATCH:
                continue
            # Rights check
            if require_authorized and asset.rights_status not in self.RIGHTS_REQUIRED:
                continue
            filtered.append(asset)

        if not filtered:
            return None

        # Score candidates by relevance
        scored: list[tuple[float, MediaAsset]] = []
        for asset in filtered:
            score = self._score_asset(asset, keywords, target_duration)
            scored.append((score, asset))

        scored.sort(key=lambda x: x[0], reverse=True)
        best_score, best_asset = scored[0]

        # Calculate segment timing
        start, end = self._calculate_segment(best_asset, target_duration)

        # Track batch usage
        self._batch_usage[best_asset.file_path] = (
            self._batch_usage.get(best_asset.file_path, 0) + 1
        )

        return ClipSelection(
            asset=best_asset,
            scene_index=scene_index,
            relevance_score=best_score,
            start_time=start,
            end_time=end,
            segment_reason=f"keywords={keywords[:3]}",
        )

    def select_for_script(
        self,
        script_text: str,
        scene_durations: Optional[list[float]] = None,
        require_authorized: bool = False,
    ) -> SelectionResult:
        """Select clips for all scenes in a script.

        Args:
            script_text: Full script with section markers
            scene_durations: Target duration per scene (seconds)
            require_authorized: Only use authorized assets
        """
        from src.production.script_to_scenes import parse_script_to_scenes

        scenes = parse_script_to_scenes(script_text)
        result = SelectionResult()
        used_paths: set[str] = set()

        for i, scene in enumerate(scenes):
            target_dur = (
                scene_durations[i]
                if scene_durations and i < len(scene_durations)
                else scene.duration_seconds
            )

            clip = self.select_for_scene(
                scene.text,
                scene_index=i,
                target_duration=target_dur,
                exclude_paths=used_paths,
                require_authorized=require_authorized,
            )

            if clip:
                result.clips.append(clip)
                used_paths.add(clip.asset.file_path)
                result.total_duration += clip.duration
            else:
                result.scenes_without_media.append(i)
                result.warnings.append(
                    f"Scene {i} ({scene.scene_type}): no matching media found"
                )

        result.unique_assets = len(used_paths)
        logger.info(result.summary())
        return result

    def reset_batch_usage(self) -> None:
        """Reset batch usage counters for a new production run."""
        self._batch_usage.clear()

    def _score_asset(
        self,
        asset: MediaAsset,
        keywords: list[str],
        target_duration: float,
    ) -> float:
        """Score an asset's relevance for the given keywords and duration."""
        score = 0.0

        # Tag match score (0-0.4)
        asset_tags = set(t.lower() for t in asset.tags)
        asset_category = (asset.category or "").lower()
        keyword_matches = sum(
            1 for kw in keywords
            if kw.lower() in asset_tags or kw.lower() in asset_category
        )
        if keywords:
            score += min(0.4, (keyword_matches / len(keywords)) * 0.4)

        # Duration fitness score (0-0.3)
        if asset.duration_seconds:
            ratio = asset.duration_seconds / max(target_duration, 1.0)
            if 0.5 <= ratio <= 2.0:
                score += 0.3
            elif 0.25 <= ratio <= 4.0:
                score += 0.15

        # Quality preference: higher resolution preferred (0-0.15)
        if asset.width and asset.height:
            pixels = asset.width * asset.height
            if pixels >= 1920 * 1080:
                score += 0.15
            elif pixels >= 1280 * 720:
                score += 0.10
            elif pixels >= 640 * 480:
                score += 0.05

        # Rights bonus (0-0.1)
        if asset.rights_status in self.RIGHTS_REQUIRED:
            score += 0.1

        # Freshness: recently indexed preferred (0-0.05)
        import time
        age_hours = (time.time() - asset.indexed_at) / 3600
        if age_hours < 24:
            score += 0.05
        elif age_hours < 168:  # 1 week
            score += 0.025

        return min(1.0, score)

    @staticmethod
    def _calculate_segment(
        asset: MediaAsset, target_duration: float
    ) -> tuple[float, Optional[float]]:
        """Calculate optimal start/end times for a clip segment."""
        total = asset.duration_seconds or 0.0

        if total <= 0:
            return (0.0, None)

        if total <= target_duration:
            # Use entire clip
            return (0.0, total)

        # Pick a segment from the middle third (avoid intro/outro)
        margin = total * 0.15
        available_start = margin
        available_end = total - margin
        available_span = max(0, available_end - available_start)

        if available_span <= target_duration:
            return (available_start, available_end)

        # Center the segment in the available range
        center = (available_start + available_end) / 2
        half = target_duration / 2
        start = max(0, center - half)
        end = min(total, start + target_duration)

        return (start, end)