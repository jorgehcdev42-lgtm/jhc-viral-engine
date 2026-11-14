"""Tests for JHC Smart Media Library — SQLite catalog and indexing."""

from __future__ import annotations

import json
import shutil
import subprocess
import pytest
from pathlib import Path

from src.media.library import (
    SmartMediaLibrary,
    MediaAsset,
    IndexProgress,
    VIDEO_EXTENSIONS,
)


@pytest.fixture
def lib(tmp_path: Path) -> SmartMediaLibrary:
    db = tmp_path / "test_media.db"
    thumbs = tmp_path / "thumbs"
    return SmartMediaLibrary(db, thumbs)


def _create_test_video(path: Path, duration: float = 2.0, color: str = "red") -> Path:
    """Create a minimal test video using FFmpeg."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg not available")
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi",
        "-i", f"color=c={color}:s=320x240:r=25:d={duration}",
        "-f", "lavfi",
        "-i", "anullsrc=r=44100:cl=stereo",
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


class TestLibraryInit:
    """Test database initialization and basic operations."""

    def test_db_created_on_init(self, tmp_path: Path) -> None:
        db = tmp_path / "init_test.db"
        thumbs = tmp_path / "thumbs"
        SmartMediaLibrary(db, thumbs)
        assert db.exists()
        assert thumbs.exists()

    def test_empty_stats(self, lib: SmartMediaLibrary) -> None:
        stats = lib.get_stats()
        assert stats["total_files"] == 0
        assert stats["corrupt_files"] == 0
        assert stats["total_size_bytes"] == 0

    def test_search_empty_returns_empty(self, lib: SmartMediaLibrary) -> None:
        results = lib.search(query="anything")
        assert len(results) == 0

    def test_verify_empty_library(self, lib: SmartMediaLibrary) -> None:
        verify = lib.verify_files_exist()
        assert verify["total_indexed"] == 0
        assert verify["missing"] == 0


class TestFileIndexing:
    """Test single file indexing with metadata extraction."""

    @pytest.mark.asyncio
    async def test_index_single_video(self, lib: SmartMediaLibrary, tmp_path: Path) -> None:
        video = _create_test_video(tmp_path / "videos" / "test.mp4")
        asset = await lib.index_file(video, str(tmp_path))
        assert asset is not None
        assert asset.file_name == "test.mp4"
        assert asset.file_size > 0
        assert len(asset.content_hash) == 64  # SHA-256 hex
        assert asset.duration_seconds is not None
        assert asset.duration_seconds > 0
        assert asset.width == 320
        assert asset.height == 240
        assert asset.codec == "h264"
        assert not asset.is_corrupt

    @pytest.mark.asyncio
    async def test_duplicate_file_skipped(self, lib: SmartMediaLibrary, tmp_path: Path) -> None:
        video = _create_test_video(tmp_path / "videos" / "dup.mp4")
        first = await lib.index_file(video, str(tmp_path))
        second = await lib.index_file(video, str(tmp_path))
        assert first is not None
        assert second is None  # Skipped as duplicate path

    @pytest.mark.asyncio
    async def test_hash_duplicate_detected(self, lib: SmartMediaLibrary, tmp_path: Path) -> None:
        video1 = _create_test_video(tmp_path / "videos" / "original.mp4", color="blue")
        # Copy same file to different name
        video2 = tmp_path / "videos" / "copy.mp4"
        shutil.copy2(video1, video2)

        first = await lib.index_file(video1, str(tmp_path))
        second = await lib.index_file(video2, str(tmp_path))
        assert first is not None
        assert second is None  # Same hash = duplicate content

    @pytest.mark.asyncio
    async def test_thumbnail_generated(self, lib: SmartMediaLibrary, tmp_path: Path) -> None:
        video = _create_test_video(tmp_path / "videos" / "thumb_test.mp4")
        asset = await lib.index_file(video, str(tmp_path))
        assert asset is not None
        if asset.thumbnail_path:
            assert Path(asset.thumbnail_path).exists()


class TestDirectoryIndexing:
    """Test batch directory scanning and indexing."""

    @pytest.mark.asyncio
    async def test_scan_finds_videos(self, lib: SmartMediaLibrary, tmp_path: Path) -> None:
        videos_dir = tmp_path / "scan_test"
        _create_test_video(videos_dir / "a.mp4")
        _create_test_video(videos_dir / "b.mov")
        _create_test_video(videos_dir / "sub" / "c.mkv")
        # Non-video file should be ignored
        (videos_dir / "readme.txt").write_text("not a video")

        found = await lib.scan_directory(videos_dir, recursive=True)
        assert len(found) == 3

    @pytest.mark.asyncio
    async def test_scan_non_recursive(self, lib: SmartMediaLibrary, tmp_path: Path) -> None:
        videos_dir = tmp_path / "flat_scan"
        _create_test_video(videos_dir / "top.mp4")
        _create_test_video(videos_dir / "sub" / "nested.mp4")

        found = await lib.scan_directory(videos_dir, recursive=False)
        assert len(found) == 1

    @pytest.mark.asyncio
    async def test_index_directory_progress(self, lib: SmartMediaLibrary, tmp_path: Path) -> None:
        videos_dir = tmp_path / "batch_test"
        colors = ["red", "green", "blue"]
        for i, color in enumerate(colors):
            _create_test_video(videos_dir / f"video_{i}.mp4", duration=1.0 + i * 0.5, color=color)

        progress = await lib.index_directory(videos_dir)
        assert progress.total_files == 3
        assert progress.indexed == 3
        assert progress.skipped_duplicate == 0
        assert progress.errors == 0

    @pytest.mark.asyncio
    async def test_nonexistent_directory(self, lib: SmartMediaLibrary, tmp_path: Path) -> None:
        found = await lib.scan_directory(tmp_path / "does_not_exist")
        assert len(found) == 0


class TestSearchAndFilter:
    """Test search with various filters."""

    @pytest.mark.asyncio
    async def test_search_by_filename(self, lib: SmartMediaLibrary, tmp_path: Path) -> None:
        v1 = _create_test_video(tmp_path / "searchable_alpha.mp4")
        v2 = _create_test_video(tmp_path / "searchable_beta.mp4")
        await lib.index_file(v1, str(tmp_path))
        await lib.index_file(v2, str(tmp_path))

        results = lib.search(query="alpha")
        assert len(results) == 1
        assert "alpha" in results[0].file_name

    @pytest.mark.asyncio
    async def test_search_by_category(self, lib: SmartMediaLibrary, tmp_path: Path) -> None:
        v1 = _create_test_video(tmp_path / "cat_vice.mp4")
        v2 = _create_test_video(tmp_path / "cat_gameplay.mp4")
        await lib.index_file(v1, str(tmp_path))
        await lib.index_file(v2, str(tmp_path))

        lib.update_category(str(v1.resolve()), "Vice City")
        lib.update_category(str(v2.resolve()), "Gameplay")

        results = lib.search(category="Vice City")
        assert len(results) == 1
        assert results[0].category == "Vice City"

    @pytest.mark.asyncio
    async def test_search_by_duration_range(self, lib: SmartMediaLibrary, tmp_path: Path) -> None:
        short = _create_test_video(tmp_path / "short.mp4", duration=1.0)
        long = _create_test_video(tmp_path / "long.mp4", duration=5.0)
        await lib.index_file(short, str(tmp_path))
        await lib.index_file(long, str(tmp_path))

        results = lib.search(min_duration=3.0)
        assert len(results) >= 1
        assert all(r.duration_seconds >= 3.0 for r in results)

    @pytest.mark.asyncio
    async def test_search_pagination(self, lib: SmartMediaLibrary, tmp_path: Path) -> None:
        colors = ["red", "green", "blue", "yellow", "cyan"]
        for i, color in enumerate(colors):
            v = _create_test_video(tmp_path / f"page_{i}.mp4", duration=1.0 + i * 0.3, color=color)
            await lib.index_file(v, str(tmp_path))

        page1 = lib.search(limit=2, offset=0)
        page2 = lib.search(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0].file_path != page2[0].file_path


class TestTagAndMetadata:
    """Test tag updates, category assignment, and rights status."""

    @pytest.mark.asyncio
    async def test_update_tags(self, lib: SmartMediaLibrary, tmp_path: Path) -> None:
        v = _create_test_video(tmp_path / "tagged.mp4")
        await lib.index_file(v, str(tmp_path))

        updated = lib.update_tags(str(v.resolve()), ["vehicles", "chase", "vice city"])
        assert updated

        results = lib.search(query="vehicles")
        assert len(results) == 1
        assert "vehicles" in results[0].tags

    @pytest.mark.asyncio
    async def test_update_rights_status(self, lib: SmartMediaLibrary, tmp_path: Path) -> None:
        v = _create_test_video(tmp_path / "rights.mp4")
        await lib.index_file(v, str(tmp_path))

        lib.update_rights_status(str(v.resolve()), "authorized")
        results = lib.search(rights_status="authorized")
        assert len(results) == 1
        assert results[0].rights_status == "authorized"

    def test_invalid_rights_status_raises(self, lib: SmartMediaLibrary) -> None:
        with pytest.raises(ValueError, match="Invalid rights status"):
            lib.update_rights_status("/nonexistent.mp4", "invalid_status")


class TestFileVerification:
    """Test detection of missing/moved files."""

    @pytest.mark.asyncio
    async def test_detect_missing_files(self, lib: SmartMediaLibrary, tmp_path: Path) -> None:
        v = _create_test_video(tmp_path / "will_delete.mp4")
        await lib.index_file(v, str(tmp_path))

        # Delete the file
        v.unlink()

        verify = lib.verify_files_exist()
        assert verify["missing"] == 1
        assert verify["present"] == 0

    @pytest.mark.asyncio
    async def test_all_files_present(self, lib: SmartMediaLibrary, tmp_path: Path) -> None:
        v = _create_test_video(tmp_path / "stays.mp4")
        await lib.index_file(v, str(tmp_path))

        verify = lib.verify_files_exist()
        assert verify["missing"] == 0
        assert verify["present"] == 1


class TestIndexProgress:
    """Test progress tracking dataclass."""

    def test_progress_summary(self) -> None:
        p = IndexProgress(total_files=100, scanned=50, indexed=45, skipped_duplicate=3, skipped_corrupt=2)
        summary = p.summary()
        assert "45/100" in summary
        assert "50.0%" in summary
        assert "duplicates=3" in summary

    def test_progress_percent_zero_total(self) -> None:
        p = IndexProgress(total_files=0)
        assert p.percent == 0.0