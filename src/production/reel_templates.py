"""Reel production templates for JHC Viral Engine.

Defines distinct visual and editorial templates for different content types.
Each template specifies scene structure, visual style, timing, and motion
parameters to ensure varied, professional-looking output instead of
repetitive gradient-only compositions.

Templates: breaking_news, curiosities, top5, theory, trailer_analysis,
           comparison, countdown, discovery, gameplay_commentary, news_summary
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class SceneTemplate:
    """Visual specification for a single scene within a template."""
    scene_type: str  # hook, context, development, cta, title_card, info_card, transition
    duration_seconds: float
    bg_style: str = "gradient"  # gradient, radial, split, neon_grid, image_overlay
    text_animation: str = "fade_in"  # fade_in, slide_up, typewriter, scale_in
    accent_color: tuple[int, int, int] = (255, 45, 120)
    zoom_start: float = 1.0
    zoom_end: float = 1.08
    pan_x_start: int = 0
    pan_x_end: int = 0
    glow_intensity: float = 0.6
    has_media_slot: bool = False  # Whether this scene expects video/image overlay


@dataclass(frozen=True)
class ReelTemplate:
    """Complete template for a Reel content type."""
    name: str
    description: str
    scenes: tuple[SceneTemplate, ...]
    total_duration: float
    category: str  # news, curiosities, theory, countdown, announcement, guide
    requires_media: bool = False  # True if template needs external media
    music_mood: str = ""  # energetic, mysterious, dramatic, chill, epic


# --- Template Definitions ---

BREAKING_NEWS = ReelTemplate(
    name="breaking_news",
    description="Urgent news flash with high-impact visuals",
    scenes=(
        SceneTemplate(
            scene_type="hook", duration_seconds=3.0,
            bg_style="neon_grid", text_animation="scale_in",
            accent_color=(255, 45, 120), zoom_start=1.15, zoom_end=1.0,
            glow_intensity=0.9,
        ),
        SceneTemplate(
            scene_type="title_card", duration_seconds=4.0,
            bg_style="gradient", text_animation="slide_up",
            accent_color=(255, 140, 50), zoom_start=1.0, zoom_end=1.05,
            has_media_slot=True,
        ),
        SceneTemplate(
            scene_type="info_card", duration_seconds=12.0,
            bg_style="gradient", text_animation="fade_in",
            accent_color=(0, 220, 255), zoom_start=1.0, zoom_end=1.08,
            has_media_slot=True,
        ),
        SceneTemplate(
            scene_type="info_card", duration_seconds=8.0,
            bg_style="radial", text_animation="fade_in",
            accent_color=(180, 60, 255), zoom_start=1.08, zoom_end=1.0,
            has_media_slot=True,
        ),
        SceneTemplate(
            scene_type="cta", duration_seconds=3.0,
            bg_style="gradient", text_animation="scale_in",
            accent_color=(255, 45, 120), zoom_start=1.0, zoom_end=1.05,
            glow_intensity=0.8,
        ),
    ),
    total_duration=30.0,
    category="news",
    requires_media=True,
    music_mood="energetic",
)

CURIOSITIES = ReelTemplate(
    name="curiosities",
    description="Did-you-know format with surprising reveals",
    scenes=(
        SceneTemplate(
            scene_type="hook", duration_seconds=3.0,
            bg_style="neon_grid", text_animation="typewriter",
            accent_color=(0, 220, 255), zoom_start=1.0, zoom_end=1.1,
            glow_intensity=0.7,
        ),
        SceneTemplate(
            scene_type="info_card", duration_seconds=10.0,
            bg_style="gradient", text_animation="slide_up",
            accent_color=(255, 220, 100), zoom_start=1.0, zoom_end=1.06,
            has_media_slot=True,
        ),
        SceneTemplate(
            scene_type="info_card", duration_seconds=10.0,
            bg_style="split", text_animation="fade_in",
            accent_color=(0, 220, 255), zoom_start=1.06, zoom_end=1.0,
            has_media_slot=True,
        ),
        SceneTemplate(
            scene_type="cta", duration_seconds=3.0,
            bg_style="gradient", text_animation="scale_in",
            accent_color=(255, 45, 120),
        ),
    ),
    total_duration=26.0,
    category="curiosities",
    requires_media=True,
    music_mood="mysterious",
)

TOP5 = ReelTemplate(
    name="top5",
    description="Ranked list format with numbered entries",
    scenes=(
        SceneTemplate(
            scene_type="hook", duration_seconds=3.0,
            bg_style="neon_grid", text_animation="scale_in",
            accent_color=(255, 140, 50), zoom_start=1.1, zoom_end=1.0,
            glow_intensity=0.8,
        ),
        SceneTemplate(
            scene_type="title_card", duration_seconds=3.0,
            bg_style="gradient", text_animation="slide_up",
            accent_color=(255, 45, 120),
        ),
        SceneTemplate(
            scene_type="info_card", duration_seconds=5.0,
            bg_style="gradient", text_animation="fade_in",
            accent_color=(0, 220, 255), zoom_start=1.0, zoom_end=1.05,
            has_media_slot=True,
        ),
        SceneTemplate(
            scene_type="info_card", duration_seconds=5.0,
            bg_style="gradient", text_animation="fade_in",
            accent_color=(180, 60, 255), zoom_start=1.0, zoom_end=1.05,
            has_media_slot=True,
        ),
        SceneTemplate(
            scene_type="info_card", duration_seconds=5.0,
            bg_style="gradient", text_animation="fade_in",
            accent_color=(255, 220, 100), zoom_start=1.0, zoom_end=1.05,
            has_media_slot=True,
        ),
        SceneTemplate(
            scene_type="cta", duration_seconds=3.0,
            bg_style="gradient", text_animation="scale_in",
            accent_color=(255, 45, 120),
        ),
    ),
    total_duration=29.0,
    category="news",
    requires_media=True,
    music_mood="energetic",
)

THEORY = ReelTemplate(
    name="theory",
    description="Speculative analysis with mysterious atmosphere",
    scenes=(
        SceneTemplate(
            scene_type="hook", duration_seconds=4.0,
            bg_style="radial", text_animation="fade_in",
            accent_color=(180, 60, 255), zoom_start=1.0, zoom_end=1.12,
            glow_intensity=0.9,
        ),
        SceneTemplate(
            scene_type="title_card", duration_seconds=5.0,
            bg_style="neon_grid", text_animation="slide_up",
            accent_color=(180, 60, 255), zoom_start=1.0, zoom_end=1.06,
        ),
        SceneTemplate(
            scene_type="info_card", duration_seconds=12.0,
            bg_style="gradient", text_animation="fade_in",
            accent_color=(0, 220, 255), zoom_start=1.0, zoom_end=1.08,
            has_media_slot=True,
        ),
        SceneTemplate(
            scene_type="info_card", duration_seconds=8.0,
            bg_style="split", text_animation="fade_in",
            accent_color=(255, 45, 120), zoom_start=1.08, zoom_end=1.0,
            has_media_slot=True,
        ),
        SceneTemplate(
            scene_type="cta", duration_seconds=3.0,
            bg_style="gradient", text_animation="scale_in",
            accent_color=(180, 60, 255),
        ),
    ),
    total_duration=32.0,
    category="theory",
    requires_media=True,
    music_mood="mysterious",
)

TRAILER_ANALYSIS = ReelTemplate(
    name="trailer_analysis",
    description="Frame-by-frame trailer breakdown",
    scenes=(
        SceneTemplate(
            scene_type="hook", duration_seconds=3.0,
            bg_style="neon_grid", text_animation="scale_in",
            accent_color=(255, 45, 120), zoom_start=1.15, zoom_end=1.0,
            glow_intensity=0.9,
        ),
        SceneTemplate(
            scene_type="info_card", duration_seconds=8.0,
            bg_style="gradient", text_animation="fade_in",
            accent_color=(0, 220, 255), zoom_start=1.0, zoom_end=1.06,
            has_media_slot=True,
        ),
        SceneTemplate(
            scene_type="info_card", duration_seconds=8.0,
            bg_style="gradient", text_animation="fade_in",
            accent_color=(255, 140, 50), zoom_start=1.0, zoom_end=1.06,
            has_media_slot=True,
        ),
        SceneTemplate(
            scene_type="info_card", duration_seconds=8.0,
            bg_style="gradient", text_animation="fade_in",
            accent_color=(180, 60, 255), zoom_start=1.0, zoom_end=1.06,
            has_media_slot=True,
        ),
        SceneTemplate(
            scene_type="cta", duration_seconds=3.0,
            bg_style="gradient", text_animation="scale_in",
            accent_color=(255, 45, 120),
        ),
    ),
    total_duration=30.0,
    category="news",
    requires_media=True,
    music_mood="dramatic",
)

COMPARISON = ReelTemplate(
    name="comparison",
    description="Side-by-side or sequential comparison format",
    scenes=(
        SceneTemplate(
            scene_type="hook", duration_seconds=3.0,
            bg_style="split", text_animation="scale_in",
            accent_color=(255, 220, 100), zoom_start=1.0, zoom_end=1.08,
        ),
        SceneTemplate(
            scene_type="info_card", duration_seconds=10.0,
            bg_style="gradient", text_animation="slide_up",
            accent_color=(0, 220, 255), zoom_start=1.0, zoom_end=1.05,
            has_media_slot=True,
        ),
        SceneTemplate(
            scene_type="info_card", duration_seconds=10.0,
            bg_style="gradient", text_animation="slide_up",
            accent_color=(255, 45, 120), zoom_start=1.0, zoom_end=1.05,
            has_media_slot=True,
        ),
        SceneTemplate(
            scene_type="cta", duration_seconds=3.0,
            bg_style="gradient", text_animation="scale_in",
            accent_color=(255, 140, 50),
        ),
    ),
    total_duration=26.0,
    category="news",
    requires_media=True,
    music_mood="energetic",
)

COUNTDOWN = ReelTemplate(
    name="countdown",
    description="Countdown timer format for launches and events",
    scenes=(
        SceneTemplate(
            scene_type="hook", duration_seconds=3.0,
            bg_style="neon_grid", text_animation="scale_in",
            accent_color=(255, 45, 120), zoom_start=1.2, zoom_end=1.0,
            glow_intensity=1.0,
        ),
        SceneTemplate(
            scene_type="title_card", duration_seconds=5.0,
            bg_style="gradient", text_animation="slide_up",
            accent_color=(255, 140, 50), zoom_start=1.0, zoom_end=1.08,
        ),
        SceneTemplate(
            scene_type="info_card", duration_seconds=12.0,
            bg_style="gradient", text_animation="fade_in",
            accent_color=(0, 220, 255), zoom_start=1.0, zoom_end=1.06,
            has_media_slot=True,
        ),
        SceneTemplate(
            scene_type="cta", duration_seconds=4.0,
            bg_style="gradient", text_animation="scale_in",
            accent_color=(255, 45, 120), glow_intensity=0.9,
        ),
    ),
    total_duration=24.0,
    category="countdown",
    requires_media=False,
    music_mood="epic",
)

DISCOVERY = ReelTemplate(
    name="discovery",
    description="Exploration and discovery format for new findings",
    scenes=(
        SceneTemplate(
            scene_type="hook", duration_seconds=3.0,
            bg_style="radial", text_animation="fade_in",
            accent_color=(0, 220, 255), zoom_start=1.0, zoom_end=1.1,
            glow_intensity=0.8,
        ),
        SceneTemplate(
            scene_type="info_card", duration_seconds=10.0,
            bg_style="gradient", text_animation="slide_up",
            accent_color=(255, 220, 100), zoom_start=1.0, zoom_end=1.06,
            has_media_slot=True,
        ),
        SceneTemplate(
            scene_type="info_card", duration_seconds=10.0,
            bg_style="neon_grid", text_animation="fade_in",
            accent_color=(0, 220, 255), zoom_start=1.0, zoom_end=1.08,
            has_media_slot=True,
        ),
        SceneTemplate(
            scene_type="cta", duration_seconds=3.0,
            bg_style="gradient", text_animation="scale_in",
            accent_color=(255, 45, 120),
        ),
    ),
    total_duration=26.0,
    category="news",
    requires_media=True,
    music_mood="mysterious",
)

GAMEPLAY_COMMENTARY = ReelTemplate(
    name="gameplay_commentary",
    description="Gameplay footage with voiceover commentary",
    scenes=(
        SceneTemplate(
            scene_type="hook", duration_seconds=3.0,
            bg_style="neon_grid", text_animation="scale_in",
            accent_color=(255, 45, 120), zoom_start=1.1, zoom_end=1.0,
        ),
        SceneTemplate(
            scene_type="info_card", duration_seconds=15.0,
            bg_style="gradient", text_animation="fade_in",
            accent_color=(0, 220, 255), zoom_start=1.0, zoom_end=1.04,
            has_media_slot=True,
        ),
        SceneTemplate(
            scene_type="info_card", duration_seconds=10.0,
            bg_style="gradient", text_animation="fade_in",
            accent_color=(255, 140, 50), zoom_start=1.0, zoom_end=1.04,
            has_media_slot=True,
        ),
        SceneTemplate(
            scene_type="cta", duration_seconds=3.0,
            bg_style="gradient", text_animation="scale_in",
            accent_color=(255, 45, 120),
        ),
    ),
    total_duration=31.0,
    category="guide",
    requires_media=True,
    music_mood="chill",
)

NEWS_SUMMARY = ReelTemplate(
    name="news_summary",
    description="Quick summary of multiple news items",
    scenes=(
        SceneTemplate(
            scene_type="hook", duration_seconds=3.0,
            bg_style="neon_grid", text_animation="scale_in",
            accent_color=(255, 45, 120), zoom_start=1.12, zoom_end=1.0,
            glow_intensity=0.8,
        ),
        SceneTemplate(
            scene_type="info_card", duration_seconds=6.0,
            bg_style="gradient", text_animation="slide_up",
            accent_color=(0, 220, 255), zoom_start=1.0, zoom_end=1.04,
            has_media_slot=True,
        ),
        SceneTemplate(
            scene_type="info_card", duration_seconds=6.0,
            bg_style="gradient", text_animation="slide_up",
            accent_color=(255, 140, 50), zoom_start=1.0, zoom_end=1.04,
            has_media_slot=True,
        ),
        SceneTemplate(
            scene_type="info_card", duration_seconds=6.0,
            bg_style="gradient", text_animation="slide_up",
            accent_color=(180, 60, 255), zoom_start=1.0, zoom_end=1.04,
            has_media_slot=True,
        ),
        SceneTemplate(
            scene_type="cta", duration_seconds=3.0,
            bg_style="gradient", text_animation="scale_in",
            accent_color=(255, 45, 120),
        ),
    ),
    total_duration=24.0,
    category="news",
    requires_media=True,
    music_mood="energetic",
)

# Registry of all available templates
ALL_TEMPLATES: dict[str, ReelTemplate] = {
    "breaking_news": BREAKING_NEWS,
    "curiosities": CURIOSITIES,
    "top5": TOP5,
    "theory": THEORY,
    "trailer_analysis": TRAILER_ANALYSIS,
    "comparison": COMPARISON,
    "countdown": COUNTDOWN,
    "discovery": DISCOVERY,
    "gameplay_commentary": GAMEPLAY_COMMENTARY,
    "news_summary": NEWS_SUMMARY,
}


def get_template(name: str) -> Optional[ReelTemplate]:
    """Get a template by name."""
    return ALL_TEMPLATES.get(name)


def select_template_for_category(category: str) -> ReelTemplate:
    """Select the best template for a content category."""
    category_map = {
        "news": BREAKING_NEWS,
        "announcement": BREAKING_NEWS,
        "rumor": DISCOVERY,
        "curiosities": CURIOSITIES,
        "theory": THEORY,
        "countdown": COUNTDOWN,
        "guide": GAMEPLAY_COMMENTARY,
        "review": COMPARISON,
        "analysis": TRAILER_ANALYSIS,
    }
    return category_map.get(category, NEWS_SUMMARY)


def list_templates() -> list[dict]:
    """List all available templates with metadata."""
    return [
        {
            "name": t.name,
            "description": t.description,
            "category": t.category,
            "duration": t.total_duration,
            "scene_count": len(t.scenes),
            "requires_media": t.requires_media,
            "music_mood": t.music_mood,
        }
        for t in ALL_TEMPLATES.values()
    ]