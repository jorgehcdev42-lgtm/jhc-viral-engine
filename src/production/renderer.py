"""Video renderer for JHC Viral Engine.

Renders final MP4 in 9:16 vertical format optimized for Instagram Reels.
Reuses FFmpeg patterns from JHC AI STUDIOS (libx264, AAC, movflags +faststart).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

from src.core.profile_config import ProfileConfig
from src.core.engine import PipelineJob

logger = logging.getLogger(__name__)


class Renderer:
    """Render Reels to Instagram-compatible MP4 using FFmpeg."""

    WIDTH = 1080
    HEIGHT = 1920
    FPS = 30
    VIDEO_CODEC = "libx264"
    AUDIO_CODEC = "aac"
    AUDIO_BITRATE = "128k"
    CRF = 23
    PRESET = "medium"

    def __init__(self, profile: ProfileConfig) -> None:
        self.profile = profile

    async def render(self, job: PipelineJob) -> Path:
        """Render final MP4 from narration audio + optional subtitles.

        Returns path to rendered video file.
        Currently renders audio-only with black background when no
        video clips are available. Real implementation will composite
        media clips with transitions.
        """
        out_dir = Path("data") / self.profile.profile_id / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{job.job_id}.mp4"

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError(
                "FFmpeg not found. Install via: brew install ffmpeg"
            )

        if job.narration_path and Path(job.narration_path).exists():
            await self._render_with_audio(job, out_path, ffmpeg)
        else:
            await self._render_placeholder(out_path, ffmpeg)

        logger.info("Rendered: %s", out_path)
        return out_path

    async def _render_with_audio(
        self, job: PipelineJob, out_path: Path, ffmpeg: str
    ) -> None:
        """Render video with narration audio and optional subtitle burn-in."""
        # First try with subtitles filter; fall back to plain render if libass unavailable
        has_subtitles = job.subtitle_path and Path(job.subtitle_path).exists()

        if has_subtitles:
            success = await self._try_render_with_subtitles(job, out_path, ffmpeg)
            if success:
                return
            logger.warning("Subtitle burn-in failed (libass likely missing); rendering without subtitles")

        # Render without subtitles
        cmd = [
            ffmpeg, "-y",
            "-f", "lavfi",
            "-i", f"color=c=#0a0a1a:s={self.WIDTH}x{self.HEIGHT}:r={self.FPS}",
            "-i", job.narration_path,
            "-c:v", self.VIDEO_CODEC,
            "-preset", self.PRESET,
            "-crf", str(self.CRF),
            "-pix_fmt", "yuv420p",
            "-c:a", self.AUDIO_CODEC,
            "-b:a", self.AUDIO_BITRATE,
            "-ar", "48000",
            "-shortest",
            "-movflags", "+faststart",
            str(out_path),
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg render failed: {stderr.decode()[-500:]}")

    async def _try_render_with_subtitles(
        self, job: PipelineJob, out_path: Path, ffmpeg: str
    ) -> bool:
        """Attempt render with subtitle burn-in. Returns True on success."""
        escaped_srt = str(Path(job.subtitle_path).resolve()).replace("\\", "\\\\\\\\").replace(":", "\\\\:")
        cmd = [
            ffmpeg, "-y",
            "-f", "lavfi",
            "-i", f"color=c=#0a0a1a:s={self.WIDTH}x{self.HEIGHT}:r={self.FPS}",
            "-i", job.narration_path,
            "-vf", (
                f"subtitles='{escaped_srt}':force_style="
                "'FontSize=24,PrimaryColour=&H00FFFFFF&,"
                "OutlineColour=&H00000000&,Outline=2,Shadow=1,"
                "Alignment=2,MarginV=80'"
            ),
            "-c:v", self.VIDEO_CODEC,
            "-preset", self.PRESET,
            "-crf", str(self.CRF),
            "-pix_fmt", "yuv420p",
            "-c:a", self.AUDIO_CODEC,
            "-b:a", self.AUDIO_BITRATE,
            "-ar", "48000",
            "-shortest",
            "-movflags", "+faststart",
            str(out_path),
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            err_msg = stderr.decode()[-500:]
            if "subtitles" in err_msg.lower() or "libass" in err_msg.lower() or "filter" in err_msg.lower():
                return False
            raise RuntimeError(f"FFmpeg render failed: {err_msg}")
        return True

    async def _render_placeholder(self, out_path: Path, ffmpeg: str) -> None:
        """Render 5-second placeholder when no audio available."""
        cmd = [
            ffmpeg, "-y",
            "-f", "lavfi",
            "-i", f"color=c=#1a1a2e:s={self.WIDTH}x{self.HEIGHT}:r={self.FPS}:d=5",
            "-f", "lavfi",
            "-i", "anullsrc=r=48000:cl=stereo",
            "-c:v", self.VIDEO_CODEC,
            "-preset", "ultrafast",
            "-crf", "28",
            "-pix_fmt", "yuv420p",
            "-c:a", self.AUDIO_CODEC,
            "-b:a", self.AUDIO_BITRATE,
            "-t", "5",
            "-movflags", "+faststart",
            str(out_path),
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg placeholder failed: {stderr.decode()[-500:]}")