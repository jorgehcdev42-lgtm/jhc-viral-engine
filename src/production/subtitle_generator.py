"""Subtitle generation for JHC Viral Engine.

Generates SRT subtitle files synchronized with narration audio.
Uses word-level timing estimation from TTS output duration.
Future: integrate Whisper for real ASR-based alignment.
"""

from __future__ import annotations

import logging
import struct
import wave
from pathlib import Path

from src.core.profile_config import ProfileConfig

logger = logging.getLogger(__name__)


class SubtitleGenerator:
    """Generate synchronized subtitles from narration audio + script."""

    def __init__(self, profile: ProfileConfig) -> None:
        self.profile = profile

    async def generate(self, audio_path: Path, job_id: str) -> Path:
        """Generate SRT file from audio duration and script text.

        Currently uses proportional timing (chars/sec estimation).
        Real implementation should use Whisper/faster-whisper for
        word-level timestamps.
        """
        duration_sec = self._get_audio_duration(audio_path)
        if duration_sec <= 0:
            raise ValueError(f"Audio duration is {duration_sec}s")

        # Find corresponding script
        script_dir = Path("data") / self.profile.profile_id / "scripts"
        script_files = list(script_dir.glob(f"{job_id}*"))
        if not script_files:
            raise FileNotFoundError(f"No script found for job {job_id}")

        text = script_files[0].read_text(encoding="utf-8")
        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
            and not line.strip().startswith("[")
            and not line.strip().startswith("---")
            and not line.strip().startswith("(")
        ]

        out_dir = Path("data") / self.profile.profile_id / "subtitles"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{job_id}.srt"

        srt_content = self._build_srt(lines, duration_sec)
        out_path.write_text(srt_content, encoding="utf-8")

        logger.info(
            "Subtitles generated: %s (%d entries, %.1fs audio)",
            out_path, len(lines), duration_sec,
        )
        return out_path

    @staticmethod
    def _get_audio_duration(path: Path) -> float:
        """Read WAV duration from header."""
        try:
            with wave.open(str(path), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                return frames / float(rate) if rate > 0 else 0.0
        except Exception:
            # Fallback: estimate from file size (24kHz 16-bit mono)
            size = path.stat().st_size
            return max(0.0, (size - 44) / (24000 * 2))

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        """Format seconds to SRT timestamp HH:MM:SS,mmm."""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def _build_srt(self, lines: list[str], total_duration: float) -> str:
        """Build SRT content with proportional timing."""
        if not lines:
            return ""

        total_chars = sum(len(line) for line in lines)
        chars_per_sec = total_chars / total_duration if total_duration > 0 else 15.0

        entries: list[str] = []
        current_time = 0.0

        for idx, line in enumerate(lines, start=1):
            char_duration = len(line) / chars_per_sec
            # Minimum 1s per subtitle, maximum 6s
            display_duration = max(1.0, min(6.0, char_duration))
            end_time = current_time + display_duration

            start_ts = self._format_timestamp(current_time)
            end_ts = self._format_timestamp(end_time)

            entries.append(f"{idx}\n{start_ts} --> {end_ts}\n{line}\n")
            current_time = end_time

        return "\n".join(entries)