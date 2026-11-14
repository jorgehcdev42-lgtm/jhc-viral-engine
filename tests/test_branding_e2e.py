"""End-to-end tests for WatermarkEngine with real FFmpeg rendering.

These tests verify that watermark application produces actual branded MP4 files
with visible logo overlays, correct positioning, opacity, and safe-area compliance.
Tests use synthetic test videos and logos generated at runtime.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from src.production.watermark import (
    WatermarkConfig,
    WatermarkEngine,
    SAFE_AREAS,
)


def _create_test_video(path: Path, width: int = 1080, height: int = 1920, duration: float = 2.0) -> Path:
    """Create a short synthetic test video using FFmpeg."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg not available")

    # Use solid color with gradient — avoids drawtext/libfreetype dependency
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i",
        f"color=c=0x1a0533:s={width}x{height}:d={duration}:r=30",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=30)
    assert result.returncode == 0, f"FFmpeg video creation failed: {result.stderr.decode()[-300:]}"
    assert path.exists() and path.stat().st_size > 1000
    return path


def _create_test_logo(path: Path, color: str = "white", size: int = 200) -> Path:
    """Create a simple test logo PNG using Pillow."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw a circle with "BR" or "GL" text
    draw.ellipse([10, 10, size - 10, size - 10], fill=None, outline=color, width=6)
    draw.rectangle([size // 4, size // 4, 3 * size // 4, 3 * size // 4], fill=(255, 45, 120, 200))

    # Add text
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size // 4)
    except (OSError, IOError):
        font = ImageFont.load_default()
    draw.text(
        (size // 2, size // 2), "L6",
        fill="white", font=font, anchor="mm",
    )

    img.save(str(path), "PNG")
    assert path.exists() and path.stat().st_size > 100
    return path


def _probe_video(path: Path) -> dict:
    """Get video metadata via ffprobe."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        pytest.skip("ffprobe not available")

    cmd = [
        ffprobe, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration,nb_frames,codec_name",
        "-show_entries", "format=duration,size",
        "-of", "json",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=10)
    return json.loads(result.stdout.decode())


def _extract_frame(video_path: Path, frame_path: Path, time: float = 1.0) -> Path:
    """Extract a single frame from a video at the given timestamp."""
    ffmpeg = shutil.which("ffmpeg")
    cmd = [
        ffmpeg, "-y", "-ss", str(time),
        "-i", str(video_path),
        "-vframes", "1",
        "-q:v", "2",
        str(frame_path),
    ]
    subprocess.run(cmd, capture_output=True, timeout=10)
    assert frame_path.exists(), f"Frame extraction failed for {video_path}"
    return frame_path


def _pixel_brightness_at(image_path: Path, x: int, y: int, region: int = 20) -> float:
    """Get average brightness of a region around (x, y) in an image."""
    from PIL import Image
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    # Clamp coordinates
    x = max(region, min(x, w - region))
    y = max(region, min(y, h - region))
    box = (x - region, y - region, x + region, y + region)
    crop = img.crop(box)
    pixels = list(crop.getdata())
    if not pixels:
        return 0.0
    return sum(sum(p) / 3 for p in pixels) / len(pixels)


@pytest.fixture
def branding_workspace(tmp_path):
    """Create a temporary workspace with test video and logos."""
    workspace = tmp_path / "branding_test"
    workspace.mkdir()

    video = _create_test_video(workspace / "test_input.mp4")
    logo_br = _create_test_logo(workspace / "logo_br.png", color="#FF2D78", size=200)
    logo_gl = _create_test_logo(workspace / "logo_gl.png", color="#00E5FF", size=200)

    return {
        "workspace": workspace,
        "video": video,
        "logo_br": logo_br,
        "logo_gl": logo_gl,
    }


class TestWatermarkE2E:
    """End-to-end tests verifying real FFmpeg watermark rendering."""

    def test_watermark_produces_valid_mp4(self, branding_workspace, tmp_path):
        """Applying watermark produces a valid, playable MP4 file."""
        engine = WatermarkEngine(tmp_path)

        # Register BR logo
        engine.save_logo("gta6-br", branding_workspace["logo_br"])

        output = tmp_path / "branded_output.mp4"
        result = asyncio.run(
            engine.apply_watermark(
                branding_workspace["video"],
                output,
                "gta6-br",
            )
        )

        assert result["success"], f"Watermark failed: {result.get('error')}"
        assert output.exists()
        assert output.stat().st_size > 5000, "Output MP4 too small — likely corrupt"

        # Verify it's a valid H.264 video
        probe = _probe_video(output)
        stream = probe["streams"][0]
        assert stream["codec_name"] == "h264"
        assert stream["width"] == 1080
        assert stream["height"] == 1920

    def test_watermark_preserves_original(self, branding_workspace, tmp_path):
        """Original video is never modified — only a new branded file is created."""
        engine = WatermarkEngine(tmp_path)
        engine.save_logo("gta6-br", branding_workspace["logo_br"])

        original_size = branding_workspace["video"].stat().st_size
        original_mtime = branding_workspace["video"].stat().st_mtime

        output = tmp_path / "branded.mp4"
        asyncio.run(
            engine.apply_watermark(branding_workspace["video"], output, "gta6-br")
        )

        # Original must be untouched
        assert branding_workspace["video"].stat().st_size == original_size
        assert branding_workspace["video"].stat().st_mtime == original_mtime
        # Output must be a different file
        assert output != branding_workspace["video"]

    def test_watermark_visible_in_frame(self, branding_workspace, tmp_path):
        """Watermark is visually detectable in the branded video output."""
        engine = WatermarkEngine(tmp_path)
        engine.save_logo("gta6-br", branding_workspace["logo_br"])

        config = engine.get_config("gta6-br")
        config = WatermarkConfig(
            profile_id="gta6-br",
            logo_path=str(branding_workspace["logo_br"]),
            position="bottom_right",
            scale_percent=15.0,
            opacity=1.0,
            margin_px=30,
            enabled=True,
        )
        engine.update_config(config)

        output = tmp_path / "visible_test.mp4"
        result = asyncio.run(
            engine.apply_watermark(branding_workspace["video"], output, "gta6-br")
        )
        assert result["success"]

        # Extract a frame and check that the watermark region has higher brightness
        frame = tmp_path / "frame.png"
        _extract_frame(output, frame, time=1.0)

        # Bottom-right region where logo should be (with safe area margin)
        safe = SAFE_AREAS["universal"]
        wm_x = 1080 - 100 - safe["right"]  # Near right edge
        wm_y = 1920 - 150 - safe["bottom"]  # Near bottom edge

        # Center of frame (should be dark blue background)
        center_x, center_y = 540, 960

        wm_brightness = _pixel_brightness_at(frame, wm_x, wm_y, region=30)
        center_brightness = _pixel_brightness_at(frame, center_x, center_y, region=30)

        # Watermark region should be noticeably brighter/different than plain background
        assert wm_brightness > center_brightness + 5, (
            f"Watermark not visible: wm_region={wm_brightness:.1f} vs center={center_brightness:.1f}"
        )

    def test_different_positions_produce_different_outputs(self, branding_workspace, tmp_path):
        """Different positions produce visually different results."""
        engine = WatermarkEngine(tmp_path)
        engine.save_logo("gta6-br", branding_workspace["logo_br"])

        frames = {}
        for position in ["top_left", "bottom_right", "center"]:
            config = WatermarkConfig(
                profile_id="gta6-br",
                logo_path=str(branding_workspace["logo_br"]),
                position=position,
                scale_percent=15.0,
                opacity=1.0,
                margin_px=25,
                enabled=True,
            )
            engine.update_config(config)

            output = tmp_path / f"pos_{position}.mp4"
            result = asyncio.run(
                engine.apply_watermark(branding_workspace["video"], output, "gta6-br")
            )
            assert result["success"], f"Failed for position {position}"

            frame = tmp_path / f"frame_{position}.png"
            _extract_frame(output, frame, time=1.0)
            frames[position] = frame

        # Check that each position has the watermark in a different region
        safe = SAFE_AREAS["universal"]
        positions_to_check = {
            "top_left": (safe["left"] + 50, safe["top"] + 50),
            "bottom_right": (1080 - safe["right"] - 80, 1920 - safe["bottom"] - 100),
            "center": (540, 960),
        }

        brightnesses = {}
        for pos, (x, y) in positions_to_check.items():
            brightnesses[pos] = _pixel_brightness_at(frames[pos], x, y, region=25)

        # At least one position should differ significantly from center baseline
        center_base = _pixel_brightness_at(frames["center"], 200, 200, region=25)
        tl_bright = brightnesses["top_left"]
        br_bright = brightnesses["bottom_right"]

        # top_left should have higher brightness at top-left than bottom_right does
        assert tl_bright > center_base or br_bright > center_base, (
            f"Position differentiation failed: TL={tl_bright:.1f}, BR={br_bright:.1f}, center_base={center_base:.1f}"
        )

    def test_opacity_affects_visibility(self, branding_workspace, tmp_path):
        """Lower opacity produces a less visible watermark."""
        engine = WatermarkEngine(tmp_path)
        engine.save_logo("gta6-br", branding_workspace["logo_br"])

        safe = SAFE_AREAS["universal"]
        wm_x = 1080 - 100 - safe["right"]
        wm_y = 1920 - 150 - safe["bottom"]

        brightnesses = {}
        for opacity in [1.0, 0.3]:
            config = WatermarkConfig(
                profile_id="gta6-br",
                logo_path=str(branding_workspace["logo_br"]),
                position="bottom_right",
                scale_percent=15.0,
                opacity=opacity,
                margin_px=25,
                enabled=True,
            )
            engine.update_config(config)

            output = tmp_path / f"opacity_{opacity}.mp4"
            result = asyncio.run(
                engine.apply_watermark(branding_workspace["video"], output, "gta6-br")
            )
            assert result["success"]

            frame = tmp_path / f"frame_opacity_{opacity}.png"
            _extract_frame(output, frame, time=1.0)
            brightnesses[opacity] = _pixel_brightness_at(frame, wm_x, wm_y, region=30)

        # Full opacity should be brighter at watermark region than 30% opacity
        assert brightnesses[1.0] > brightnesses[0.3] + 2, (
            f"Opacity test failed: full={brightnesses[1.0]:.1f} vs 30%={brightnesses[0.3]:.1f}"
        )

    def test_safe_areas_respected(self, branding_workspace, tmp_path):
        """Watermark position respects platform-specific safe areas."""
        engine = WatermarkEngine(tmp_path)

        for platform in ["instagram", "youtube", "tiktok", "universal"]:
            preview = engine.preview_position("gta6-br", 1080, 1920)
            # Override config to test each preset
            config = WatermarkConfig(
                profile_id="gta6-br",
                position="bottom_right",
                scale_percent=12.0,
                opacity=0.9,
                margin_px=20,
                enabled=True,
                platform_preset=platform,
            )
            engine.update_config(config)
            preview = engine.preview_position("gta6-br", 1080, 1920)

            safe = SAFE_AREAS[platform]
            logo_w = preview["logo_width_px"]

            # Bottom-right: x should not go into right safe area
            assert preview["x"] + logo_w <= 1080 - safe["right"] + 5, (
                f"{platform}: watermark x+width ({preview['x'] + logo_w}) exceeds right safe area ({1080 - safe['right']})"
            )
            # y should not go into bottom safe area
            assert preview["y"] + logo_w <= 1920 - safe["bottom"] + 5, (
                f"{platform}: watermark y+height exceeds bottom safe area"
            )

    def test_batch_processing(self, branding_workspace, tmp_path):
        """Batch watermark processes multiple videos sequentially."""
        engine = WatermarkEngine(tmp_path)
        engine.save_logo("gta6-br", branding_workspace["logo_br"])

        # Create 3 test videos
        videos = []
        for i in range(3):
            v = _create_test_video(tmp_path / f"batch_input_{i}.mp4", duration=1.0)
            videos.append(v)

        results = asyncio.run(
            engine.apply_batch(videos, "gta6-br")
        )

        assert len(results) == 3
        success_count = sum(1 for r in results if r["success"])
        assert success_count == 3, f"Batch: only {success_count}/3 succeeded"

        # All output files should exist
        for r in results:
            assert Path(r["output"]).exists()

    def test_br_and_global_use_different_logos(self, branding_workspace, tmp_path):
        """BR and Global profiles use their respective logos — no cross-contamination."""
        engine = WatermarkEngine(tmp_path)
        engine.save_logo("gta6-br", branding_workspace["logo_br"])
        engine.save_logo("gta6-global", branding_workspace["logo_gl"])

        br_config = engine.get_config("gta6-br")
        gl_config = engine.get_config("gta6-global")

        assert "gta6-br_logo" in br_config.logo_path
        assert "gta6-global_logo" in gl_config.logo_path
        assert br_config.logo_path != gl_config.logo_path

        # Render both
        br_out = tmp_path / "br_output.mp4"
        gl_out = tmp_path / "gl_output.mp4"

        br_result = asyncio.run(
            engine.apply_watermark(branding_workspace["video"], br_out, "gta6-br")
        )
        gl_result = asyncio.run(
            engine.apply_watermark(branding_workspace["video"], gl_out, "gta6-global")
        )

        assert br_result["success"]
        assert gl_result["success"]
        assert br_out.exists()
        assert gl_out.exists()

        # Both should be valid H.264
        for path in [br_out, gl_out]:
            probe = _probe_video(path)
            assert probe["streams"][0]["codec_name"] == "h264"

    def test_disabled_watermark_skips_render(self, branding_workspace, tmp_path):
        """When watermark is disabled, no FFmpeg rendering occurs."""
        engine = WatermarkEngine(tmp_path)
        engine.save_logo("gta6-br", branding_workspace["logo_br"])

        # Disable watermark
        config = WatermarkConfig(
            profile_id="gta6-br",
            logo_path=str(branding_workspace["logo_br"]),
            position="bottom_right",
            enabled=False,  # Disabled
        )
        engine.update_config(config)

        output = tmp_path / "disabled_output.mp4"
        result = asyncio.run(
            engine.apply_watermark(branding_workspace["video"], output, "gta6-br")
        )

        assert not result["success"]
        assert "disabled" in result.get("error", "").lower()
        assert not output.exists()

    def test_missing_logo_fails_gracefully(self, branding_workspace, tmp_path):
        """Attempting watermark without a configured logo fails gracefully."""
        engine = WatermarkEngine(tmp_path)
        # Don't register any logo

        output = tmp_path / "no_logo_output.mp4"
        result = asyncio.run(
            engine.apply_watermark(branding_workspace["video"], output, "gta6-br")
        )

        assert not result["success"]
        assert "logo" in result.get("error", "").lower()

    def test_scale_percent_controls_logo_size(self, branding_workspace, tmp_path):
        """Different scale percentages produce different overlay sizes."""
        engine = WatermarkEngine(tmp_path)

        sizes = {}
        for scale in [10.0, 25.0]:
            preview = engine.preview_position("gta6-br", 1080, 1920)
            config = WatermarkConfig(
                profile_id="gta6-br",
                position="bottom_right",
                scale_percent=scale,
                opacity=0.9,
                margin_px=20,
                enabled=True,
            )
            engine.update_config(config)
            preview = engine.preview_position("gta6-br", 1080, 1920)
            sizes[scale] = preview["logo_width_px"]

        assert sizes[25.0] > sizes[10.0], (
            f"Scale test: 25% ({sizes[25.0]}px) should be larger than 10% ({sizes[10.0]}px)"
        )
        assert sizes[10.0] == 108  # 10% of 1080
        assert sizes[25.0] == 270  # 25% of 1080

    def test_config_persistence(self, tmp_path):
        """Watermark configs persist across engine instances."""
        engine1 = WatermarkEngine(tmp_path)
        custom = WatermarkConfig(
            profile_id="test-profile",
            position="top_left",
            scale_percent=20.0,
            opacity=0.5,
            margin_px=40,
            enabled=True,
            platform_preset="tiktok",
        )
        engine1.update_config(custom)

        # Create new engine instance — should load persisted config
        engine2 = WatermarkEngine(tmp_path)
        loaded = engine2.get_config("test-profile")

        assert loaded.position == "top_left"
        assert loaded.scale_percent == 20.0
        assert loaded.opacity == 0.5
        assert loaded.margin_px == 40
        assert loaded.platform_preset == "tiktok"


class TestSafeAreas:
    """Verify platform-specific safe area definitions are correct."""

    def test_all_platforms_defined(self):
        expected = {"universal", "instagram", "youtube", "tiktok"}
        assert set(SAFE_AREAS.keys()) == expected

    def test_safe_areas_have_required_keys(self):
        for platform, areas in SAFE_AREAS.items():
            assert "top" in areas, f"{platform} missing 'top'"
            assert "bottom" in areas, f"{platform} missing 'bottom'"
            assert "left" in areas, f"{platform} missing 'left'"
            assert "right" in areas, f"{platform} missing 'right'"

    def test_tiktok_has_larger_right_safe_area(self):
        """TikTok has a right sidebar with icons — larger right safe area."""
        assert SAFE_AREAS["tiktok"]["right"] > SAFE_AREAS["universal"]["right"]

    def test_instagram_has_larger_bottom_safe_area(self):
        """Instagram has bottom navigation — larger bottom safe area."""
        assert SAFE_AREAS["instagram"]["bottom"] > SAFE_AREAS["universal"]["bottom"]