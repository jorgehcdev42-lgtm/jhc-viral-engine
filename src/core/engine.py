"""JHC Viral Engine — Core multi-profile orchestration engine.

Coordinates research → script → media → narration → subtitles → render → publish
pipeline for any registered profile. Reuses JHC AI STUDIOS components via adapters.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from src.core.profile_config import ProfileConfig, get_profile

logger = logging.getLogger(__name__)


class PipelineStage(str, Enum):
    """Ordered stages of the Reels production pipeline."""
    RESEARCH = "research"
    FACT_CHECK = "fact_check"
    SCRIPT = "script"
    MEDIA_PREP = "media_prep"
    NARRATION = "narration"
    SUBTITLES = "subtitles"
    EDITING = "editing"
    RENDER = "render"
    REVIEW = "review"
    SCHEDULE = "schedule"
    PUBLISH = "publish"
    ANALYTICS = "analytics"


@dataclass(frozen=True)
class PipelineJob:
    """Immutable record of a single Reel production job."""
    job_id: str
    profile_id: str
    topic: str
    stage: PipelineStage = PipelineStage.RESEARCH
    script_path: Optional[str] = None
    media_paths: tuple[str, ...] = ()
    narration_path: Optional[str] = None
    subtitle_path: Optional[str] = None
    output_path: Optional[str] = None
    error: Optional[str] = None

    def advance(self, stage: PipelineStage, **kwargs) -> PipelineJob:
        """Return new job at next stage with updated fields."""
        return PipelineJob(
            job_id=self.job_id,
            profile_id=self.profile_id,
            topic=self.topic,
            stage=stage,
            script_path=kwargs.get("script_path", self.script_path),
            media_paths=kwargs.get("media_paths", self.media_paths),
            narration_path=kwargs.get("narration_path", self.narration_path),
            subtitle_path=kwargs.get("subtitle_path", self.subtitle_path),
            output_path=kwargs.get("output_path", self.output_path),
            error=kwargs.get("error", self.error),
        )


class ViralEngine:
    """Central engine that orchestrates content production across profiles."""

    def __init__(self, data_root: Path | str = "data") -> None:
        self.data_root = Path(data_root)
        self.data_root.mkdir(parents=True, exist_ok=True)
        logger.info("ViralEngine initialized with data_root=%s", self.data_root)

    async def produce_reel(self, profile_id: str, topic: str) -> PipelineJob:
        """Run full pipeline for one Reel. Returns final job state."""
        profile = get_profile(profile_id)
        job = PipelineJob(
            job_id=f"{profile_id}-{topic[:30].replace(' ', '-').lower()}",
            profile_id=profile_id,
            topic=topic,
        )
        logger.info("Starting pipeline for profile=%s topic=%s", profile_id, topic)

        # Stage 1: Research
        job = await self._run_stage(job, profile, PipelineStage.RESEARCH)
        if job.error:
            return job

        # Stage 2: Fact check
        job = await self._run_stage(job, profile, PipelineStage.FACT_CHECK)
        if job.error:
            return job

        # Stage 3: Script generation
        job = await self._run_stage(job, profile, PipelineStage.SCRIPT)
        if job.error:
            return job

        # Stage 4: Media preparation
        job = await self._run_stage(job, profile, PipelineStage.MEDIA_PREP)
        if job.error:
            return job

        # Stage 5: Narration (TTS)
        job = await self._run_stage(job, profile, PipelineStage.NARRATION)
        if job.error:
            return job

        # Stage 6: Subtitles
        job = await self._run_stage(job, profile, PipelineStage.SUBTITLES)
        if job.error:
            return job

        # Stage 7: Editing + transitions
        job = await self._run_stage(job, profile, PipelineStage.EDITING)
        if job.error:
            return job

        # Stage 8: Render to MP4
        job = await self._run_stage(job, profile, PipelineStage.RENDER)
        if job.error:
            return job

        # Stage 9: Quality review
        job = await self._run_stage(job, profile, PipelineStage.REVIEW)

        logger.info(
            "Pipeline complete for job=%s stage=%s error=%s",
            job.job_id, job.stage, job.error,
        )
        return job

    async def _run_stage(
        self, job: PipelineJob, profile: ProfileConfig, stage: PipelineStage
    ) -> PipelineJob:
        """Execute a single pipeline stage with error handling."""
        logger.debug("Running stage %s for job %s", stage.value, job.job_id)
        try:
            handler = getattr(self, f"_stage_{stage.value}", None)
            if handler is None:
                return job.advance(stage, error=f"No handler for stage {stage.value}")
            return await handler(job, profile)
        except Exception as exc:
            logger.exception("Stage %s failed for job %s", stage.value, job.job_id)
            return job.advance(stage, error=str(exc))

    # --- Stage handlers (to be implemented per-stage) ---

    async def _stage_research(self, job: PipelineJob, profile: ProfileConfig) -> PipelineJob:
        """Find and validate content topic using research sources."""
        from src.research.trend_hunter import TrendHunter
        hunter = TrendHunter(profile)
        result = await hunter.validate_topic(job.topic)
        if not result.is_valid:
            return job.advance(PipelineStage.RESEARCH, error=f"Topic validation failed: {result.reason}")
        return job.advance(PipelineStage.FACT_CHECK)

    async def _stage_fact_check(self, job: PipelineJob, profile: ProfileConfig) -> PipelineJob:
        """Verify factual claims in the topic."""
        # Placeholder — will integrate fact-checking agent
        return job.advance(PipelineStage.SCRIPT)

    async def _stage_script(self, job: PipelineJob, profile: ProfileConfig) -> PipelineJob:
        """Generate original Reel script in pt-BR."""
        from src.production.scriptwriter import ScriptWriter
        writer = ScriptWriter(profile)
        result = await writer.generate(job.topic)
        out = self.data_root / profile.profile_id / "scripts" / f"{job.job_id}.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(result.text, encoding="utf-8")
        # Save caption and hashtags as metadata alongside script
        meta_out = self.data_root / profile.profile_id / "scripts" / f"{job.job_id}.meta.json"
        import json
        meta_out.write_text(json.dumps({
            "caption": result.caption,
            "hashtags": list(result.hashtags),
            "hook": result.hook,
            "llm_used": result.llm_used,
            "model": result.model,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return job.advance(PipelineStage.MEDIA_PREP, script_path=str(out))

    async def _stage_media_prep(self, job: PipelineJob, profile: ProfileConfig) -> PipelineJob:
        """Select and prepare media assets for the Reel."""
        # Placeholder — will use asset manager + smart clipper
        return job.advance(PipelineStage.NARRATION)

    async def _stage_narration(self, job: PipelineJob, profile: ProfileConfig) -> PipelineJob:
        """Generate pt-BR narration via TTS."""
        from src.production.narrator import Narrator
        narrator = Narrator(profile)
        if not job.script_path:
            return job.advance(PipelineStage.NARRATION, error="No script available")
        audio_path = await narrator.synthesize(Path(job.script_path), job.job_id)
        return job.advance(PipelineStage.SUBTITLES, narration_path=str(audio_path))

    async def _stage_subtitles(self, job: PipelineJob, profile: ProfileConfig) -> PipelineJob:
        """Generate synchronized subtitles from narration audio."""
        from src.production.subtitle_generator import SubtitleGenerator
        gen = SubtitleGenerator(profile)
        if not job.narration_path:
            return job.advance(PipelineStage.SUBTITLES, error="No narration available")
        srt_path = await gen.generate(Path(job.narration_path), job.job_id)
        return job.advance(PipelineStage.EDITING, subtitle_path=str(srt_path))

    async def _stage_editing(self, job: PipelineJob, profile: ProfileConfig) -> PipelineJob:
        """Apply transitions, overlays, and visual identity."""
        # Placeholder — will use FFmpeg adapter from JHC AI STUDIOS
        return job.advance(PipelineStage.RENDER)

    async def _stage_render(self, job: PipelineJob, profile: ProfileConfig) -> PipelineJob:
        """Render final MP4 in 9:16 format optimized for Instagram."""
        from src.production.renderer import Renderer
        renderer = Renderer(profile)
        output = await renderer.render(job)
        return job.advance(PipelineStage.REVIEW, output_path=str(output))

    async def _stage_review(self, job: PipelineJob, profile: ProfileConfig) -> PipelineJob:
        """Quality check on rendered video."""
        # Placeholder — automated quality gate
        return job.advance(PipelineStage.SCHEDULE)

    async def _stage_schedule(self, job: PipelineJob, profile: ProfileConfig) -> PipelineJob:
        """Queue for publishing at optimal time."""
        return job.advance(PipelineStage.PUBLISH)

    async def _stage_publish(self, job: PipelineJob, profile: ProfileConfig) -> PipelineJob:
        """Publish via Instagram Content Publishing API."""
        if not profile.publishing.access_token:
            return job.advance(
                PipelineStage.PUBLISH,
                error="Instagram credentials not configured. Manual publish required.",
            )
        # Placeholder — will integrate Instagram publisher
        return job.advance(PipelineStage.ANALYTICS)

    async def _stage_analytics(self, job: PipelineJob, profile: ProfileConfig) -> PipelineJob:
        """Track performance metrics after publishing."""
        return job