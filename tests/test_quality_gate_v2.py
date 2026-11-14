"""Tests for QualityGate V2 multidimensional assessment."""

from __future__ import annotations

import json
import pytest
from pathlib import Path

from src.production.quality_gate_v2 import QualityGateV2, QualityReportV2


@pytest.fixture
def qg() -> QualityGateV2:
    return QualityGateV2()


class TestQualityGateV2Editorial:
    """Test editorial quality detection."""

    def test_template_language_detected(self, qg: QualityGateV2, tmp_path: Path) -> None:
        script = tmp_path / "script.txt"
        script.write_text(
            "[HOOK - 3s]\nTudo sobre GTA 6\n\n"
            "[CONTEXTO - 8s]\nVamos falar sobre GTA 6.\n\n"
            "[DESENVOLVIMENTO - 20s]\nÉ um assunto importante.\n\n"
            "[CTA - 4s]\nSegue o perfil para mais conteúdos como esse!",
            encoding="utf-8",
        )
        result = qg._check_editorial(script)
        assert result.score < 1.0
        assert any("Template language" in d for d in result.details)

    def test_original_script_passes(self, qg: QualityGateV2, tmp_path: Path) -> None:
        script = tmp_path / "script.txt"
        script.write_text(
            "[HOOK - 3s]\nRockstar confirmou nova data!\n\n"
            "[CONTEXTO - 8s]\nApós meses de especulação, a empresa revelou...\n\n"
            "[DESENVOLVIMENTO - 20s]\nO mapa inclui três regiões inéditas...\n\n"
            "[CTA - 4s]\nComenta qual região você quer explorar!",
            encoding="utf-8",
        )
        result = qg._check_editorial(script)
        assert result.score >= 0.7
        assert result.status == "pass"

    def test_short_script_fails(self, qg: QualityGateV2, tmp_path: Path) -> None:
        script = tmp_path / "script.txt"
        script.write_text("Texto curto.", encoding="utf-8")
        result = qg._check_editorial(script)
        assert result.status == "fail" or result.score < 0.5


class TestQualityGateV2Visual:
    """Test visual quality checks with synthetic frames."""

    @pytest.mark.asyncio
    async def test_dark_frames_score_low(self, qg: QualityGateV2, tmp_path: Path) -> None:
        from PIL import Image
        frames_dir = tmp_path / "dark_frames"
        frames_dir.mkdir()
        # Create uniformly dark frames
        for i in range(5):
            img = Image.new("RGB", (1080, 1920), (5, 5, 10))
            img.save(frames_dir / f"frame_{i:03d}.jpg")
        result = await qg._check_visual(frames_dir)
        assert result.score < 0.5
        assert any("dark" in d.lower() for d in result.details)

    @pytest.mark.asyncio
    async def test_static_frames_low_motion(self, qg: QualityGateV2, tmp_path: Path) -> None:
        from PIL import Image
        frames_dir = tmp_path / "static_frames"
        frames_dir.mkdir()
        # Create identical frames (zero motion)
        img = Image.new("RGB", (1080, 1920), (30, 20, 50))
        for i in range(10):
            img.save(frames_dir / f"frame_{i:03d}.jpg")
        result = await qg._check_visual(frames_dir)
        assert any("static" in d.lower() for d in result.details)

    @pytest.mark.asyncio
    async def test_diverse_frames_score_high(self, qg: QualityGateV2, tmp_path: Path) -> None:
        from PIL import Image, ImageDraw
        frames_dir = tmp_path / "diverse_frames"
        frames_dir.mkdir()
        for i in range(10):
            img = Image.new("RGB", (1080, 1920), (10 + i * 20, 20 + i * 15, 40 + i * 10))
            draw = ImageDraw.Draw(img)
            draw.rectangle([(100, 100 + i * 50), (500, 400 + i * 50)], fill=(255, 45, 120))
            draw.text((200, 800), f"Scene {i}", fill=(255, 255, 255))
            img.save(frames_dir / f"frame_{i:03d}.jpg")
        result = await qg._check_visual(frames_dir)
        assert result.score > 0.5
        assert any("100%" in d for d in result.details)


class TestQualityGateV2Persistence:
    """Test report saving and loading."""

    @pytest.mark.asyncio
    async def test_save_report_creates_json(self, qg: QualityGateV2, tmp_path: Path) -> None:
        report = QualityReportV2(
            job_id="test-job",
            dimensions=(),
            overall_score=0.85,
            status="READY_FOR_PUBLICATION",
            summary="test summary",
        )
        path = await qg.save_report(report, tmp_path)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["job_id"] == "test-job"
        assert data["status"] == "READY_FOR_PUBLICATION"
        assert abs(data["overall_score"] - 0.85) < 0.001

    @pytest.mark.asyncio
    async def test_rejected_status_on_critical_fail(self, qg: QualityGateV2, tmp_path: Path) -> None:
        # Create a tiny corrupt video file
        video = tmp_path / "bad.mp4"
        video.write_bytes(b"\x00" * 100)
        report = await qg.evaluate(video_path=video)
        assert report.status == "REJECTED"
        assert report.overall_score < 0.4


class TestQualityGateV2Commercial:
    """Test commercial readiness checks."""

    def test_missing_thumbnail_warns(self, qg: QualityGateV2, tmp_path: Path) -> None:
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00" * 100)
        result = qg._check_commercial(thumbnail_path=None, video_path=video)
        assert any("missing" in d.lower() for d in result.details)

    def test_complete_metadata_passes(self, qg: QualityGateV2, tmp_path: Path) -> None:
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00" * 100)
        thumb = tmp_path / "thumb.png"
        thumb.write_bytes(b"\x89PNG" + b"\x00" * 2000)
        meta_dir = tmp_path / "scripts"
        meta_dir.mkdir()
        meta = meta_dir / "test.meta.json"
        meta.write_text(json.dumps({"caption": "Test caption", "hashtags": ["#test"]}))
        result = qg._check_commercial(thumbnail_path=thumb, video_path=video)
        assert result.score >= 0.7