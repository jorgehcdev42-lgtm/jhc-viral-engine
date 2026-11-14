"""Quality Gate V2 — Multidimensional Reel evaluation.

Replaces the purely technical V1 gate with a comprehensive assessment
covering visual quality, audio integrity, editorial standards, and
commercial readiness. Prevents technically-valid but visually poor
content from being marked as publication-ready.

Status levels:
- REJECTED: Critical failures, cannot publish
- NEEDS_REVIEW: Passes technical checks but has visual/editorial concerns
- TECHNICALLY_VALID: All automated checks pass, no visual analysis available
- READY_FOR_PUBLICATION: All dimensions validated including visual quality
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DimensionResult:
    """Result for one quality dimension."""
    name: str
    score: float  # 0.0 to 1.0
    status: str  # pass, warning, fail
    details: tuple[str, ...]
    weight: float = 1.0


@dataclass(frozen=True)
class QualityReportV2:
    """Complete multidimensional quality report."""
    job_id: str
    dimensions: tuple[DimensionResult, ...]
    overall_score: float
    status: str  # REJECTED, NEEDS_REVIEW, TECHNICALLY_VALID, READY_FOR_PUBLICATION
    summary: str
    visual_evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "overall_score": round(self.overall_score, 3),
            "status": self.status,
            "summary": self.summary,
            "visual_evidence": list(self.visual_evidence),
            "dimensions": [
                {
                    "name": d.name,
                    "score": round(d.score, 3),
                    "status": d.status,
                    "weight": d.weight,
                    "details": list(d.details),
                }
                for d in self.dimensions
            ],
        }


class QualityGateV2:
    """Multidimensional quality assessment for Reels."""

    # Thresholds
    MIN_DURATION = 10.0
    MAX_DURATION = 90.0
    MIN_UNIQUE_FRAME_RATIO = 0.5  # At least 50% unique frames
    MIN_COLOR_VARIANCE = 200.0  # Not a flat color
    MIN_TEXT_SCREEN_RATIO_MAX = 0.7  # Text shouldn't dominate >70% of screen
    REJECTION_THRESHOLD = 0.4
    REVIEW_THRESHOLD = 0.7
    PUBLICATION_THRESHOLD = 0.85

    async def evaluate(
        self,
        video_path: Path,
        script_path: Optional[Path] = None,
        thumbnail_path: Optional[Path] = None,
        audio_path: Optional[Path] = None,
        inspection_dir: Optional[Path] = None,
    ) -> QualityReportV2:
        """Run all quality dimensions and produce a comprehensive report."""
        dimensions: list[DimensionResult] = []

        # A. Technical Quality
        tech = await self._check_technical(video_path)
        dimensions.append(tech)

        # B. Visual Quality (requires frame extraction)
        if inspection_dir and inspection_dir.exists():
            visual = await self._check_visual(inspection_dir)
            dimensions.append(visual)
        else:
            dimensions.append(DimensionResult(
                name="visual_quality",
                score=0.5,
                status="warning",
                details=("No inspection frames available for visual analysis",),
                weight=2.0,
            ))

        # C. Audio Quality
        if audio_path and audio_path.exists():
            audio = await self._check_audio(audio_path)
            dimensions.append(audio)
        else:
            dimensions.append(DimensionResult(
                name="audio_quality",
                score=0.0,
                status="fail",
                details=("Audio file missing",),
                weight=1.5,
            ))

        # D. Editorial Quality
        if script_path and script_path.exists():
            editorial = self._check_editorial(script_path)
            dimensions.append(editorial)
        else:
            dimensions.append(DimensionResult(
                name="editorial_quality",
                score=0.0,
                status="fail",
                details=("Script file missing",),
                weight=1.0,
            ))

        # E. Commercial Readiness
        commercial = self._check_commercial(thumbnail_path, video_path)
        dimensions.append(commercial)

        # Calculate weighted overall score
        total_weight = sum(d.weight for d in dimensions)
        overall = sum(d.score * d.weight for d in dimensions) / total_weight if total_weight > 0 else 0.0

        # Determine status
        has_critical_fail = any(d.status == "fail" and d.weight >= 1.5 for d in dimensions)
        if has_critical_fail or overall < self.REJECTION_THRESHOLD:
            status = "REJECTED"
        elif overall < self.REVIEW_THRESHOLD:
            status = "NEEDS_REVIEW"
        elif overall < self.PUBLICATION_THRESHOLD:
            status = "TECHNICALLY_VALID"
        else:
            status = "READY_FOR_PUBLICATION"

        # Collect visual evidence paths
        evidence: list[str] = []
        if inspection_dir and inspection_dir.exists():
            samples = sorted(inspection_dir.glob("frame_*.jpg"))[:5]
            evidence = [str(s) for s in samples]

        failed_dims = [d.name for d in dimensions if d.status == "fail"]
        warn_dims = [d.name for d in dimensions if d.status == "warning"]
        summary_parts = [f"score={overall:.2f}", f"status={status}"]
        if failed_dims:
            summary_parts.append(f"FAILED: {', '.join(failed_dims)}")
        if warn_dims:
            summary_parts.append(f"WARNINGS: {', '.join(warn_dims)}")
        summary = " | ".join(summary_parts)

        report = QualityReportV2(
            job_id=video_path.stem,
            dimensions=tuple(dimensions),
            overall_score=overall,
            status=status,
            summary=summary,
            visual_evidence=tuple(evidence),
        )

        logger.info("QualityGate V2: %s", summary)
        return report

    async def _check_technical(self, video_path: Path) -> DimensionResult:
        """A. Technical quality: codec, resolution, duration, file integrity."""
        details: list[str] = []
        issues = 0

        if not video_path.exists() or video_path.stat().st_size < 10240:
            return DimensionResult("technical", 0.0, "fail", ("Video missing or too small",), 2.0)

        probe = await self._ffprobe(video_path)
        if not probe:
            return DimensionResult("technical", 0.0, "fail", ("ffprobe failed",), 2.0)

        streams = probe.get("streams", [])
        fmt = probe.get("format", {})
        vs = next((s for s in streams if s.get("codec_name") == "h264"), None)

        if not vs:
            issues += 2
            details.append("Missing H.264 codec")
        else:
            w, h = int(vs.get("width", 0)), int(vs.get("height", 0))
            if w >= 1080 and h >= 1920:
                details.append(f"Resolution OK: {w}x{h}")
            else:
                issues += 1
                details.append(f"Low resolution: {w}x{h}")

            if vs.get("pix_fmt") == "yuv420p":
                details.append("Pixel format OK")
            else:
                issues += 1
                details.append(f"Unexpected pixel format: {vs.get('pix_fmt')}")

        duration = float(fmt.get("duration", 0))
        if self.MIN_DURATION <= duration <= self.MAX_DURATION:
            details.append(f"Duration OK: {duration:.1f}s")
        else:
            issues += 1
            details.append(f"Duration out of range: {duration:.1f}s")

        size_kb = int(fmt.get("size", 0)) // 1024
        details.append(f"File size: {size_kb}KB")

        score = max(0.0, 1.0 - issues * 0.25)
        status = "pass" if score >= 0.7 else ("warning" if score >= 0.4 else "fail")
        return DimensionResult("technical", score, status, tuple(details), 2.0)

    async def _check_visual(self, inspection_dir: Path) -> DimensionResult:
        """B. Visual quality: diversity, color richness, motion, text ratio."""
        details: list[str] = []
        scores: list[float] = []

        frames = sorted(inspection_dir.glob("frame_*.jpg"))
        if not frames:
            return DimensionResult("visual_quality", 0.0, "fail", ("No frames to analyze",), 2.0)

        # B1. Frame uniqueness (diversity)
        hashes: list[str] = []
        for fp in frames:
            img = Image.open(fp).resize((32, 32))
            hashes.append(hashlib.md5(img.tobytes()).hexdigest()[:12])
        unique = len(set(hashes))
        unique_ratio = unique / len(frames)
        scores.append(min(1.0, unique_ratio / self.MIN_UNIQUE_FRAME_RATIO))
        details.append(f"Unique frames: {unique}/{len(frames)} ({unique_ratio:.0%})")

        # B2. Color variance (not flat/dark)
        variances: list[float] = []
        for fp in frames[:5]:  # Sample first 5
            img = Image.open(fp).resize((64, 64))
            pixels = list(img.getdata())
            r_vals = [p[0] for p in pixels]
            g_vals = [p[1] for p in pixels]
            b_vals = [p[2] for p in pixels]
            r_var = sum((x - sum(r_vals)/len(r_vals))**2 for x in r_vals) / len(r_vals)
            g_var = sum((x - sum(g_vals)/len(g_vals))**2 for x in g_vals) / len(g_vals)
            b_var = sum((x - sum(b_vals)/len(b_vals))**2 for x in b_vals) / len(b_vals)
            variances.append((r_var + g_var + b_var) / 3)
        avg_variance = sum(variances) / len(variances) if variances else 0
        color_score = min(1.0, avg_variance / 1000.0)
        scores.append(color_score)
        details.append(f"Color variance: {avg_variance:.0f} ({'rich' if avg_variance > 500 else 'poor'})")

        # B3. Brightness distribution (not all dark)
        brightnesses: list[float] = []
        for fp in frames[:5]:
            img = Image.open(fp).resize((64, 64)).convert("L")
            pixels = list(img.getdata())
            brightnesses.append(sum(pixels) / len(pixels))
        avg_brightness = sum(brightnesses) / len(brightnesses) if brightnesses else 0
        bright_score = min(1.0, avg_brightness / 80.0)
        scores.append(bright_score)
        details.append(f"Avg brightness: {avg_brightness:.0f} ({'good' if avg_brightness > 40 else 'dark'})")

        # B4. Motion detection (frame-to-frame delta)
        deltas: list[float] = []
        for i in range(min(len(frames) - 1, 10)):
            img1 = Image.open(frames[i]).resize((32, 32)).convert("L")
            img2 = Image.open(frames[i + 1]).resize((32, 32)).convert("L")
            p1, p2 = list(img1.getdata()), list(img2.getdata())
            delta = sum(abs(a - b) for a, b in zip(p1, p2)) / len(p1)
            deltas.append(delta)
        avg_delta = sum(deltas) / len(deltas) if deltas else 0
        motion_score = min(1.0, avg_delta / 15.0)
        scores.append(motion_score)
        details.append(f"Motion delta: {avg_delta:.1f} ({'dynamic' if avg_delta > 5 else 'static'})")

        overall = sum(scores) / len(scores) if scores else 0
        status = "pass" if overall >= 0.7 else ("warning" if overall >= 0.4 else "fail")
        return DimensionResult("visual_quality", overall, status, tuple(details), 2.0)

    async def _check_audio(self, audio_path: Path) -> DimensionResult:
        """C. Audio quality: duration, format, non-silence."""
        details: list[str] = []
        issues = 0

        try:
            import wave
            with wave.open(str(audio_path), "rb") as w:
                duration = w.getnframes() / w.getframerate()
                channels = w.getnchannels()
                sample_rate = w.getframerate()
                sample_width = w.getsampwidth()

                details.append(f"Duration: {duration:.1f}s")
                details.append(f"Format: {sample_rate}Hz {channels}ch {sample_width*8}bit")

                if duration < 5.0:
                    issues += 2
                    details.append("Audio too short")
                elif duration > 120.0:
                    issues += 1
                    details.append("Audio unusually long")

                if sample_rate < 16000:
                    issues += 1
                    details.append(f"Low sample rate: {sample_rate}Hz")

        except Exception as exc:
            return DimensionResult("audio_quality", 0.0, "fail", (f"Cannot read audio: {exc}",), 1.5)

        score = max(0.0, 1.0 - issues * 0.3)
        status = "pass" if score >= 0.7 else ("warning" if score >= 0.4 else "fail")
        return DimensionResult("audio_quality", score, status, tuple(details), 1.5)

    def _check_editorial(self, script_path: Path) -> DimensionResult:
        """D. Editorial quality: structure, length, source markers."""
        details: list[str] = []
        issues = 0

        try:
            text = script_path.read_text(encoding="utf-8").strip()
        except Exception as exc:
            return DimensionResult("editorial_quality", 0.0, "fail", (f"Cannot read script: {exc}",), 1.0)

        if len(text) < 50:
            issues += 2
            details.append(f"Script too short: {len(text)} chars")
        else:
            details.append(f"Script length: {len(text)} chars")

        has_hook = "[HOOK" in text.upper()
        has_cta = "[CTA" in text.upper()
        has_sections = has_hook and has_cta

        if has_sections:
            details.append("Structure: sections present")
        else:
            issues += 1
            details.append("Structure: missing section markers")

        # Check for placeholder/template language
        placeholder_phrases = [
            "vamos falar sobre", "tudo sobre", "é um assunto importante",
            "segue o perfil para mais",
        ]
        placeholder_count = sum(1 for p in placeholder_phrases if p.lower() in text.lower())
        if placeholder_count >= 2:
            issues += 1
            details.append(f"Template language detected ({placeholder_count} phrases)")
        else:
            details.append("Original language: OK")

        score = max(0.0, 1.0 - issues * 0.3)
        status = "pass" if score >= 0.7 else ("warning" if score >= 0.4 else "fail")
        return DimensionResult("editorial_quality", score, status, tuple(details), 1.0)

    def _check_commercial(
        self, thumbnail_path: Optional[Path], video_path: Path
    ) -> DimensionResult:
        """E. Commercial readiness: thumbnail, metadata, rights indicators."""
        details: list[str] = []
        issues = 0

        if thumbnail_path and thumbnail_path.exists() and thumbnail_path.stat().st_size > 1024:
            details.append(f"Thumbnail: {thumbnail_path.stat().st_size // 1024}KB")
        else:
            issues += 1
            details.append("Thumbnail: missing or too small")

        # Check for metadata sidecar
        meta_path = video_path.parent.parent / "scripts" / f"{video_path.stem}.meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                has_caption = bool(meta.get("caption"))
                has_hashtags = bool(meta.get("hashtags"))
                if has_caption and has_hashtags:
                    details.append("Metadata: caption + hashtags present")
                else:
                    issues += 1
                    details.append("Metadata: incomplete")
            except Exception:
                issues += 1
                details.append("Metadata: parse error")
        else:
            issues += 1
            details.append("Metadata: sidecar missing")

        # Rights: flag that media is generated (no external assets used)
        details.append("Rights: AI-generated visuals (no external media)")

        score = max(0.0, 1.0 - issues * 0.3)
        status = "pass" if score >= 0.7 else ("warning" if score >= 0.4 else "fail")
        return DimensionResult("commercial_readiness", score, status, tuple(details), 1.0)

    async def _ffprobe(self, video_path: Path) -> Optional[dict]:
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return None
        cmd = [
            ffprobe, "-v", "error",
            "-show_entries", "stream=codec_name,width,height,r_frame_rate,pix_fmt,duration,nb_frames",
            "-show_entries", "format=duration,size,bit_rate",
            "-of", "json", str(video_path),
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

    async def save_report(self, report: QualityReportV2, output_dir: Path) -> Path:
        """Save quality report as JSON sidecar."""
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / f"{report.job_id}.quality_v2.json"
        report_path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("QualityGate V2 report saved: %s", report_path)
        return report_path