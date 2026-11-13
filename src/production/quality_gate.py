"""Quality gate for JHC Viral Engine Reels.

Validates rendered videos against objective criteria before
allowing scheduling or publication. Prevents low-quality content
from reaching the audience.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QualityCheck:
    """Single quality check result."""
    name: str
    passed: bool
    message: str
    severity: str = "error"  # error, warning, info


@dataclass(frozen=True)
class QualityReport:
    """Complete quality gate report."""
    job_id: str
    checks: tuple[QualityCheck, ...]
    approved: bool
    score: float  # 0.0 to 1.0
    summary: str

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "approved": self.approved,
            "score": round(self.score, 3),
            "summary": self.summary,
            "checks": [
                {"name": c.name, "passed": c.passed, "message": c.message, "severity": c.severity}
                for c in self.checks
            ],
        }


class QualityGate:
    """Validate Reel quality against objective criteria."""

    MIN_DURATION_SECONDS = 10.0
    MAX_DURATION_SECONDS = 90.0
    MIN_WIDTH = 1080
    MIN_HEIGHT = 1920
    REQUIRED_FPS = 25  # Allow 25 or 30
    MIN_AUDIO_BITRATE = 64000  # 64kbps minimum
    REQUIRED_CODEC = "h264"
    REQUIRED_PIX_FMT = "yuv420p"

    async def evaluate(
        self,
        video_path: Path,
        script_path: Optional[Path] = None,
        thumbnail_path: Optional[Path] = None,
        audio_path: Optional[Path] = None,
    ) -> QualityReport:
        """Run all quality checks and produce a report."""
        checks: list[QualityCheck] = []

        # Video file exists
        checks.append(self._check_file_exists(video_path, "Video MP4"))

        # Video specs via ffprobe
        probe_data = await self._ffprobe(video_path)
        if probe_data:
            checks.extend(self._check_video_specs(probe_data))
        else:
            checks.append(QualityCheck(
                "video_specs", False, "ffprobe failed — cannot validate video", "error"
            ))

        # Audio integrity
        if audio_path:
            checks.append(self._check_file_exists(audio_path, "Audio WAV"))
            checks.append(await self._check_audio_duration(audio_path, probe_data))

        # Script exists and has content
        if script_path:
            checks.append(self._check_script_quality(script_path))

        # Thumbnail exists
        if thumbnail_path:
            checks.append(self._check_file_exists(thumbnail_path, "Thumbnail"))

        # Calculate score and approval
        passed = sum(1 for c in checks if c.passed)
        total = len(checks)
        errors = sum(1 for c in checks if not c.passed and c.severity == "error")
        score = passed / total if total > 0 else 0.0
        approved = errors == 0 and score >= 0.7

        summary = f"{passed}/{total} checks passed, score={score:.2f}"
        if approved:
            summary += " — APPROVED"
        else:
            failed = [c.name for c in checks if not c.passed]
            summary += f" — REJECTED ({', '.join(failed)})"

        report = QualityReport(
            job_id=video_path.stem,
            checks=tuple(checks),
            approved=approved,
            score=score,
            summary=summary,
        )

        logger.info("Quality gate: %s", summary)
        return report

    def _check_file_exists(self, path: Path, label: str) -> QualityCheck:
        if path.exists() and path.stat().st_size > 0:
            size_kb = path.stat().st_size // 1024
            return QualityCheck(f"{label.lower()}_exists", True, f"{label}: {size_kb}KB", "info")
        return QualityCheck(f"{label.lower()}_exists", False, f"{label} missing or empty", "error")

    async def _ffprobe(self, video_path: Path) -> Optional[dict]:
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return None
        cmd = [
            ffprobe, "-v", "error",
            "-show_entries", "stream=codec_name,width,height,r_frame_rate,pix_fmt,duration,nb_frames",
            "-show_entries", "format=duration,size,bit_rate",
            "-of", "json",
            str(video_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return None
        try:
            return json.loads(stdout.decode())
        except json.JSONDecodeError:
            return None

    def _check_video_specs(self, probe: dict) -> list[QualityCheck]:
        checks: list[QualityCheck] = []
        streams = probe.get("streams", [])
        fmt = probe.get("format", {})

        video_stream = next((s for s in streams if s.get("codec_name") == self.REQUIRED_CODEC), None)
        if not video_stream:
            checks.append(QualityCheck("codec", False, f"Expected {self.REQUIRED_CODEC}", "error"))
            return checks

        # Resolution
        w = int(video_stream.get("width", 0))
        h = int(video_stream.get("height", 0))
        if w >= self.MIN_WIDTH and h >= self.MIN_HEIGHT:
            checks.append(QualityCheck("resolution", True, f"{w}x{h}", "info"))
        else:
            checks.append(QualityCheck("resolution", False, f"{w}x{h} < {self.MIN_WIDTH}x{self.MIN_HEIGHT}", "error"))

        # Pixel format
        pix = video_stream.get("pix_fmt", "")
        if pix == self.REQUIRED_PIX_FMT:
            checks.append(QualityCheck("pixel_format", True, pix, "info"))
        else:
            checks.append(QualityCheck("pixel_format", False, f"Expected {self.REQUIRED_PIX_FMT}, got {pix}", "warning"))

        # Duration
        duration = float(fmt.get("duration", video_stream.get("duration", 0)))
        if self.MIN_DURATION_SECONDS <= duration <= self.MAX_DURATION_SECONDS:
            checks.append(QualityCheck("duration", True, f"{duration:.1f}s", "info"))
        else:
            checks.append(QualityCheck("duration", False, f"{duration:.1f}s outside [{self.MIN_DURATION_SECONDS}-{self.MAX_DURATION_SECONDS}s]", "error"))

        # Frame count (visual change verification)
        nb_frames = video_stream.get("nb_frames")
        if nb_frames and int(nb_frames) > 100:
            checks.append(QualityCheck("frame_count", True, f"{nb_frames} frames", "info"))
        elif nb_frames:
            checks.append(QualityCheck("frame_count", False, f"Only {nb_frames} frames — possible static image", "warning"))
        else:
            checks.append(QualityCheck("frame_count", True, "Frame count unavailable", "info"))

        # File size sanity check (>10KB means real content)
        size = int(fmt.get("size", 0))
        if size > 10240:
            checks.append(QualityCheck("file_size", True, f"{size // 1024}KB", "info"))
        else:
            checks.append(QualityCheck("file_size", False, f"{size // 1024}KB too small", "error"))

        return checks

    async def _check_audio_duration(
        self, audio_path: Path, probe_data: Optional[dict]
    ) -> QualityCheck:
        """Verify audio has meaningful duration."""
        try:
            import wave
            with wave.open(str(audio_path), "rb") as w:
                audio_dur = w.getnframes() / w.getframerate()
            if audio_dur > 5.0:
                return QualityCheck("audio_duration", True, f"{audio_dur:.1f}s", "info")
            return QualityCheck("audio_duration", False, f"{audio_dur:.1f}s too short", "error")
        except Exception as exc:
            return QualityCheck("audio_duration", False, f"Cannot read audio: {exc}", "warning")

    def _check_script_quality(self, script_path: Path) -> QualityCheck:
        """Verify script has meaningful content."""
        try:
            text = script_path.read_text(encoding="utf-8").strip()
            if len(text) < 50:
                return QualityCheck("script_quality", False, f"Script too short ({len(text)} chars)", "warning")
            # Check for section markers
            has_sections = "[HOOK" in text.upper() or "[CONTEXTO" in text.upper()
            if has_sections:
                return QualityCheck("script_quality", True, f"{len(text)} chars with sections", "info")
            return QualityCheck("script_quality", True, f"{len(text)} chars (no sections)", "info")
        except Exception as exc:
            return QualityCheck("script_quality", False, f"Cannot read script: {exc}", "error")

    async def save_report(self, report: QualityReport, output_dir: Path) -> Path:
        """Save quality report as JSON sidecar."""
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / f"{report.job_id}.quality.json"
        report_path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Quality report saved: %s", report_path)
        return report_path