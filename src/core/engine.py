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
        """Render final MP4 with composed scenes or fallback to plain renderer."""
        # Try scene-based rendering first (visual quality upgrade)
        if job.script_path and Path(job.script_path).exists():
            try:
                output = await self._render_with_scenes(job, profile)
                if output:
                    return job.advance(PipelineStage.REVIEW, output_path=str(output))
            except Exception as exc:
                logger.warning("Scene rendering failed, falling back to plain: %s", exc)

        # Fallback to original renderer
        from src.production.renderer import Renderer
        renderer = Renderer(profile)
        output = await renderer.render(job)
        return job.advance(PipelineStage.REVIEW, output_path=str(output))

    @staticmethod
    def _sanitize_job_id(topic: str, profile_id: str) -> str:
        """Create filesystem-safe job ID from topic and profile."""
        import re
        slug = re.sub(r"[^a-z0-9]+", "-", topic[:40].lower()).strip("-")
        slug = re.sub(r"-+", "-", slug)
        return f"{profile_id}-{slug}" if slug else f"{profile_id}-reel-{int(__import__('time').time())}"

    async def _render_with_scenes(
        self, job: PipelineJob, profile: ProfileConfig
    ) -> Optional[Path]:
        """Render video using DynamicSceneEngine with template-driven visuals.

        Integrates SmartVideoSelector to use real media clips from the library
        when available, falling back to synthetic frames for scenes without media.
        """
        from src.production.dynamic_scene_engine import DynamicSceneEngine, DynamicSceneSpec
        from src.production.script_to_scenes import parse_script_to_scenes
        from src.production.visual_identity import VICE_CITY_IDENTITY
        from src.production.reel_templates import select_template_for_category

        script_path = Path(job.script_path)
        script_text = script_path.read_text(encoding="utf-8")
        base_scenes = parse_script_to_scenes(script_text)
        if not base_scenes:
            return None

        # Select template based on first scene's inferred category
        first_scene_type = base_scenes[0].scene_type if base_scenes else "hook"
        category_map = {"hook": "news", "title_card": "announcement", "info_card": "news"}
        category = category_map.get(first_scene_type, "news")
        template = select_template_for_category(category)

        # Try to select real media clips from library for this script
        selected_clips: dict[int, object] = {}  # scene_index -> ClipSelection
        try:
            from src.media.library import SmartMediaLibrary
            from src.media.video_selector import SmartVideoSelector
            db_path = self.data_root / "media_library.db"
            thumbs_dir = self.data_root / "thumbnails"
            if db_path.exists():
                lib = SmartMediaLibrary(db_path, thumbs_dir)
                stats = lib.get_stats()
                if stats["total_files"] > 0:
                    selector = SmartVideoSelector(lib)
                    scene_durations = [s.duration_seconds for s in template.scenes]
                    result = selector.select_for_script(
                        script_text,
                        scene_durations=scene_durations,
                        require_authorized=False,
                    )
                    for clip in result.clips:
                        selected_clips[clip.scene_index] = clip
                    logger.info(
                        "SmartVideoSelector: %d/%d scenes matched with real media",
                        len(selected_clips), len(template.scenes),
                    )
        except Exception as exc:
            logger.debug("SmartVideoSelector unavailable, using synthetic frames: %s", exc)

        # Build dynamic specs from template structure + script content + media overlay
        dyn_specs: list[DynamicSceneSpec] = []
        template_scenes = list(template.scenes)
        for i, tmpl_scene in enumerate(template_scenes):
            # Map script content to template scene slots
            if i < len(base_scenes):
                text = base_scenes[i].text
                subtitle = base_scenes[i].subtitle_text
            elif base_scenes:
                text = base_scenes[-1].text
                subtitle = base_scenes[-1].subtitle_text
            else:
                text = template.name.replace("_", " ").upper()
                subtitle = ""

            # Check if we have a real media clip for this scene
            media_overlay_path = None
            if i in selected_clips:
                clip = selected_clips[i]
                media_overlay_path = clip.asset.file_path
                logger.debug(
                    "Scene %d using real media: %s (score=%.2f)",
                    i, clip.asset.file_name, clip.relevance_score,
                )

            dyn_specs.append(DynamicSceneSpec(
                scene_type=tmpl_scene.scene_type,
                text=text,
                duration_seconds=tmpl_scene.duration_seconds,
                subtitle_text=subtitle,
                category=category,
                zoom_start=tmpl_scene.zoom_start,
                zoom_end=tmpl_scene.zoom_end,
                pan_x_start=tmpl_scene.pan_x_start,
                pan_x_end=tmpl_scene.pan_x_end,
                accent_color=tmpl_scene.accent_color,
                bg_style=tmpl_scene.bg_style,
                text_animation=tmpl_scene.text_animation,
                glow_intensity=tmpl_scene.glow_intensity,
                media_overlay_path=media_overlay_path,
            ))

        engine = DynamicSceneEngine(VICE_CITY_IDENTITY)
        safe_job_id = self._sanitize_job_id(job.topic, job.profile_id)
        frames_dir = self.data_root / profile.profile_id / "frames" / safe_job_id
        frame_paths = await engine.render_sequence(dyn_specs, frames_dir)

        out_dir = self.data_root / profile.profile_id / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{safe_job_id}.mp4"

        audio_path = Path(job.narration_path) if job.narration_path else None
        from src.production.scene_composer import SceneComposer
        await SceneComposer.frames_to_video(frame_paths, out_path, audio_path)

        # FASE 2: Apply watermark/branding overlay if configured for this profile
        try:
            from src.production.watermark import WatermarkEngine
            wm_engine = WatermarkEngine(self.data_root)
            wm_config = wm_engine.get_config(profile.profile_id)
            if wm_config.enabled and wm_config.logo_path and Path(wm_config.logo_path).exists():
                branded_path = out_path.with_stem(out_path.stem + "_branded")
                wm_result = await wm_engine.apply_watermark(out_path, branded_path, profile.profile_id)
                if wm_result["success"]:
                    # Replace output with branded version
                    branded_path.rename(out_path)
                    logger.info(
                        "Watermark applied to %s (%.1fs render)",
                        out_path.name, wm_result.get("render_time_seconds", 0),
                    )
                else:
                    logger.warning("Watermark failed for %s: %s", out_path.name, wm_result.get("error"))
        except Exception as wm_exc:
            logger.debug("WatermarkEngine unavailable, skipping branding: %s", wm_exc)

        media_count = len(selected_clips)
        logger.info(
            "Template-rendered video: %s (%d frames, template=%s, real_media=%d/%d scenes)",
            out_path, len(frame_paths), template.name,
            media_count, len(template.scenes),
        )
        return out_path

    async def _stage_review(self, job: PipelineJob, profile: ProfileConfig) -> PipelineJob:
        """Quality gate: validate video, audio, script, and thumbnail."""
        from src.production.quality_gate import QualityGate

        qg = QualityGate()
        video_path = Path(job.output_path) if job.output_path else None
        script_path = Path(job.script_path) if job.script_path else None
        audio_path = Path(job.narration_path) if job.narration_path else None

        # Generate thumbnail if not exists
        thumb_path = None
        if job.script_path and job.output_path:
            from src.production.thumbnail_generator import ThumbnailGenerator
            from src.production.script_to_scenes import parse_script_to_scenes
            try:
                script_text = Path(job.script_path).read_text(encoding="utf-8")
                scenes = parse_script_to_scenes(script_text)
                hook_text = scenes[0].text if scenes else "Vice City Radar"
                thumb_dir = self.data_root / profile.profile_id / "thumbnails"
                thumb_path = thumb_dir / f"{job.job_id}.png"
                if not thumb_path.exists():
                    gen = ThumbnailGenerator()
                    gen.generate(hook_text[:80], thumb_path, category="news")
            except Exception as exc:
                logger.warning("Thumbnail generation failed: %s", exc)

        if not video_path or not video_path.exists():
            return job.advance(PipelineStage.REVIEW, error="No video to review")

        report = await qg.evaluate(video_path, script_path, thumb_path, audio_path)
        report_dir = self.data_root / profile.profile_id / "quality"
        await qg.save_report(report, report_dir)

        if not report.approved:
            return job.advance(
                PipelineStage.REVIEW,
                error=f"Quality gate rejected: {report.summary}",
            )

        logger.info("Quality gate passed: %s", report.summary)
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