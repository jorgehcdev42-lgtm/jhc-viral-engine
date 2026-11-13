"""TTS narration adapter for JHC Viral Engine.

Wraps macOS `say` command (reused from JHC AI STUDIOS pattern)
to generate pt-BR narration audio from script files.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from src.core.profile_config import ProfileConfig

logger = logging.getLogger(__name__)


class Narrator:
    """Generate pt-BR narration audio using macOS TTS."""

    DEFAULT_VOICE = "Luciana"
    DEFAULT_RATE = 200
    SAMPLE_RATE = 24000

    def __init__(self, profile: ProfileConfig) -> None:
        self.profile = profile

    async def synthesize(self, script_path: Path, job_id: str) -> Path:
        """Convert script text to speech audio file.

        Returns path to generated WAV file.
        Falls back to silent audio if `say` is unavailable.
        """
        text = script_path.read_text(encoding="utf-8")
        # Strip section markers [HOOK], [CONTEXTO], etc.
        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith("[") and not line.strip().startswith("---")
        ]
        clean_text = " ".join(lines)

        if not clean_text:
            raise ValueError("Script is empty after cleaning")

        out_dir = Path("data") / self.profile.profile_id / "audio"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{job_id}.wav"

        logger.info(
            "Synthesizing narration: voice=%s rate=%d chars=%d",
            self.DEFAULT_VOICE, self.DEFAULT_RATE, len(clean_text),
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                "say", "-v", self.DEFAULT_VOICE,
                "-r", str(self.DEFAULT_RATE),
                "-o", str(out_path),
                "--file-format=WAVE",
                "--data-format=LEI16@24000",
                clean_text,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"say failed: {stderr.decode()}")
        except FileNotFoundError:
            logger.warning("macOS `say` not found — generating silent placeholder")
            await self._generate_silent(out_path, len(clean_text))

        logger.info("Narration saved: %s", out_path)
        return out_path

    async def _generate_silent(self, path: Path, char_count: int) -> None:
        """Generate silent WAV proportional to text length (~15 chars/sec)."""
        duration_sec = max(3, char_count // 15)
        num_samples = self.SAMPLE_RATE * duration_sec
        # Minimal WAV header + silence
        import struct
        data_size = num_samples * 2  # 16-bit mono
        with open(path, "wb") as f:
            f.write(b"RIFF")
            f.write(struct.pack("<I", 36 + data_size))
            f.write(b"WAVEfmt ")
            f.write(struct.pack("<IHHIIHH", 16, 1, 1, self.SAMPLE_RATE, self.SAMPLE_RATE * 2, 2, 16))
            f.write(b"data")
            f.write(struct.pack("<I", data_size))
            f.write(b"\x00" * min(data_size, 1024 * 1024))  # Cap at 1MB for safety