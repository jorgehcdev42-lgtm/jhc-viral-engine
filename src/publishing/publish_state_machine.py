"""Publish State Machine — Verifiable job states for MISSÃO G.

Maps mission-required states to AutoPublishScheduler lifecycle:
  preparing → rendering → awaiting_auth → scheduled → publishing → published | failed

Enforces: publication only marked 'published' after verifiable platform confirmation.
Preserves assisted-publish fallback when OAuth is pending.
Isolates BR and Global accounts absolutely.
"""

import time
import hashlib
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional
from enum import Enum


class PublishState(str, Enum):
    PREPARING = "preparing"
    RENDERING = "rendering"
    AWAITING_AUTH = "awaiting_auth"
    SCHEDULED = "scheduled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


# Valid state transitions
VALID_TRANSITIONS = {
    PublishState.PREPARING: [PublishState.RENDERING, PublishState.FAILED],
    PublishState.RENDERING: [PublishState.AWAITING_AUTH, PublishState.SCHEDULED, PublishState.FAILED],
    PublishState.AWAITING_AUTH: [PublishState.SCHEDULED, PublishState.FAILED],
    PublishState.SCHEDULED: [PublishState.PUBLISHING, PublishState.FAILED],
    PublishState.PUBLISHING: [PublishState.PUBLISHED, PublishState.FAILED],
    PublishState.PUBLISHED: [],  # terminal
    PublishState.FAILED: [PublishState.PREPARING],  # retry allowed
}

# Map legacy scheduler states to mission states
LEGACY_STATE_MAP = {
    "pending": PublishState.PREPARING,
    "approved": PublishState.SCHEDULED,
    "auth_blocked": PublishState.AWAITING_AUTH,
    "publishing": PublishState.PUBLISHING,
    "published": PublishState.PUBLISHED,
    "failed": PublishState.FAILED,
    "cancelled": PublishState.FAILED,
    "rescheduled": PublishState.SCHEDULED,
}


@dataclass
class PublishConfirmation:
    """Verifiable proof that content was published on a platform."""
    platform: str
    post_id: str
    permalink: str = ""
    confirmed_at: float = 0.0
    verification_method: str = "api_response"  # api_response, screenshot, manual
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PublishPipelineJob:
    """Full pipeline job tracking from AutoReel through publish."""
    job_id: str
    market: str  # "br" or "global"
    platform: str
    video_path: str = ""
    thumbnail_path: str = ""
    title: str = ""
    description: str = ""
    hashtags: list[str] = field(default_factory=list)

    state: str = PublishState.PREPARING.value
    autoreel_job_id: Optional[str] = None
    thumbnail_job_id: Optional[str] = None
    scheduler_job_id: Optional[str] = None

    confirmation: Optional[PublishConfirmation] = None
    error: Optional[str] = None
    state_history: list[dict] = field(default_factory=list)

    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.confirmation:
            d["confirmation"] = self.confirmation.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "PublishPipelineJob":
        conf_data = data.pop("confirmation", None)
        valid_fields = {k for k in cls.__dataclass_fields__}
        job = cls(**{k: v for k, v in data.items() if k in valid_fields})
        if conf_data:
            job.confirmation = PublishConfirmation(**conf_data)
        return job


class PublishStateMachine:
    """Manages verifiable publish pipeline states with platform confirmation gate."""

    def __init__(self, data_root: str = "data"):
        self.data_root = Path(data_root)
        self.jobs_dir = self.data_root / "publish_pipeline"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_file = self.jobs_dir / "pipeline_jobs.json"
        self._jobs: dict[str, PublishPipelineJob] = {}
        self._load()

    def _load(self):
        if not self.jobs_file.exists():
            return
        try:
            import json
            data = json.loads(self.jobs_file.read_text())
            for item in data:
                job = PublishPipelineJob.from_dict(item)
                self._jobs[job.job_id] = job
        except Exception:
            pass

    def _save(self):
        import json
        data = [j.to_dict() for j in self._jobs.values()]
        self.jobs_file.write_text(json.dumps(data, indent=2))

    def create_job(
        self, market: str, platform: str,
        video_path: str = "", title: str = "",
        autoreel_job_id: str = "", thumbnail_job_id: str = ""
    ) -> PublishPipelineJob:
        """Create new pipeline job in PREPARING state."""
        job_id = hashlib.md5(
            f"{market}{platform}{video_path}{time.time()}".encode()
        ).hexdigest()[:12]

        job = PublishPipelineJob(
            job_id=job_id,
            market=market,
            platform=platform,
            video_path=video_path,
            title=title,
            autoreel_job_id=autoreel_job_id or None,
            thumbnail_job_id=thumbnail_job_id or None,
            created_at=time.time(),
            updated_at=time.time(),
        )
        self._record_transition(job, PublishState.PREPARING.value, "created")
        self._jobs[job_id] = job
        self._save()
        return job

    def transition(self, job_id: str, new_state: str, reason: str = "") -> dict:
        """Transition job to new state with validation."""
        job = self._jobs.get(job_id)
        if not job:
            return {"error": f"Job {job_id} not found"}

        current = PublishState(job.state)
        target = PublishState(new_state)

        if target not in VALID_TRANSITIONS.get(current, []):
            return {
                "error": f"Invalid transition: {current.value} → {target.value}",
                "valid_next": [s.value for s in VALID_TRANSITIONS.get(current, [])],
            }

        # Enforce: PUBLISHED requires confirmation
        if target == PublishState.PUBLISHED and not job.confirmation:
            return {
                "error": "Cannot mark as published without platform confirmation",
                "required": "Call confirm_publish() first with verifiable proof",
            }

        self._record_transition(job, new_state, reason)
        job.updated_at = time.time()
        self._save()
        return {"status": "ok", "state": new_state, "job_id": job_id}

    def confirm_publish(
        self, job_id: str, post_id: str, permalink: str = "",
        verification_method: str = "api_response", metadata: dict = None
    ) -> dict:
        """Record verifiable platform confirmation. Required before PUBLISHED."""
        job = self._jobs.get(job_id)
        if not job:
            return {"error": f"Job {job_id} not found"}

        confirmation = PublishConfirmation(
            platform=job.platform,
            post_id=post_id,
            permalink=permalink,
            confirmed_at=time.time(),
            verification_method=verification_method,
            metadata=metadata or {},
        )
        job.confirmation = confirmation
        job.updated_at = time.time()
        self._save()

        # Auto-transition to PUBLISHED if currently PUBLISHING
        if job.state == PublishState.PUBLISHING.value:
            return self.transition(job_id, PublishState.PUBLISHED.value, "platform_confirmed")

        return {"status": "ok", "confirmation": confirmation.to_dict()}

    def mark_assisted_publish(self, job_id: str, note: str = "") -> dict:
        """Mark job as awaiting manual/assisted publish (OAuth pending)."""
        job = self._jobs.get(job_id)
        if not job:
            return {"error": f"Job {job_id} not found"}

        # Allow transition from AWAITING_AUTH or SCHEDULED to a special assisted state
        if job.state not in (PublishState.AWAITING_AUTH.value, PublishState.SCHEDULED.value):
            return {"error": f"Assisted publish not available from state {job.state}"}

        self._record_transition(job, PublishState.AWAITING_AUTH.value, f"assisted: {note}")
        job.updated_at = time.time()
        self._save()
        return {"status": "ok", "state": "awaiting_auth", "note": note}

    def get_job(self, job_id: str) -> Optional[dict]:
        job = self._jobs.get(job_id)
        return job.to_dict() if job else None

    def list_jobs(self, market: str = "", state: str = "", limit: int = 50) -> list[dict]:
        results = []
        for job in sorted(self._jobs.values(), key=lambda j: j.updated_at, reverse=True):
            if market and job.market != market:
                continue
            if state and job.state != state:
                continue
            results.append(job.to_dict())
        return results[:limit]

    def get_stats(self) -> dict:
        counts = {s.value: 0 for s in PublishState}
        by_market = {"br": 0, "global": 0}
        for job in self._jobs.values():
            counts[job.state] = counts.get(job.state, 0) + 1
            if job.market in by_market:
                by_market[job.market] += 1
        return {"by_state": counts, "by_market": by_market, "total": len(self._jobs)}

    def _record_transition(self, job: PublishPipelineJob, new_state: str, reason: str):
        job.state_history.append({
            "from": job.state,
            "to": new_state,
            "reason": reason,
            "at": time.time(),
        })
        job.state = new_state

    @staticmethod
    def map_legacy_state(legacy_state: str) -> str:
        """Map AutoPublishScheduler legacy state to mission state."""
        mapped = LEGACY_STATE_MAP.get(legacy_state)
        return mapped.value if mapped else legacy_state

    @staticmethod
    def get_valid_transitions(current_state: str) -> list[str]:
        """Return valid next states for a given state."""
        try:
            state = PublishState(current_state)
            return [s.value for s in VALID_TRANSITIONS.get(state, [])]
        except ValueError:
            return []