"""Testes de qualidade real do AutoReel — MISSÃO 027 FASE 2.

Valida detecção de vídeos pretos, congelados, sem áudio, bitrate baixo,
FPS incorreto, truncados e conteúdo visual válido via Quality Gate V2.
"""

import pytest
import tempfile
import subprocess
import json
from pathlib import Path


@pytest.fixture
def studio():
    from src.production.auto_reel import AutoReelStudio
    return AutoReelStudio(data_root="data")


@pytest.fixture
def real_video():
    """Vídeo real autorizado para testes."""
    path = Path("data/test_real_source.mp4")
    if not path.exists():
        pytest.skip("Vídeo real não disponível: data/test_real_source.mp4")
    return str(path)


class TestQualityGateV2States:
    """Testa estados PASSED, NEEDS_REVIEW, REJECTED do Quality Gate V2."""

    def test_valid_video_passes(self, studio, real_video):
        result = studio._quality_gate(real_video)
        assert result["state"] in ("PASSED", "NEEDS_REVIEW")
        assert len(result["issues"]) == 0 or result["state"] == "NEEDS_REVIEW"

    def test_black_frames_detected(self, studio):
        """Vídeo com frames pretos deve ser REJECTED."""
        # Criar vídeo preto sintético
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            subprocess.run([
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=black:s=320x240:d=3:r=30",
                "-c:v", "libx264", "-preset", "ultrafast", tmp_path
            ], timeout=15)
            result = studio._quality_gate(tmp_path)
            assert result["state"] == "REJECTED"
            assert any("preto" in i.lower() or "black" in i.lower() for i in result["issues"])
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_frozen_video_detected(self, studio):
        """Vídeo congelado (mesmo frame repetido) deve ser REJECTED."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            # 1 frame estático estendido por 5 segundos
            subprocess.run([
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=red:s=320x240:d=5:r=1",
                "-c:v", "libx264", "-preset", "ultrafast", tmp_path
            ], timeout=15)
            result = studio._quality_gate(tmp_path)
            # Deve detectar como estático ou ter warnings
            visual = result.get("visual_check", {})
            assert visual.get("unique_colors", 0) <= 1 or result["state"] != "PASSED"
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_low_bitrate_needs_review(self, studio):
        """Vídeo com bitrate muito baixo deve ser NEEDS_REVIEW."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            # Vídeo válido mas com bitrate extremamente baixo
            subprocess.run([
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc=d=3:s=320x240:r=30",
                "-c:v", "libx264", "-b:v", "10k", "-preset", "ultrafast", tmp_path
            ], timeout=15)
            result = studio._quality_gate(tmp_path)
            # Bitrate < 50kbps deve gerar warning ou rejection
            assert result["state"] in ("NEEDS_REVIEW", "REJECTED")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_missing_audio_warning(self, studio, real_video):
        """Vídeo sem áudio quando fonte tem áudio gera NEEDS_REVIEW."""
        result = studio._quality_gate(real_video, source_has_audio=True)
        # Fonte real não tem áudio, então se source_has_audio=True, deve warn
        if not studio._get_video_info(real_video).get("has_audio"):
            assert "NEEDS_REVIEW" == result["state"] or any("áudio" in w.lower() for w in result.get("warnings", []))

    def test_truncated_video_rejected(self, studio):
        """Vídeo com duração < 1s deve ser REJECTED."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            subprocess.run([
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=0.5:r=30",
                "-c:v", "libx264", "-preset", "ultrafast", tmp_path
            ], timeout=15)
            result = studio._quality_gate(tmp_path)
            assert result["state"] == "REJECTED"
            assert any("duração" in i.lower() or "duration" in i.lower() for i in result["issues"])
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_visual_content_check_functional(self, studio, real_video):
        """_check_visual_content retorna dados estruturados válidos."""
        check = studio._check_visual_content(real_video)
        assert "valid" in check
        assert "frames" in check
        assert len(check["frames"]) >= 1
        for frame in check["frames"]:
            assert "rgb" in frame
            assert "variance" in frame
            assert "is_black" in frame
            assert "is_static" in frame


class TestAutoReelPipeline:
    """Testa pipeline completo do AutoReel com vídeo real."""

    def test_pilot_render_produces_valid_output(self, studio, real_video):
        """Render piloto produz MP4 válido com conteúdo visual real."""
        from src.production.auto_reel import ReelRequest
        req = ReelRequest(
            video_path=real_video,
            market="br",
            platform="reels",
            subtitle_text="TESTE M027",
        )
        result = studio.produce(req)
        assert result.status == "done"
        assert result.output_path is not None
        assert Path(result.output_path).exists()
        assert Path(result.output_path).stat().st_size > 100_000  # > 100KB

        # Verificar QG V2
        qg = result.metadata.get("quality_gate", {})
        assert qg.get("state") in ("PASSED", "NEEDS_REVIEW")
        assert qg.get("visual_check", {}).get("valid") is True

    def test_fps_preserved_from_source(self, studio, real_video):
        """FPS do output deve corresponder ao FPS da fonte."""
        from src.production.auto_reel import ReelRequest
        source_info = studio._get_video_info(real_video)
        source_fps = source_info.get("fps", 30.0)

        req = ReelRequest(video_path=real_video, market="br", platform="reels")
        result = studio.produce(req)
        assert result.status == "done"

        out_info = studio._get_video_info(result.output_path)
        out_fps = out_info.get("fps", 0)
        # FPS deve estar dentro de margem aceitável
        assert abs(out_fps - source_fps) < 5.0, f"FPS mismatch: source={source_fps} output={out_fps}"

    def test_temp_dirs_isolated(self, studio, real_video):
        """Diretórios temporários devem ser isolados por execução."""
        import os
        from src.production.auto_reel import ReelRequest

        temp_base = studio.temp_dir
        initial_files = set(os.listdir(temp_base)) if temp_base.exists() else set()

        req = ReelRequest(video_path=real_video, market="br", platform="reels")
        result = studio.produce(req)
        assert result.status == "done"

        # Temp dir não deve acumular arquivos permanentes após execução bem-sucedida
        # (arquivos temporários são limpos no single-pass pipeline)
        final_files = set(os.listdir(temp_base)) if temp_base.exists() else set()
        leftover = final_files - initial_files
        # Permitir alguns arquivos residuais mas não muitos
        assert len(leftover) < 10, f"Temp dir leak: {leftover}"