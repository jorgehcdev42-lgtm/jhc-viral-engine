"""JHC Autonomous Media Director — Production scheduler and job manager.

Orchestrates daily content production with persistent queues,
checkpoint/resume, idempotency, and resource-aware scheduling.
Designed for MacBook M2 8GB: sequential processing, no parallel renders.

Job states: PENDING → SCRIPTING → NARRATING → RENDERING → REVIEWING → APPROVED | REJECTED
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class JobState(str, Enum):
    """Explicit job lifecycle states."""
    PENDING = "pending"
    SCRIPTING = "scripting"
    NARRATING = "narrating"
    RENDERING = "rendering"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(frozen=True)
class ProductionJob:
    """Immutable record of a single content production job."""
    job_id: str
    profile_id: str
    topic: str
    source_url: str
    source_name: str
    category: str
    state: JobState = JobState.PENDING
    script_path: Optional[str] = None
    audio_path: Optional[str] = None
    video_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    quality_score: Optional[float] = None
    quality_status: Optional[str] = None
    error: Optional[str] = None
    created_at: float = 0.0
    updated_at: float = 0.0
    retry_count: int = 0

    def transition(self, new_state: JobState, **kwargs) -> ProductionJob:
        """Return new job with updated state and fields."""
        return ProductionJob(
            job_id=self.job_id,
            profile_id=self.profile_id,
            topic=self.topic,
            source_url=self.source_url,
            source_name=self.source_name,
            category=self.category,
            state=new_state,
            script_path=kwargs.get("script_path", self.script_path),
            audio_path=kwargs.get("audio_path", self.audio_path),
            video_path=kwargs.get("video_path", self.video_path),
            thumbnail_path=kwargs.get("thumbnail_path", self.thumbnail_path),
            quality_score=kwargs.get("quality_score", self.quality_score),
            quality_status=kwargs.get("quality_status", self.quality_status),
            error=kwargs.get("error", self.error),
            created_at=self.created_at,
            updated_at=time.time(),
            retry_count=kwargs.get("retry_count", self.retry_count),
        )

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "profile_id": self.profile_id,
            "topic": self.topic,
            "source_url": self.source_url,
            "source_name": self.source_name,
            "category": self.category,
            "state": self.state.value,
            "script_path": self.script_path,
            "audio_path": self.audio_path,
            "video_path": self.video_path,
            "thumbnail_path": self.thumbnail_path,
            "quality_score": self.quality_score,
            "quality_status": self.quality_status,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "retry_count": self.retry_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProductionJob:
        return cls(
            job_id=data["job_id"],
            profile_id=data["profile_id"],
            topic=data["topic"],
            source_url=data.get("source_url", ""),
            source_name=data.get("source_name", ""),
            category=data.get("category", "news"),
            state=JobState(data.get("state", "pending")),
            script_path=data.get("script_path"),
            audio_path=data.get("audio_path"),
            video_path=data.get("video_path"),
            thumbnail_path=data.get("thumbnail_path"),
            quality_score=data.get("quality_score"),
            quality_status=data.get("quality_status"),
            error=data.get("error"),
            created_at=data.get("created_at", 0.0),
            updated_at=data.get("updated_at", 0.0),
            retry_count=data.get("retry_count", 0),
        )


@dataclass(frozen=True)
class ProductionBatch:
    """A batch of jobs for a production run."""
    batch_id: str
    profile_id: str
    jobs: tuple[ProductionJob, ...]
    created_at: float
    max_concurrent: int = 1  # Sequential on M2 8GB

    def pending_jobs(self) -> list[ProductionJob]:
        return [j for j in self.jobs if j.state == JobState.PENDING]

    def completed_jobs(self) -> list[ProductionJob]:
        return [j for j in self.jobs if j.state in (JobState.APPROVED, JobState.REJECTED)]

    def failed_jobs(self) -> list[ProductionJob]:
        return [j for j in self.jobs if j.state == JobState.FAILED]

    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "profile_id": self.profile_id,
            "created_at": self.created_at,
            "max_concurrent": self.max_concurrent,
            "jobs": [j.to_dict() for j in self.jobs],
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProductionBatch:
        return cls(
            batch_id=data["batch_id"],
            profile_id=data["profile_id"],
            jobs=tuple(ProductionJob.from_dict(j) for j in data.get("jobs", [])),
            created_at=data.get("created_at", 0.0),
            max_concurrent=data.get("max_concurrent", 1),
        )


class MediaDirector:
    """Autonomous production scheduler with checkpoint/resume."""

    BATCH_FILE = "production_batch.json"
    LOG_FILE = "production_log.jsonl"
    MAX_RETRIES = 2

    def __init__(self, data_root: Path, profile_id: str) -> None:
        self.data_root = data_root
        self.profile_id = profile_id
        self.batch_dir = data_root / profile_id / "batches"
        self.batch_dir.mkdir(parents=True, exist_ok=True)
        self._current_batch: Optional[ProductionBatch] = None

    def create_batch(self, topics: list[dict]) -> ProductionBatch:
        """Create a new production batch from selected topics.

        Args:
            topics: List of dicts with keys: title, source_url, source_name, category, content_hash
        """
        now = time.time()
        batch_id = f"{self.profile_id}-{int(now)}"

        jobs = tuple(
            ProductionJob(
                job_id=f"{batch_id}-{i:03d}",
                profile_id=self.profile_id,
                topic=t["title"],
                source_url=t.get("source_url", ""),
                source_name=t.get("source_name", ""),
                category=t.get("category", "news"),
                created_at=now,
                updated_at=now,
            )
            for i, t in enumerate(topics)
        )

        batch = ProductionBatch(
            batch_id=batch_id,
            profile_id=self.profile_id,
            jobs=jobs,
            created_at=now,
        )

        self._save_batch(batch)
        self._log_event("batch_created", {"batch_id": batch_id, "job_count": len(jobs)})
        logger.info("Created batch %s with %d jobs", batch_id, len(jobs))
        return batch

    def load_batch(self) -> Optional[ProductionBatch]:
        """Load the most recent batch for checkpoint/resume."""
        batch_path = self.batch_dir / self.BATCH_FILE
        if not batch_path.exists():
            return None
        try:
            data = json.loads(batch_path.read_text(encoding="utf-8"))
            batch = ProductionBatch.from_dict(data)
            self._current_batch = batch
            logger.info("Loaded batch %s (%d jobs)", batch.batch_id, len(batch.jobs))
            return batch
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Could not load batch: %s", exc)
            return None

    async def process_next_job(self, engine) -> Optional[ProductionJob]:
        """Process the next pending job in the current batch.

        Returns the updated job, or None if no pending jobs remain.
        """
        batch = self._current_batch or self.load_batch()
        if not batch:
            logger.warning("No batch loaded")
            return None

        pending = batch.pending_jobs()
        if not pending:
            logger.info("No pending jobs in batch %s", batch.batch_id)
            return None

        job = pending[0]
        logger.info("Processing job %s: %s", job.job_id, job.topic[:50])

        try:
            # Run pipeline via engine
            result = await engine.produce_reel(job.profile_id, job.topic)

            if result.error:
                new_state = JobState.FAILED if job.retry_count >= self.MAX_RETRIES else JobState.PENDING
                updated_job = job.transition(
                    new_state,
                    error=result.error,
                    retry_count=job.retry_count + 1,
                )
                self._log_event("job_failed", {
                    "job_id": job.job_id,
                    "error": result.error,
                    "retry": updated_job.retry_count,
                })
            else:
                # Run quality gate
                from src.production.quality_gate_v2 import QualityGateV2
                qg = QualityGateV2()
                video_path = Path(result.output_path) if result.output_path else None
                script_path = Path(result.script_path) if result.script_path else None
                audio_path = Path(result.narration_path) if result.narration_path else None

                inspection_dir = self.data_root / job.profile_id / "inspection" / job.job_id
                if video_path and video_path.exists():
                    inspection_dir.mkdir(parents=True, exist_ok=True)
                    ffmpeg = __import__("shutil").which("ffmpeg")
                    if ffmpeg:
                        proc = await asyncio.create_subprocess_exec(
                            ffmpeg, "-y", "-i", str(video_path),
                            "-vf", "fps=1", "-q:v", "2",
                            str(inspection_dir / "frame_%03d.jpg"),
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        await proc.communicate()

                report = await qg.evaluate(video_path, script_path, None, audio_path, inspection_dir)
                await qg.save_report(report, self.data_root / job.profile_id / "quality")

                if report.status == "REJECTED":
                    updated_job = job.transition(
                        JobState.REJECTED,
                        video_path=result.output_path,
                        script_path=result.script_path,
                        audio_path=result.narration_path,
                        quality_score=report.overall_score,
                        quality_status=report.status,
                    )
                else:
                    updated_job = job.transition(
                        JobState.APPROVED,
                        video_path=result.output_path,
                        script_path=result.script_path,
                        audio_path=result.narration_path,
                        quality_score=report.overall_score,
                        quality_status=report.status,
                    )

                self._log_event("job_completed", {
                    "job_id": job.job_id,
                    "status": updated_job.state.value,
                    "quality_score": updated_job.quality_score,
                })

        except Exception as exc:
            logger.exception("Job %s failed with exception", job.job_id)
            updated_job = job.transition(
                JobState.FAILED,
                error=str(exc),
                retry_count=job.retry_count + 1,
            )
            self._log_event("job_exception", {"job_id": job.job_id, "error": str(exc)})

        # Update batch with new job state
        new_jobs = tuple(
            updated_job if j.job_id == job.job_id else j
            for j in batch.jobs
        )
        updated_batch = ProductionBatch(
            batch_id=batch.batch_id,
            profile_id=batch.profile_id,
            jobs=new_jobs,
            created_at=batch.created_at,
        )
        self._save_batch(updated_batch)
        self._current_batch = updated_batch

        return updated_job

    async def run_batch(self, engine) -> ProductionBatch:
        """Process all pending jobs in the current batch sequentially."""
        batch = self._current_batch or self.load_batch()
        if not batch:
            raise RuntimeError("No batch to process")

        logger.info("Starting batch %s (%d total, %d pending)",
                     batch.batch_id, len(batch.jobs), len(batch.pending_jobs()))

        while batch.pending_jobs():
            result = await self.process_next_job(engine)
            if result is None:
                break
            # Reload batch after each job for checkpoint safety
            batch = self.load_batch() or batch

        approved = len([j for j in batch.jobs if j.state == JobState.APPROVED])
        rejected = len([j for j in batch.jobs if j.state == JobState.REJECTED])
        failed = len([j for j in batch.jobs if j.state == JobState.FAILED])

        logger.info(
            "Batch %s complete: %d approved, %d rejected, %d failed",
            batch.batch_id, approved, rejected, failed,
        )
        return batch

    def get_batch_summary(self) -> dict:
        """Get summary statistics for the current batch."""
        batch = self._current_batch or self.load_batch()
        if not batch:
            return {"error": "No batch loaded"}

        state_counts = {}
        for j in batch.jobs:
            state_counts[j.state.value] = state_counts.get(j.state.value, 0) + 1

        return {
            "batch_id": batch.batch_id,
            "profile_id": batch.profile_id,
            "total_jobs": len(batch.jobs),
            "state_counts": state_counts,
            "created_at": batch.created_at,
        }

    def _save_batch(self, batch: ProductionBatch) -> None:
        """Persist batch state to disk (checkpoint)."""
        batch_path = self.batch_dir / self.BATCH_FILE
        batch_path.write_text(
            json.dumps(batch.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _log_event(self, event_type: str, data: dict) -> None:
        """Append structured log entry."""
        log_path = self.batch_dir / self.LOG_FILE
        entry = {
            "timestamp": time.time(),
            "event": event_type,
            **data,
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")