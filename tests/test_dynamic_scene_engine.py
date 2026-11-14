"""Tests for DynamicSceneEngine visual quality and motion."""

from __future__ import annotations

import hashlib
import pytest
from pathlib import Path

from PIL import Image

from src.production.dynamic_scene_engine import (
    DynamicSceneEngine,
    DynamicSceneSpec,
    WIDTH,
    HEIGHT,
)
from src.production.visual_identity import VICE_CITY_IDENTITY


@pytest.fixture
def engine() -> DynamicSceneEngine:
    return DynamicSceneEngine(VICE_CITY_IDENTITY)


class TestDynamicSceneEngineVisuals:
    """Test visual diversity, color richness, and motion."""

    def test_hook_frame_has_neon_colors(self, engine: DynamicSceneEngine) -> None:
        spec = DynamicSceneSpec(
            scene_type="hook",
            text="GTA 6 CONFIRMADO!",
            duration_seconds=1.0,
            accent_color=(255, 45, 120),
        )
        img = engine.render_frame(spec, 0, 30)
        assert img.size == (WIDTH, HEIGHT)
        # Check for neon pink pixels in the frame
        pixels = list(img.getdata())
        neon_pink_count = sum(
            1 for p in pixels
            if p[0] > 200 and p[1] < 80 and p[2] > 80
        )
        assert neon_pink_count > 100, "Hook frame should contain neon pink accent elements"

    def test_frames_vary_over_time(self, engine: DynamicSceneEngine) -> None:
        """Verify animated gradient produces different frames over time."""
        spec = DynamicSceneSpec(
            scene_type="hook",
            text="TESTE ANIMAÇÃO",
            duration_seconds=1.0,
        )
        hashes = set()
        for i in range(0, 30, 5):  # Sample every 5th frame
            img = engine.render_frame(spec, i, 30)
            thumb = img.resize((32, 32))
            h = hashlib.md5(thumb.tobytes()).hexdigest()
            hashes.add(h)
        assert len(hashes) >= 4, f"Expected at least 4 unique frames, got {len(hashes)}"

    def test_ken_burns_zoom_changes_frame(self, engine: DynamicSceneEngine) -> None:
        """Ken Burns zoom should produce visually different first vs last frame."""
        spec = DynamicSceneSpec(
            scene_type="info_card",
            text="Zoom test content for verification.",
            duration_seconds=2.0,
            zoom_start=1.0,
            zoom_end=1.15,
        )
        total = int(2.0 * 30)
        first = engine.render_frame(spec, 0, total)
        last = engine.render_frame(spec, total - 1, total)
        # Compare center regions — zoomed frame should differ
        f_thumb = first.resize((64, 64))
        l_thumb = last.resize((64, 64))
        f_hash = hashlib.md5(f_thumb.tobytes()).hexdigest()
        l_hash = hashlib.md5(l_thumb.tobytes()).hexdigest()
        assert f_hash != l_hash, "Ken Burns zoom should change frame appearance"

    def test_color_variance_above_threshold(self, engine: DynamicSceneEngine) -> None:
        """Frames should have rich color variance, not flat dark backgrounds."""
        spec = DynamicSceneSpec(
            scene_type="title_card",
            text="Color richness test.",
            duration_seconds=1.0,
            accent_color=(0, 220, 255),
        )
        img = engine.render_frame(spec, 15, 30).resize((64, 64))
        pixels = list(img.getdata())
        r_vals = [p[0] for p in pixels]
        g_vals = [p[1] for p in pixels]
        b_vals = [p[2] for p in pixels]
        r_var = sum((x - sum(r_vals) / len(r_vals)) ** 2 for x in r_vals) / len(r_vals)
        g_var = sum((x - sum(g_vals) / len(g_vals)) ** 2 for x in g_vals) / len(g_vals)
        b_var = sum((x - sum(b_vals) / len(b_vals)) ** 2 for x in b_vals) / len(b_vals)
        total_var = (r_var + g_var + b_var) / 3
        assert total_var > 150, f"Color variance {total_var:.0f} too low (expected >150)"

    def test_subtitle_bar_visible(self, engine: DynamicSceneEngine) -> None:
        """Subtitle bar should render with readable contrast."""
        spec = DynamicSceneSpec(
            scene_type="hook",
            text="Main title text.",
            duration_seconds=1.0,
            subtitle_text="Legenda visível aqui.",
        )
        img = engine.render_frame(spec, 0, 30)
        # Bottom region should have subtitle bar (darker semi-transparent area)
        bottom_region = img.crop((0, HEIGHT - 220, WIDTH, HEIGHT - 80))
        pixels = list(bottom_region.getdata())
        avg_brightness = sum(sum(p[:3]) / 3 for p in pixels) / len(pixels)
        # Subtitle bar bg is dark overlay; brightness should be lower than mid-frame
        assert avg_brightness < 120, "Subtitle bar region should be darker for readability"

    def test_cta_scene_has_button(self, engine: DynamicSceneEngine) -> None:
        """CTA scene should render a visible button element."""
        spec = DynamicSceneSpec(
            scene_type="cta",
            text="SEGUE O PERFIL!",
            duration_seconds=1.0,
            accent_color=(255, 140, 50),
        )
        img = engine.render_frame(spec, 15, 30)
        # Center region should have bright button pixels
        center = img.crop((100, HEIGHT // 2 - 100, WIDTH - 100, HEIGHT // 2 + 100))
        pixels = list(center.getdata())
        bright_pixels = sum(1 for p in pixels if sum(p[:3]) > 400)
        assert bright_pixels > 500, "CTA button should have visible bright pixels"

    @pytest.mark.asyncio
    async def test_render_sequence_produces_all_frames(
        self, engine: DynamicSceneEngine, tmp_path: Path
    ) -> None:
        specs = [
            DynamicSceneSpec(scene_type="hook", text="Hook!", duration_seconds=1.0),
            DynamicSceneSpec(scene_type="info_card", text="Info.", duration_seconds=2.0),
            DynamicSceneSpec(scene_type="cta", text="CTA!", duration_seconds=1.0),
        ]
        frames = await engine.render_sequence(specs, tmp_path / "frames")
        expected = int(1.0 * 30) + int(2.0 * 30) + int(1.0 * 30)
        assert len(frames) == expected
        assert all(f.exists() and f.stat().st_size > 0 for f in frames)

    def test_transition_scene_renders(self, engine: DynamicSceneEngine) -> None:
        """Transition scene type should render without error."""
        spec = DynamicSceneSpec(
            scene_type="transition",
            text="",
            duration_seconds=0.5,
            accent_color=(180, 60, 255),
        )
        img = engine.render_frame(spec, 5, 15)
        assert img.size == (WIDTH, HEIGHT)

    def test_alternating_accent_colors_differ(self, engine: DynamicSceneEngine) -> None:
        """Different accent colors should produce visually distinct frames."""
        spec_pink = DynamicSceneSpec(
            scene_type="hook", text="SAME TEXT", duration_seconds=1.0,
            accent_color=(255, 45, 120),
        )
        spec_cyan = DynamicSceneSpec(
            scene_type="hook", text="SAME TEXT", duration_seconds=1.0,
            accent_color=(0, 220, 255),
        )
        img_pink = engine.render_frame(spec_pink, 15, 30).resize((32, 32))
        img_cyan = engine.render_frame(spec_cyan, 15, 30).resize((32, 32))
        h_pink = hashlib.md5(img_pink.tobytes()).hexdigest()
        h_cyan = hashlib.md5(img_cyan.tobytes()).hexdigest()
        assert h_pink != h_cyan, "Different accent colors must produce different frames"