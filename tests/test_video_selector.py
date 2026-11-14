"""Tests for SmartVideoSelector — contextual media selection."""

from __future__ import annotations

import shutil
import subprocess
import pytest
from pathlib import Path

from src.media.library import SmartMediaLibrary, MediaAsset
from src.media.video_selector import (
    SmartVideoSelector,
    ClipSelection,
    SelectionResult,
    KEYWORD_CATEGORIES,
)


@pytest.fixture
def lib_and_selector(tmp_path: Path):
    db = tmp_path / "selector_test.db"
    thumbs = tmp_path / "thumbs"
    lib = SmartMediaLibrary(db, thumbs)
    selector = SmartVideoSelector(lib)
    return lib, selector


def _create_test_video(path: Path, duration: float = 5.0, color: str = "red") -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg not available")
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi",
        "-i", f"color=c={color}:s=320x240:r=25:d={duration}",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", "-b:a", "64k",
        "-t", str(duration),
        "-movflags", "+faststart",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=30)
    if result.returncode != 0:
        pytest.skip(f"FFmpeg failed: {result.stderr.decode()[-200:]}")
    return path


class TestKeywordExtraction:
    """Test script-to-keyword mapping."""

    def test_extracts_vice_city_keywords(self, lib_and_selector) -> None:
        _, selector = lib_and_selector
        kws = selector.extract_keywords("Novidades sobre Vice City e suas praias")
        assert any("Vice City" in kw for kw in kws)
        assert any("praias" in kw for kw in kws)

    def test_extracts_vehicle_keywords(self, lib_and_selector) -> None:
        _, selector = lib_and_selector
        kws = selector.extract_keywords("Os melhores veículos e carros do GTA 6")
        assert any("vehicles" in kw or "carros" in kw for kw in kws)

    def test_extracts_character_keywords(self, lib_and_selector) -> None:
        _, selector = lib_and_selector
        kws = selector.extract_keywords("Jason e Lucia são os protagonistas")
        assert any("Jason" in kw for kw in kws)
        assert any("Lucia" in kw for kw in kws)

    def test_empty_text_returns_empty(self, lib_and_selector) -> None:
        _, selector = lib_and_selector
        kws = selector.extract_keywords("")
        assert len(kws) == 0

    def test_keyword_categories_defined(self) -> None:
        assert len(KEYWORD_CATEGORIES) >= 10
        assert "vice city" in KEYWORD_CATEGORIES
        assert "veículo" in KEYWORD_CATEGORIES


class TestSegmentCalculation:
    """Test clip segment timing logic."""

    def test_short_clip_uses_full_duration(self) -> None:
        asset = MediaAsset(
            file_path="/tmp/short.mp4", file_name="short.mp4",
            file_size=500, content_hash="abc", duration_seconds=3.0,
        )
        start, end = SmartVideoSelector._calculate_segment(asset, 5.0)
        assert start == 0.0
        assert end == 3.0

    def test_long_clip_segments_middle(self) -> None:
        asset = MediaAsset(
            file_path="/tmp/long.mp4", file_name="long.mp4",
            file_size=5000, content_hash="def", duration_seconds=30.0,
        )
        start, end = SmartVideoSelector._calculate_segment(asset, 5.0)
        assert end is not None
        assert abs((end - start) - 5.0) < 0.1
        # Segment should be in middle third, not at edges
        assert start > 0
        assert end < 30.0

    def test_zero_duration_asset(self) -> None:
        asset = MediaAsset(
            file_path="/tmp/zero.mp4", file_name="zero.mp4",
            file_size=100, content_hash="ghi", duration_seconds=0.0,
        )
        start, end = SmartVideoSelector._calculate_segment(asset, 5.0)
        assert start == 0.0
        assert end is None


class TestContextualSelection:
    """Test selection against a populated library."""

    @pytest.mark.asyncio
    async def test_select_for_scene_with_matching_media(
        self, lib_and_selector, tmp_path: Path
    ) -> None:
        lib, selector = lib_and_selector
        videos_dir = tmp_path / "videos"

        # Create and index videos with different tags
        v1 = _create_test_video(videos_dir / "vehicles.mp4", duration=8.0, color="blue")
        v2 = _create_test_video(videos_dir / "beach.mp4", duration=10.0, color="cyan")
        v3 = _create_test_video(videos_dir / "city.mp4", duration=6.0, color="purple")

        await lib.index_file(v1, str(videos_dir))
        await lib.index_file(v2, str(videos_dir))
        await lib.index_file(v3, str(videos_dir))

        # Tag them
        lib.update_tags(str(v1.resolve()), ["vehicles", "carros", "perseguições"])
        lib.update_tags(str(v2.resolve()), ["praias", "ambientes", "Vice City"])
        lib.update_tags(str(v3.resolve()), ["cenários urbanos", "Vice City"])

        # Select for a vehicle scene
        clip = selector.select_for_scene(
            "Os veículos mais rápidos de Vice City",
            scene_index=0,
            target_duration=5.0,
        )
        assert clip is not None
        assert clip.relevance_score > 0

    @pytest.mark.asyncio
    async def test_select_returns_none_on_empty_library(
        self, lib_and_selector
    ) -> None:
        _, selector = lib_and_selector
        clip = selector.select_for_scene("Teste sem mídia", scene_index=0)
        assert clip is None

    @pytest.mark.asyncio
    async def test_batch_usage_limits_reuse(
        self, lib_and_selector, tmp_path: Path
    ) -> None:
        lib, selector = lib_and_selector
        videos_dir = tmp_path / "reuse_test"

        # Only one video available
        v = _create_test_video(videos_dir / "only.mp4", duration=10.0, color="green")
        await lib.index_file(v, str(videos_dir))
        lib.update_tags(str(v.resolve()), ["vehicles"])

        # First two selections should succeed (MAX_REUSE_PER_BATCH=2)
        c1 = selector.select_for_scene("carros velozes", scene_index=0)
        c2 = selector.select_for_scene("mais carros", scene_index=1)
        assert c1 is not None
        assert c2 is not None

        # Third should fail (over limit)
        c3 = selector.select_for_scene("ainda carros", scene_index=2)
        assert c3 is None

    @pytest.mark.asyncio
    async def test_reset_batch_usage_allows_reuse(
        self, lib_and_selector, tmp_path: Path
    ) -> None:
        lib, selector = lib_and_selector
        videos_dir = tmp_path / "reset_test"

        v = _create_test_video(videos_dir / "single.mp4", duration=10.0, color="yellow")
        await lib.index_file(v, str(videos_dir))
        lib.update_tags(str(v.resolve()), ["gameplay"])

        # Exhaust reuse
        selector.select_for_scene("gameplay intenso", scene_index=0)
        selector.select_for_scene("mais gameplay", scene_index=1)
        assert selector.select_for_scene("gameplay", scene_index=2) is None

        # Reset and try again
        selector.reset_batch_usage()
        c = selector.select_for_scene("gameplay novo", scene_index=3)
        assert c is not None


class TestScriptSelection:
    """Test full script-to-clips selection."""

    @pytest.mark.asyncio
    async def test_select_for_script_coverage(
        self, lib_and_selector, tmp_path: Path
    ) -> None:
        lib, selector = lib_and_selector
        videos_dir = tmp_path / "script_test"

        colors = ["red", "blue", "green", "cyan", "purple"]
        for i, color in enumerate(colors):
            v = _create_test_video(
                videos_dir / f"clip_{i}.mp4", duration=8.0 + i, color=color
            )
            await lib.index_file(v, str(videos_dir))

        # Tag some clips
        assets = lib.search(limit=10)
        if len(assets) >= 2:
            lib.update_tags(assets[0].file_path, ["Vice City", "cenários urbanos"])
            lib.update_tags(assets[1].file_path, ["vehicles", "carros"])

        script = """[HOOK - 3s]
GTA 6 em Vice City!

[CONTEXTO - 8s]
Os veículos mais incríveis do jogo.

[DESENVOLVIMENTO - 15s]
Explorando os cenários urbanos e as praias.

[CTA - 4s]
Segue o Vice City Radar!"""

        result = selector.select_for_script(script)
        assert isinstance(result, SelectionResult)
        assert len(result.clips) + len(result.scenes_without_media) == 4
        assert result.coverage_ratio >= 0.0  # At least computed

    @pytest.mark.asyncio
    async def test_selection_result_summary(self, lib_and_selector) -> None:
        _, selector = lib_and_selector
        result = selector.select_for_script("[HOOK - 3s]\nTeste\n[CTA - 4s]\nFim")
        summary = result.summary()
        assert "Selected" in summary
        assert "coverage=" in summary


class TestClipSelectionDataclass:
    """Test ClipSelection properties."""

    def test_duration_with_end_time(self) -> None:
        asset = MediaAsset(
            file_path="/tmp/t.mp4", file_name="t.mp4",
            file_size=100, content_hash="x", duration_seconds=30.0,
        )
        clip = ClipSelection(
            asset=asset, scene_index=0, relevance_score=0.8,
            start_time=5.0, end_time=10.0,
        )
        assert clip.duration == 5.0

    def test_duration_without_end_time(self) -> None:
        asset = MediaAsset(
            file_path="/tmp/t.mp4", file_name="t.mp4",
            file_size=100, content_hash="x", duration_seconds=30.0,
        )
        clip = ClipSelection(
            asset=asset, scene_index=0, relevance_score=0.8,
            start_time=5.0,
        )
        assert clip.duration == 25.0  # 30 - 5