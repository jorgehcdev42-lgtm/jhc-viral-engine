"""Tests for Reel production templates — visual variety and editorial structure."""

from __future__ import annotations

import pytest

from src.production.reel_templates import (
    ALL_TEMPLATES,
    get_template,
    select_template_for_category,
    list_templates,
    SceneTemplate,
    ReelTemplate,
    BREAKING_NEWS,
    CURIOSITIES,
    TOP5,
    THEORY,
    TRAILER_ANALYSIS,
    COMPARISON,
    COUNTDOWN,
    DISCOVERY,
    GAMEPLAY_COMMENTARY,
    NEWS_SUMMARY,
)


class TestTemplateRegistry:
    """Test template registration and retrieval."""

    def test_all_templates_registered(self) -> None:
        assert len(ALL_TEMPLATES) == 10

    def test_get_template_by_name(self) -> None:
        t = get_template("breaking_news")
        assert t is not None
        assert t.name == "breaking_news"

    def test_get_template_unknown_returns_none(self) -> None:
        assert get_template("nonexistent") is None

    def test_list_templates_metadata(self) -> None:
        items = list_templates()
        assert len(items) == 10
        for item in items:
            assert "name" in item
            assert "description" in item
            assert "category" in item
            assert "duration" in item
            assert "scene_count" in item
            assert "requires_media" in item
            assert "music_mood" in item
            assert item["duration"] > 0
            assert item["scene_count"] >= 3


class TestCategorySelection:
    """Test automatic template selection by content category."""

    def test_news_selects_breaking_news(self) -> None:
        assert select_template_for_category("news").name == "breaking_news"

    def test_announcement_selects_breaking_news(self) -> None:
        assert select_template_for_category("announcement").name == "breaking_news"

    def test_rumor_selects_discovery(self) -> None:
        assert select_template_for_category("rumor").name == "discovery"

    def test_curiosities_selects_curiosities(self) -> None:
        assert select_template_for_category("curiosities").name == "curiosities"

    def test_theory_selects_theory(self) -> None:
        assert select_template_for_category("theory").name == "theory"

    def test_countdown_selects_countdown(self) -> None:
        assert select_template_for_category("countdown").name == "countdown"

    def test_guide_selects_gameplay_commentary(self) -> None:
        assert select_template_for_category("guide").name == "gameplay_commentary"

    def test_review_selects_comparison(self) -> None:
        assert select_template_for_category("review").name == "comparison"

    def test_analysis_selects_trailer_analysis(self) -> None:
        assert select_template_for_category("analysis").name == "trailer_analysis"

    def test_unknown_category_falls_back_to_news_summary(self) -> None:
        assert select_template_for_category("unknown_xyz").name == "news_summary"


class TestTemplateStructure:
    """Validate structural integrity of all templates."""

    @pytest.mark.parametrize("name", list(ALL_TEMPLATES.keys()))
    def test_valid_scene_types(self, name: str) -> None:
        valid = {"hook", "context", "development", "cta", "title_card", "info_card", "transition"}
        tmpl = ALL_TEMPLATES[name]
        for scene in tmpl.scenes:
            assert scene.scene_type in valid, f"{name}: invalid scene_type '{scene.scene_type}'"

    @pytest.mark.parametrize("name", list(ALL_TEMPLATES.keys()))
    def test_positive_duration(self, name: str) -> None:
        tmpl = ALL_TEMPLATES[name]
        assert tmpl.total_duration > 0, f"{name}: zero or negative duration"
        for scene in tmpl.scenes:
            assert scene.duration_seconds > 0, f"{name}: scene with zero duration"

    @pytest.mark.parametrize("name", list(ALL_TEMPLATES.keys()))
    def test_minimum_scene_count(self, name: str) -> None:
        tmpl = ALL_TEMPLATES[name]
        assert len(tmpl.scenes) >= 3, f"{name}: too few scenes ({len(tmpl.scenes)})"

    @pytest.mark.parametrize("name", list(ALL_TEMPLATES.keys()))
    def test_starts_with_hook(self, name: str) -> None:
        tmpl = ALL_TEMPLATES[name]
        assert tmpl.scenes[0].scene_type == "hook", f"{name}: first scene should be hook"

    @pytest.mark.parametrize("name", list(ALL_TEMPLATES.keys()))
    def test_ends_with_cta(self, name: str) -> None:
        tmpl = ALL_TEMPLATES[name]
        assert tmpl.scenes[-1].scene_type == "cta", f"{name}: last scene should be cta"

    @pytest.mark.parametrize("name", list(ALL_TEMPLATES.keys()))
    def test_valid_accent_colors(self, name: str) -> None:
        tmpl = ALL_TEMPLATES[name]
        for scene in tmpl.scenes:
            assert len(scene.accent_color) == 3, f"{name}: accent_color must be RGB tuple"
            assert all(0 <= c <= 255 for c in scene.accent_color), f"{name}: color out of 0-255 range"

    @pytest.mark.parametrize("name", list(ALL_TEMPLATES.keys()))
    def test_valid_bg_styles(self, name: str) -> None:
        valid_styles = {"gradient", "radial", "split", "neon_grid", "image_overlay"}
        tmpl = ALL_TEMPLATES[name]
        for scene in tmpl.scenes:
            assert scene.bg_style in valid_styles, f"{name}: invalid bg_style '{scene.bg_style}'"

    @pytest.mark.parametrize("name", list(ALL_TEMPLATES.keys()))
    def test_valid_text_animations(self, name: str) -> None:
        valid_anims = {"fade_in", "slide_up", "typewriter", "scale_in"}
        tmpl = ALL_TEMPLATES[name]
        for scene in tmpl.scenes:
            assert scene.text_animation in valid_anims, f"{name}: invalid animation '{scene.text_animation}'"


class TestVisualVariety:
    """Verify templates produce visually distinct outputs."""

    def test_templates_use_different_bg_styles(self) -> None:
        all_styles = set()
        for tmpl in ALL_TEMPLATES.values():
            for scene in tmpl.scenes:
                all_styles.add(scene.bg_style)
        assert len(all_styles) >= 4, f"Expected at least 4 bg styles, got {all_styles}"

    def test_templates_use_different_accent_colors(self) -> None:
        all_colors = set()
        for tmpl in ALL_TEMPLATES.values():
            for scene in tmpl.scenes:
                all_colors.add(scene.accent_color)
        assert len(all_colors) >= 4, f"Expected at least 4 accent colors, got {len(all_colors)}"

    def test_templates_use_different_animations(self) -> None:
        all_anims = set()
        for tmpl in ALL_TEMPLATES.values():
            for scene in tmpl.scenes:
                all_anims.add(scene.text_animation)
        assert len(all_anims) >= 3, f"Expected at least 3 animations, got {all_anims}"

    def test_templates_have_varying_durations(self) -> None:
        durations = [t.total_duration for t in ALL_TEMPLATES.values()]
        assert max(durations) - min(durations) >= 5.0, "Templates should have varied durations"

    def test_some_templates_require_media(self) -> None:
        media_required = sum(1 for t in ALL_TEMPLATES.values() if t.requires_media)
        assert media_required >= 7, f"At least 7 templates should require media, got {media_required}"

    def test_countdown_does_not_require_media(self) -> None:
        assert not COUNTDOWN.requires_media


class TestSceneTemplateDataclass:
    """Test SceneTemplate frozen dataclass properties."""

    def test_default_values(self) -> None:
        s = SceneTemplate(scene_type="hook", duration_seconds=3.0)
        assert s.bg_style == "gradient"
        assert s.text_animation == "fade_in"
        assert s.zoom_start == 1.0
        assert s.zoom_end == 1.08
        assert s.glow_intensity == 0.6
        assert s.has_media_slot is False

    def test_custom_values(self) -> None:
        s = SceneTemplate(
            scene_type="info_card",
            duration_seconds=10.0,
            bg_style="neon_grid",
            text_animation="slide_up",
            accent_color=(0, 255, 0),
            zoom_start=1.1,
            zoom_end=1.0,
            glow_intensity=0.9,
            has_media_slot=True,
        )
        assert s.bg_style == "neon_grid"
        assert s.has_media_slot is True
        assert s.accent_color == (0, 255, 0)


class TestReelTemplateDataclass:
    """Test ReelTemplate frozen dataclass properties."""

    def test_music_moods_varied(self) -> None:
        moods = {t.music_mood for t in ALL_TEMPLATES.values()}
        assert len(moods) >= 4, f"Expected at least 4 music moods, got {moods}"

    def test_categories_cover_main_types(self) -> None:
        categories = {t.category for t in ALL_TEMPLATES.values()}
        assert "news" in categories
        assert "theory" in categories
        assert "countdown" in categories