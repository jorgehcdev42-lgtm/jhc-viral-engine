"""Testes unitários para Quality Gate V2 — AutoReelStudio._quality_gate().

Cobre os três estados (PASSED, NEEDS_REVIEW, REJECTED) e a lógica de tolerância
a falso positivo de frames pretos em transições/fades legítimos.
"""
import pytest
from unittest.mock import patch
from src.production.auto_reel import AutoReelStudio


@pytest.fixture
def studio():
    """AutoReelStudio sem inicialização pesada."""
    with patch.object(AutoReelStudio, "__init__", lambda self: None):
        s = AutoReelStudio()
        return s


def _make_info(duration=10.0, width=1080, size_mb=5.0, bitrate=2000000,
               has_audio=True, error=None):
    """Helper para criar dict de info de vídeo mockado."""
    return {
        "duration": duration,
        "width": width,
        "size_mb": size_mb,
        "bitrate": bitrate,
        "has_audio": has_audio,
        "error": error,
    }


def _make_visual(valid=True, black_frames=0, static_frames=0,
                 unique_colors=3, frames=None):
    """Helper para criar dict de visual check mockado."""
    if frames is None:
        frames = [
            {"rgb": (100, 100, 100), "variance": 500.0,
             "is_black": False, "is_static": False},
            {"rgb": (120, 110, 100), "variance": 600.0,
             "is_black": False, "is_static": False},
            {"rgb": (80, 90, 100), "variance": 400.0,
             "is_black": False, "is_static": False},
        ]
    return {
        "valid": valid,
        "black_frames": black_frames,
        "static_frames": static_frames,
        "unique_colors": unique_colors,
        "frames": frames,
    }


class TestQualityGatePassed:
    """Vídeos válidos devem retornar state=PASSED."""

    def test_valid_video_passes(self, studio):
        """Vídeo com conteúdo visual rico → PASSED."""
        with (
            patch.object(studio, "_get_video_info", return_value=_make_info()),
            patch.object(studio, "_check_visual_content",
                         return_value=_make_visual()),
        ):
            result = studio._quality_gate("/fake/video.mp4")
            assert result["state"] == "PASSED"
            assert result["passed"] is True
            assert result["issues"] == []

    def test_dark_scene_not_black_passes(self, studio):
        """Cena escura legítima (RGB baixo mas variância alta) → PASSED."""
        dark_frames = [
            {"rgb": (18, 23, 26), "variance": 42.8,
             "is_black": False, "is_static": False},
            {"rgb": (22, 27, 29), "variance": 114.7,
             "is_black": False, "is_static": False},
            {"rgb": (35, 41, 43), "variance": 49.2,
             "is_black": False, "is_static": False},
        ]
        with (
            patch.object(studio, "_get_video_info", return_value=_make_info()),
            patch.object(studio, "_check_visual_content",
                         return_value=_make_visual(frames=dark_frames)),
        ):
            result = studio._quality_gate("/fake/dark_scene.mp4")
            assert result["state"] == "PASSED"
            assert result["passed"] is True


class TestQualityGateRejected:
    """Vídeos inválidos devem retornar state=REJECTED."""

    def test_all_black_frames_rejected(self, studio):
        """Todos os frames pretos → REJECTED."""
        all_black = [
            {"rgb": (2, 2, 2), "variance": 0.1,
             "is_black": True, "is_static": True},
            {"rgb": (3, 3, 3), "variance": 0.2,
             "is_black": True, "is_static": True},
            {"rgb": (1, 1, 1), "variance": 0.1,
             "is_black": True, "is_static": True},
        ]
        visual = _make_visual(valid=False, black_frames=3, frames=all_black)
        with (
            patch.object(studio, "_get_video_info", return_value=_make_info()),
            patch.object(studio, "_check_visual_content",
                         return_value=visual),
        ):
            result = studio._quality_gate("/fake/all_black.mp4")
            assert result["state"] == "REJECTED"
            assert result["passed"] is False
            assert any("Frames pretos" in i for i in result["issues"])

    def test_too_short_rejected(self, studio):
        """Duração < 1s → REJECTED."""
        with (
            patch.object(studio, "_get_video_info",
                         return_value=_make_info(duration=0.5)),
            patch.object(studio, "_check_visual_content",
                         return_value=_make_visual()),
        ):
            result = studio._quality_gate("/fake/short.mp4")
            assert result["state"] == "REJECTED"
            assert any("< 1s" in i for i in result["issues"])

    def test_too_narrow_rejected(self, studio):
        """Largura < 480px → REJECTED."""
        with (
            patch.object(studio, "_get_video_info",
                         return_value=_make_info(width=320)),
            patch.object(studio, "_check_visual_content",
                         return_value=_make_visual()),
        ):
            result = studio._quality_gate("/fake/narrow.mp4")
            assert result["state"] == "REJECTED"
            assert any("< 480px" in i for i in result["issues"])

    def test_empty_file_rejected(self, studio):
        """Arquivo < 10KB → REJECTED."""
        with (
            patch.object(studio, "_get_video_info",
                         return_value=_make_info(size_mb=0.005)),
            patch.object(studio, "_check_visual_content",
                         return_value=_make_visual()),
        ):
            result = studio._quality_gate("/fake/tiny.mp4")
            assert result["state"] == "REJECTED"
            assert any("< 10KB" in i for i in result["issues"])

    def test_ffprobe_error_rejected(self, studio):
        """Erro ffprobe → REJECTED."""
        with (
            patch.object(studio, "_get_video_info",
                         return_value=_make_info(error="ffprobe failed")),
            patch.object(studio, "_check_visual_content",
                         return_value=_make_visual()),
        ):
            result = studio._quality_gate("/fake/broken.mp4")
            assert result["state"] == "REJECTED"
            assert any("ffprobe" in i for i in result["issues"])

    def test_static_content_rejected(self, studio):
        """Conteúdo congelado (unique_colors <= 1) → REJECTED."""
        static_frames = [
            {"rgb": (100, 100, 100), "variance": 0.0,
             "is_black": False, "is_static": True},
            {"rgb": (100, 100, 100), "variance": 0.0,
             "is_black": False, "is_static": True},
            {"rgb": (100, 100, 100), "variance": 0.0,
             "is_black": False, "is_static": True},
        ]
        visual = _make_visual(valid=False, static_frames=3,
                              unique_colors=1, frames=static_frames)
        with (
            patch.object(studio, "_get_video_info", return_value=_make_info()),
            patch.object(studio, "_check_visual_content",
                         return_value=visual),
        ):
            result = studio._quality_gate("/fake/static.mp4")
            assert result["state"] == "REJECTED"
            assert any("estático" in i or "congelado" in i
                       for i in result["issues"])


class TestQualityGateTolerance:
    """Tolerância a falso positivo: 1/3 frames pretos com outros válidos."""

    def test_one_black_with_two_valid_others_passes(self, studio):
        """1/3 preto + 2 válidos (var>10) → warning, não REJECTED."""
        mixed_frames = [
            {"rgb": (5, 5, 5), "variance": 0.5,
             "is_black": True, "is_static": True},
            {"rgb": (100, 80, 60), "variance": 200.0,
             "is_black": False, "is_static": False},
            {"rgb": (120, 90, 70), "variance": 300.0,
             "is_black": False, "is_static": False},
        ]
        visual = _make_visual(valid=False, black_frames=1, frames=mixed_frames)
        with (
            patch.object(studio, "_get_video_info", return_value=_make_info()),
            patch.object(studio, "_check_visual_content",
                         return_value=visual),
        ):
            result = studio._quality_gate("/fake/fade_transition.mp4")
            # Tolerância: 1/3 preto com 2 válidos → PASSED ou NEEDS_REVIEW
            assert result["state"] != "REJECTED"
            assert any("Frame escuro" in w or "conteúdo válido" in w
                       for w in result["warnings"])

    def test_two_black_with_one_valid_rejected(self, studio):
        """2/3 pretos + 1 válido → REJECTED (não é falso positivo)."""
        mostly_black = [
            {"rgb": (3, 3, 3), "variance": 0.1,
             "is_black": True, "is_static": True},
            {"rgb": (2, 2, 2), "variance": 0.2,
             "is_black": True, "is_static": True},
            {"rgb": (100, 80, 60), "variance": 200.0,
             "is_black": False, "is_static": False},
        ]
        visual = _make_visual(valid=False, black_frames=2,
                              frames=mostly_black)
        with (
            patch.object(studio, "_get_video_info", return_value=_make_info()),
            patch.object(studio, "_check_visual_content",
                         return_value=visual),
        ):
            result = studio._quality_gate("/fake/mostly_black.mp4")
            assert result["state"] == "REJECTED"
            assert any("Frames pretos" in i for i in result["issues"])

    def test_low_variance_non_black_not_counted_as_valid(self, studio):
        """Frame não-preto com var<=10 não conta como non_black_valid."""
        low_var_frames = [
            {"rgb": (5, 5, 5), "variance": 0.5,
             "is_black": True, "is_static": True},
            {"rgb": (20, 20, 20), "variance": 3.0,
             "is_black": False, "is_static": True},
            {"rgb": (100, 80, 60), "variance": 200.0,
             "is_black": False, "is_static": False},
        ]
        visual = _make_visual(valid=False, black_frames=1, frames=low_var_frames)
        with (
            patch.object(studio, "_get_video_info", return_value=_make_info()),
            patch.object(studio, "_check_visual_content",
                         return_value=visual),
        ):
            result = studio._quality_gate("/fake/low_var.mp4")
            # Apenas 1 non_black_valid (var>10), precisa >=2 → REJECTED
            assert result["state"] == "REJECTED"


class TestQualityGateNeedsReview:
    """Warnings sem issues → NEEDS_REVIEW."""

    def test_low_bitrate_needs_review(self, studio):
        """Bitrate baixo gera warning → NEEDS_REVIEW."""
        with (
            patch.object(studio, "_get_video_info",
                         return_value=_make_info(bitrate=30000)),
            patch.object(studio, "_check_visual_content",
                         return_value=_make_visual()),
        ):
            result = studio._quality_gate("/fake/low_bitrate.mp4")
            assert result["state"] == "NEEDS_REVIEW"
            assert any("Bitrate baixo" in w for w in result["warnings"])

    def test_audio_lost_needs_review(self, studio):
        """Áudio perdido gera warning → NEEDS_REVIEW."""
        with (
            patch.object(studio, "_get_video_info",
                         return_value=_make_info(has_audio=False)),
            patch.object(studio, "_check_visual_content",
                         return_value=_make_visual()),
        ):
            result = studio._quality_gate("/fake/no_audio.mp4",
                                          source_has_audio=True)
            assert result["state"] == "NEEDS_REVIEW"
            assert any("Áudio perdido" in w for w in result["warnings"])

    def test_large_file_needs_review(self, studio):
        """Arquivo >100MB gera warning → NEEDS_REVIEW."""
        with (
            patch.object(studio, "_get_video_info",
                         return_value=_make_info(size_mb=150.0)),
            patch.object(studio, "_check_visual_content",
                         return_value=_make_visual()),
        ):
            result = studio._quality_gate("/fake/large.mp4")
            assert result["state"] == "NEEDS_REVIEW"
            assert any("Arquivo grande" in w for w in result["warnings"])

    def test_static_frames_warning_needs_review(self, studio):
        """Frames estáticos com conteúdo válido → NEEDS_REVIEW."""
        frames_with_static = [
            {"rgb": (100, 100, 100), "variance": 500.0,
             "is_black": False, "is_static": False},
            {"rgb": (120, 110, 100), "variance": 600.0,
             "is_black": False, "is_static": False},
            {"rgb": (100, 100, 100), "variance": 2.0,
             "is_black": False, "is_static": True},
        ]
        visual = _make_visual(valid=True, static_frames=1, frames=frames_with_static)
        with (
            patch.object(studio, "_get_video_info", return_value=_make_info()),
            patch.object(studio, "_check_visual_content",
                         return_value=visual),
        ):
            result = studio._quality_gate("/fake/has_static.mp4")
            assert result["state"] == "NEEDS_REVIEW"
            assert any("estáticos" in w for w in result["warnings"])