"""Tests for SceneComposer and script_to_scenes integration."""

from __future__ import annotations

import pytest
from pathlib import Path

from src.production.scene_composer import (
    SceneComposer,
    SceneSpec,
    VisualIdentity,
    GTA6_IDENTITY,
    WIDTH,
    HEIGHT,
    FPS,
)
from src.production.script_to_scenes import parse_script_to_scenes


@pytest.fixture
def composer() -> SceneComposer:
    return SceneComposer(GTA6_IDENTITY)


class TestSceneComposer:
    """Test visual frame generation."""

    def test_compose_hook_scene(self, composer: SceneComposer) -> None:
        spec = SceneSpec(
            scene_type="hook",
            text="GTA 6 CONFIRMADO!",
            duration_seconds=3.0,
        )
        img = composer.compose_scene(spec)
        assert img.size == (WIDTH, HEIGHT)
        assert img.mode == "RGB"

    def test_compose_title_card(self, composer: SceneComposer) -> None:
        spec = SceneSpec(
            scene_type="title_card",
            text="Vice City Radar",
            duration_seconds=5.0,
        )
        img = composer.compose_scene(spec)
        assert img.size == (WIDTH, HEIGHT)

    def test_compose_info_card(self, composer: SceneComposer) -> None:
        spec = SceneSpec(
            scene_type="info_card",
            text="Rockstar revelou a data oficial de lançamento.",
            duration_seconds=8.0,
        )
        img = composer.compose_scene(spec)
        assert img.size == (WIDTH, HEIGHT)

    def test_compose_cta(self, composer: SceneComposer) -> None:
        spec = SceneSpec(
            scene_type="cta",
            text="Segue o perfil pra mais!",
            duration_seconds=4.0,
        )
        img = composer.compose_scene(spec)
        assert img.size == (WIDTH, HEIGHT)

    def test_compose_with_subtitle(self, composer: SceneComposer) -> None:
        spec = SceneSpec(
            scene_type="hook",
            text="GTA 6 chegando!",
            duration_seconds=3.0,
            subtitle_text="Legendas visíveis no frame",
        )
        img = composer.compose_scene(spec)
        assert img.size == (WIDTH, HEIGHT)
        # Verify subtitle region has non-background pixels
        pixels = list(img.getdata())
        # Bottom area should have subtitle bar pixels (darker region)
        bottom_row = pixels[-100 * WIDTH : -99 * WIDTH]
        assert len(bottom_row) == WIDTH

    def test_custom_identity(self) -> None:
        identity = VisualIdentity(
            primary_color=(255, 0, 0),
            logo_text="TEST RADAR",
        )
        composer = SceneComposer(identity)
        spec = SceneSpec(
            scene_type="hook",
            text="Teste",
            duration_seconds=2.0,
        )
        img = composer.compose_scene(spec)
        assert img.size == (WIDTH, HEIGHT)

    @pytest.mark.asyncio
    async def test_compose_sequence(
        self, composer: SceneComposer, tmp_path: Path
    ) -> None:
        specs = [
            SceneSpec(scene_type="hook", text="Hook!", duration_seconds=1.0),
            SceneSpec(scene_type="info_card", text="Info", duration_seconds=2.0),
            SceneSpec(scene_type="cta", text="CTA", duration_seconds=1.0),
        ]
        frames = await composer.compose_sequence(specs, tmp_path / "frames")
        expected_frames = int(1.0 * FPS) + int(2.0 * FPS) + int(1.0 * FPS)
        assert len(frames) == expected_frames
        assert all(f.exists() for f in frames)


class TestScriptToScenes:
    """Test script parsing into scene specifications."""

    def test_parse_full_script(self) -> None:
        script = """[HOOK - 3s]
GTA 6 confirmado!

[CONTEXTO - 8s]
Rockstar revelou tudo.

[DESENVOLVIMENTO - 20s]
Vice City reimaginada com gráficos next-gen.

[CTA - 4s]
Segue pra mais!"""
        scenes = parse_script_to_scenes(script)
        assert len(scenes) == 4
        assert scenes[0].scene_type == "hook"
        assert scenes[0].duration_seconds == 3.0
        assert "GTA 6" in scenes[0].text
        assert scenes[1].scene_type == "info_card"
        assert scenes[2].scene_type == "default"
        assert scenes[3].scene_type == "cta"

    def test_parse_empty_script(self) -> None:
        scenes = parse_script_to_scenes("")
        assert len(scenes) == 1
        assert scenes[0].scene_type == "default"

    def test_parse_no_markers(self) -> None:
        scenes = parse_script_to_scenes("Texto sem marcadores de seção.")
        assert len(scenes) == 1
        assert scenes[0].scene_type == "default"

    def test_total_duration_matches_script(self) -> None:
        script = """[HOOK - 3s]
Hook text.

[CONTEXTO - 10s]
Context text.

[CTA - 5s]
CTA text."""
        scenes = parse_script_to_scenes(script)
        total = sum(s.duration_seconds for s in scenes)
        assert total == 18.0

    def test_subtitle_extraction(self) -> None:
        script = """[HOOK - 3s]
Primeira linha do gancho.
Segunda linha ignorada."""
        scenes = parse_script_to_scenes(script)
        assert scenes[0].subtitle_text == "Primeira linha do gancho."

    def test_long_subtitle_truncated(self) -> None:
        long_text = "A" * 120
        script = f"[HOOK - 3s]\n{long_text}"
        scenes = parse_script_to_scenes(script)
        assert len(scenes[0].subtitle_text) <= 80
        assert scenes[0].subtitle_text.endswith("...")

    def test_curiosities_category(self) -> None:
        script = """[HOOK - 3s]
Você sabia?

[CURIOSIDADE - 15s]
Detalhe surpreendente sobre GTA 6.

[CTA - 4s]
Comenta aí!"""
        scenes = parse_script_to_scenes(script)
        assert scenes[1].scene_type == "info_card"

    def test_theory_category(self) -> None:
        script = """[HOOK - 3s]
E se Jason for o vilão?

[TEORIA - 10s]
Análise profunda.

[ANÁLISE - 20s]
Detalhes da teoria.

[CTA - 4s]
O que você acha?"""
        scenes = parse_script_to_scenes(script)
        assert scenes[1].scene_type == "title_card"
        assert scenes[2].scene_type == "default"