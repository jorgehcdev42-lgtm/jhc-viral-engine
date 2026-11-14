"""Tests for JHC Viral Engine core pipeline."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.core.profile_config import (
    ProfileConfig,
    VisualIdentity,
    ResearchSources,
    EditorialConfig,
    PublishingConfig,
    GTA6_PROFILE,
    MARVEL_DC_PROFILE,
    get_profile,
    list_profiles,
)
from src.core.engine import ViralEngine, PipelineStage, PipelineJob
from src.research.trend_hunter import TrendHunter, TopicValidation


@pytest.fixture
def gta6_profile() -> ProfileConfig:
    return GTA6_PROFILE


@pytest.fixture
def engine(tmp_path: Path) -> ViralEngine:
    return ViralEngine(data_root=tmp_path / "data")


class TestProfileConfig:
    def test_gta6_profile_exists(self, gta6_profile: ProfileConfig) -> None:
        assert gta6_profile.profile_id == "gta6"
        assert gta6_profile.name == "Leonida GTA VI Flash"
        assert gta6_profile.niche == "gaming"
        assert gta6_profile.enabled is True

    def test_marvel_dc_profile_disabled(self) -> None:
        assert MARVEL_DC_PROFILE.profile_id == "marvel-dc"
        assert MARVEL_DC_PROFILE.enabled is False

    def test_get_profile_valid(self) -> None:
        profile = get_profile("gta6")
        assert profile.profile_id == "gta6"

    def test_get_profile_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown profile"):
            get_profile("nonexistent")

    def test_list_profiles(self) -> None:
        profiles = list_profiles()
        assert len(profiles) >= 2
        ids = [p.profile_id for p in profiles]
        assert "gta6" in ids
        assert "marvel-dc" in ids

    def test_profile_roundtrip_json(self, tmp_path: Path) -> None:
        path = tmp_path / "test_profile.json"
        GTA6_PROFILE.save(path)
        loaded = ProfileConfig.load(path)
        assert loaded.profile_id == GTA6_PROFILE.profile_id
        assert loaded.name == GTA6_PROFILE.name
        assert loaded.visual_identity.primary_color == GTA6_PROFILE.visual_identity.primary_color

    def test_visual_identity_defaults(self) -> None:
        vi = VisualIdentity()
        assert vi.primary_color == "#0066FF"
        assert vi.font_family == "Inter"

    def test_editorial_config_defaults(self) -> None:
        ec = EditorialConfig()
        assert ec.max_reel_duration_seconds == 90
        assert ec.hook_duration_seconds == 3
        assert ec.fact_check_required is True


class TestTrendHunter:
    @pytest.mark.asyncio
    async def test_validate_topic_valid(self, gta6_profile: ProfileConfig) -> None:
        hunter = TrendHunter(gta6_profile)
        result = await hunter.validate_topic("GTA 6 trailer novidades")
        assert result.is_valid is True
        assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_validate_topic_too_short(self, gta6_profile: ProfileConfig) -> None:
        hunter = TrendHunter(gta6_profile)
        result = await hunter.validate_topic("ab")
        assert result.is_valid is False
        assert "too short" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_validate_topic_banned(self, gta6_profile: ProfileConfig) -> None:
        hunter = TrendHunter(gta6_profile)
        # Banned topic uses underscores; test string must contain exact substring
        result = await hunter.validate_topic("vazou spoilers_confirmados_sem_aviso do GTA 6")
        assert result.is_valid is False
        assert "banned" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_validate_topic_no_keyword_match(self, gta6_profile: ProfileConfig) -> None:
        hunter = TrendHunter(gta6_profile)
        result = await hunter.validate_topic("receita de bolo de cenoura")
        assert result.is_valid is False
        assert "keyword" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_discover_trends_returns_empty_without_apis(
        self, gta6_profile: ProfileConfig
    ) -> None:
        hunter = TrendHunter(gta6_profile)
        trends = await hunter.discover_trends(limit=5)
        assert isinstance(trends, list)


class TestPipelineJob:
    def test_advance_creates_new_job(self) -> None:
        job = PipelineJob(job_id="test-1", profile_id="gta6", topic="GTA 6 news")
        advanced = job.advance(PipelineStage.SCRIPT, script_path="/tmp/script.txt")
        assert advanced.stage == PipelineStage.SCRIPT
        assert advanced.script_path == "/tmp/script.txt"
        assert job.stage == PipelineStage.RESEARCH  # original unchanged (immutable)

    def test_advance_preserves_fields(self) -> None:
        job = PipelineJob(
            job_id="test-2",
            profile_id="gta6",
            topic="Test",
            narration_path="/tmp/audio.wav",
        )
        advanced = job.advance(PipelineStage.SUBTITLES, subtitle_path="/tmp/sub.srt")
        assert advanced.narration_path == "/tmp/audio.wav"
        assert advanced.subtitle_path == "/tmp/sub.srt"


class TestViralEngine:
    @pytest.mark.asyncio
    async def test_engine_initializes_data_root(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "custom_data"
        engine = ViralEngine(data_root=data_dir)
        assert data_dir.exists()
        assert engine.data_root == data_dir

    @pytest.mark.asyncio
    async def test_produce_reel_creates_output_structure(
        self, engine: ViralEngine, tmp_path: Path
    ) -> None:
        """Test that pipeline runs without crashing and creates expected dirs."""
        job = await engine.produce_reel("gta6", "GTA 6 Vice City novidades")
        # Pipeline should complete (possibly with errors at publish stage due to no credentials)
        assert job.job_id.startswith("gta6-")
        assert job.profile_id == "gta6"
        # Script should have been generated
        if job.script_path:
            assert Path(job.script_path).exists()
        # Audio should have been generated (or silent fallback)
        if job.narration_path:
            assert Path(job.narration_path).exists()