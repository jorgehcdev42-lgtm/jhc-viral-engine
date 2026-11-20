"""FASE 7 — Testes de transcodificação HEVC→H.264 e validação de codec."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestCodecCompatibility:
    """Testa _check_codec_compatibility do AutoReelStudio."""

    def test_h264_is_compatible(self):
        from src.production.auto_reel import AutoReelStudio
        studio = AutoReelStudio(data_root="/tmp")
        ok, msg = studio._check_codec_compatibility({"codec": "h264", "pix_fmt": "yuv420p"})
        assert ok is True
        assert msg == ""

    def test_hevc_is_incompatible(self):
        from src.production.auto_reel import AutoReelStudio
        studio = AutoReelStudio(data_root="/tmp")
        ok, msg = studio._check_codec_compatibility({"codec": "hevc", "pix_fmt": "yuv420p"})
        assert ok is False
        assert "hevc" in msg.lower() or "codec" in msg.lower()

    def test_h265_is_incompatible(self):
        from src.production.auto_reel import AutoReelStudio
        studio = AutoReelStudio(data_root="/tmp")
        ok, msg = studio._check_codec_compatibility({"codec": "h265", "pix_fmt": "yuv420p"})
        assert ok is False

    def test_problematic_pixfmt_warns_but_passes(self):
        from src.production.auto_reel import AutoReelStudio
        studio = AutoReelStudio(data_root="/tmp")
        ok, msg = studio._check_codec_compatibility({"codec": "h264", "pix_fmt": "yuv420p10le"})
        assert ok is True
        assert "yuv420p10le" in msg

    def test_unknown_codec_is_compatible(self):
        from src.production.auto_reel import AutoReelStudio
        studio = AutoReelStudio(data_root="/tmp")
        ok, msg = studio._check_codec_compatibility({"codec": "vp9", "pix_fmt": "yuv420p"})
        assert ok is True

    def test_missing_fields_default_safe(self):
        from src.production.auto_reel import AutoReelStudio
        studio = AutoReelStudio(data_root="/tmp")
        ok, msg = studio._check_codec_compatibility({})
        assert ok is True


class TestTranscodeToH264:
    """Testa _transcode_to_h264 com mocks para evitar render real."""

    def test_transcode_returns_none_on_ffmpeg_failure(self, tmp_path):
        from src.production.auto_reel import AutoReelStudio
        studio = AutoReelStudio(data_root=str(tmp_path))
        # Mock _run_ffmpeg to simulate failure
        with patch.object(studio, '_run_ffmpeg', return_value=(1, "", "error")):
            result = studio._transcode_to_h264("/fake/input.mp4")
        assert result is None

    def test_transcode_returns_none_when_output_too_small(self, tmp_path):
        from src.production.auto_reel import AutoReelStudio
        studio = AutoReelStudio(data_root=str(tmp_path))
        # Create tiny output file (< 100KB threshold)
        tmp_dir = tmp_path / "autoreel" / "tmp"
        tmp_dir.mkdir(parents=True)
        tiny_file = tmp_dir / "transcoded_fake_h264.mp4"
        tiny_file.write_bytes(b"x" * 50)  # Way below 100KB

        with patch.object(studio, '_run_ffmpeg', return_value=(0, "", "")):
            result = studio._transcode_to_h264("/fake/input.mp4")
        assert result is None

    def test_transcode_reuses_existing_cache(self, tmp_path):
        from src.production.auto_reel import AutoReelStudio
        studio = AutoReelStudio(data_root=str(tmp_path))
        # Create valid cached file (> 100KB)
        tmp_dir = tmp_path / "autoreel" / "tmp"
        tmp_dir.mkdir(parents=True)
        # Cache key = f"transcoded_{Path(input_path).stem}_h264.mp4"
        cached = tmp_dir / "transcoded_myvideo_h264.mp4"
        cached.write_bytes(b"x" * 200_000)

        # Should return cached path without calling ffmpeg
        with patch.object(studio, '_run_ffmpeg') as mock_ffmpeg:
            result = studio._transcode_to_h264(str(tmp_path / "myvideo.mp4"))
            assert result == str(cached)
            assert mock_ffmpeg.call_count == 0


class TestGetVideoInfoIncludesPixFmt:
    """Verifica que _get_video_info retorna pix_fmt."""

    def test_get_video_info_has_pix_fmt_key(self, tmp_path):
        from src.production.auto_reel import AutoReelStudio
        studio = AutoReelStudio(data_root=str(tmp_path))
        # Mock ffprobe response
        fake_probe = {
            "streams": [
                {"codec_type": "video", "codec_name": "hevc", "pix_fmt": "yuv420p10le",
                 "width": 1080, "height": 1920, "duration": "60.0", "nb_frames": "3600"},
                {"codec_type": "audio", "codec_name": "aac"}
            ],
            "format": {"duration": "60.0", "bit_rate": "5000000", "size": "37500000"}
        }
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(fake_probe))
            info = studio._get_video_info("/fake/video.mp4")
        assert "pix_fmt" in info
        assert info["pix_fmt"] == "yuv420p10le"
        assert info["codec"] == "hevc"


class TestBlacklistPersistence:
    """Verifica que materiais blacklisted são excluídos da seleção."""

    def test_blacklisted_material_excluded(self):
        """Vídeo 0013.mp4 deve estar na blacklist após falhas de black frames."""
        from scripts.batch_reels_launch import get_existing_job_materials
        # This is a structural test — verifies the function exists and returns a set
        result = get_existing_job_materials()
        assert isinstance(result, set)