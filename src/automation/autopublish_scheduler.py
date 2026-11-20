"""AutoPublish Scheduler — integrates PublishQueue with ProductionScheduler.

Manages the full lifecycle from content production to social media publishing:
- Persistent job queue with idempotency keys
- Retry with exponential backoff (max 5 attempts)
- Duplicate prevention via content hash deduplication
- QualityGate approval required before publishing
- OAuth authentication validation before publishing
- Timezone-aware scheduling per profile
- Recovery after restart (loads pending jobs from disk)
- Cancellation and rescheduling
- Historical tracking with confirmed results

Designed for MacBook M2 8GB: sequential processing, no parallel publishes.
Launchd integration prepared but DISABLED by default (requires explicit owner authorization).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MAX_RETRY_ATTEMPTS = 5
BASE_RETRY_DELAY_SECONDS = 60  # 1 minute base, doubles each retry


@dataclass
class AutoPublishJob:
    """A single auto-publish job with full lifecycle tracking."""
    job_id: str
    profile_id: str
    platform: str
    video_path: str
    title: str
    description: str = ""
    hashtags: tuple[str, ...] = ()
    thumbnail_path: Optional[str] = None
    scheduled_at: Optional[float] = None  # Unix timestamp (None = immediate when eligible)
    timezone: str = "America/Sao_Paulo"
    privacy: str = "public"

    # Lifecycle state
    state: str = "pending"  # pending, approved, auth_blocked, publishing, published, failed, cancelled, rescheduled
    quality_gate_passed: bool = False
    quality_gate_score: float = 0.0
    auth_state: str = "not_checked"  # not_checked, connected, auth_required, token_expired

    # Idempotency & dedup
    content_hash: str = ""  # SHA-256 of video_path + title + platform
    idempotency_key: str = ""  # Unique key to prevent duplicate submissions

    # Retry tracking
    retry_count: int = 0
    max_retries: int = MAX_RETRY_ATTEMPTS
    next_retry_at: float = 0.0  # Unix timestamp for next retry attempt
    last_error: str = ""

    # Results
    platform_post_id: Optional[str] = None
    permalink: Optional[str] = None
    published_at: Optional[float] = None

    # Timestamps
    created_at: float = 0.0
    updated_at: float = 0.0
    approved_at: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> AutoPublishJob:
        valid_fields = {k for k in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in valid_fields})

    @staticmethod
    def compute_content_hash(video_path: str, title: str, platform: str) -> str:
        """Compute deterministic hash for deduplication."""
        raw = f"{video_path}|{title}|{platform}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def generate_idempotency_key(profile_id: str, platform: str, video_path: str, title: str) -> str:
        """Generate unique idempotency key to prevent duplicate job submissions."""
        raw = f"{profile_id}:{platform}:{video_path}:{title}"
        return hashlib.sha256(raw.encode()).hexdigest()[:12]


class AutoPublishScheduler:
    """Orchestrates content publishing with persistence, retries, and guards."""

    JOBS_FILE = "autopublish_jobs.json"
    HISTORY_FILE = "autopublish_history.json"
    LAUNCHD_PLIST = "com.jhc.autopublish.plist"

    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.scheduler_dir = data_root / "scheduler"
        self.scheduler_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_path = self.scheduler_dir / self.JOBS_FILE
        self.history_path = self.scheduler_dir / self.HISTORY_FILE
        self._jobs: dict[str, AutoPublishJob] = {}  # job_id → job
        self._load_jobs()

    def _load_jobs(self) -> None:
        """Load persistent jobs from disk."""
        if not self.jobs_path.exists():
            return
        try:
            data = json.loads(self.jobs_path.read_text(encoding="utf-8"))
            for job_dict in data:
                job = AutoPublishJob.from_dict(job_dict)
                self._jobs[job.job_id] = job
            logger.info("Loaded %d autopublish jobs from disk", len(self._jobs))
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Could not load autopublish jobs: %s", e)

    def _save_jobs(self) -> None:
        """Persist all active jobs to disk."""
        data = [j.to_dict() for j in self._jobs.values()]
        self.jobs_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _save_to_history(self, job: AutoPublishJob) -> None:
        """Append completed/failed/cancelled job to history."""
        history: list[dict] = []
        if self.history_path.exists():
            try:
                history = json.loads(self.history_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                history = []
        history.append(job.to_dict())
        # Keep last 500 entries
        history = history[-500:]
        self.history_path.write_text(
            json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # --- Job submission ---

    async def execute_tiktok_hybrid(self, job: AutoPublishJob) -> dict:
        """Hybrid TikTok publisher: API first → Playwright fallback.

        Selection policy:
        1. Check TikTokAdapter (API) connection state.
        2. If CONNECTED → attempt API upload via adapters.TikTokAdapter.
        3. If API returns PERMISSION_REQUIRED or AUTH_REQUIRED → check BrowserPublisher session.
        4. If browser session valid → attempt Playwright upload via BrowserPublisher._publish_tiktok.
        5. If both fail → mark job as failed with detailed error.
        6. NEVER auto-fallback after uncertain result (upload started but no confirmation).

        Returns dict with 'status', 'method', 'job_id', 'error' keys.
        """
        from src.publishing.adapters import TikTokAdapter, PublishJob, PublishState
        from src.publishing.browser_publisher import BrowserPublisher, PublishRequest

        result = {"job_id": job.job_id, "method": None, "status": None, "error": None}

        # Step 1: Try API adapter
        api_adapter = TikTokAdapter(self.data_root / "publishing" / "credentials", job.profile_id)
        api_state = await api_adapter.check_connection()

        if api_state == PublishState.CONNECTED:
            logger.info("TikTok hybrid: attempting API upload for %s", job.job_id)
            publish_job = PublishJob(
                job_id=job.job_id,
                profile_id=job.profile_id,
                platform="tiktok",
                video_path=job.video_path,
                title=job.title,
                description=job.description or "",
                hashtags=tuple(job.hashtags) if job.hashtags else (),
                state="queued",
            )
            api_result = await api_adapter.upload(publish_job)
            result["method"] = "api"

            if api_result.state == PublishState.PROCESSING.value:
                # Upload accepted, poll for confirmation
                polled = await api_adapter.poll_status(api_result)
                if polled.state == PublishState.PUBLISHED.value:
                    self.mark_published(job.job_id, platform_post_id=polled.remote_id or "", permalink=polled.published_url or "")
                    result["status"] = "published"
                    result["remote_id"] = polled.remote_id
                    result["url"] = polled.published_url
                    return result
                elif polled.state == PublishState.ERROR.value:
                    self.mark_failed(job.job_id, polled.error_message or "API publish failed", retry=True)
                    result["status"] = "failed"
                    result["error"] = polled.error_message
                    return result
                else:
                    # Still processing — do NOT fallback to Playwright
                    self._jobs[job.job_id].state = "processing"
                    self._jobs[job.job_id].remote_id = api_result.remote_id
                    self._save_jobs()
                    result["status"] = "processing"
                    result["remote_id"] = api_result.remote_id
                    return result

            elif api_result.state == PublishState.PERMISSION_REQUIRED.value:
                # App not approved — fall through to Playwright check
                logger.info("TikTok hybrid: API permission_required, checking browser session")
                result["method"] = "api_denied"
            elif api_result.state == PublishState.ERROR.value:
                result["status"] = "failed"
                result["error"] = api_result.error_message
                self.mark_failed(job.job_id, api_result.error_message or "API upload failed", retry=True)
                return result
            else:
                # Unknown state — do NOT fallback
                result["status"] = "uncertain"
                result["error"] = f"API returned unexpected state: {api_result.state}"
                return result
        else:
            logger.info("TikTok hybrid: API state=%s, checking browser session", api_state.value)
            result["method"] = f"api_{api_state.value}"

        # Step 2: Check BrowserPublisher session for Playwright fallback
        browser_pub = BrowserPublisher(self.data_root)
        session_ok = await browser_pub.check_session("tiktok")

        if not session_ok.get("active", False):
            # No valid browser session — cannot fallback
            error_msg = f"API unavailable ({result['method']}) and no active browser session. Login required."
            self.mark_failed(job.job_id, error_msg, retry=False)
            result["status"] = "auth_required"
            result["error"] = error_msg
            return result

        # Step 3: Attempt Playwright upload
        logger.info("TikTok hybrid: attempting Playwright upload for %s", job.job_id)
        result["method"] = "playwright"
        try:
            req = PublishRequest(
                platform="tiktok",
                video_path=job.video_path,
                title=job.title,
                description=job.description or "",
                tags=job.tags or [],
                privacy="private",  # Safe default
            )
            pub_result = await browser_pub.publish(req)

            if pub_result.success:
                self.mark_published(job.job_id, platform_post_id=pub_result.post_id or "", permalink=pub_result.url or "")
                result["status"] = "published"
                result["url"] = pub_result.url
                return result
            else:
                error_msg = pub_result.error or "Playwright upload failed"
                self.mark_failed(job.job_id, error_msg, retry=True)
                result["status"] = "failed"
                result["error"] = error_msg
                return result

        except Exception as e:
            error_msg = f"Playwright error: {str(e)[:200]}"
            logger.error("TikTok hybrid Playwright error: %s", e)
            self.mark_failed(job.job_id, error_msg, retry=True)
            result["status"] = "failed"
            result["error"] = error_msg
            return result

    def submit_job(self, job: AutoPublishJob) -> dict:
        """Submit a new publish job with idempotency and dedup checks.

        Returns dict with 'status' ('submitted', 'duplicate', 'error') and job info.
        """
        now = time.time()
        job.created_at = now
        job.updated_at = now

        # Compute dedup hash
        job.content_hash = AutoPublishJob.compute_content_hash(
            job.video_path, job.title, job.platform
        )
        job.idempotency_key = AutoPublishJob.generate_idempotency_key(
            job.profile_id, job.platform, job.video_path, job.title
        )

        # Check for duplicate active job
        for existing in self._jobs.values():
            if existing.idempotency_key == job.idempotency_key and existing.state not in (
                "published", "failed", "cancelled"
            ):
                return {
                    "status": "duplicate",
                    "existing_job_id": existing.job_id,
                    "message": f"Job already exists: {existing.job_id} (state={existing.state})",
                }

        # Check content hash dedup across active jobs
        for existing in self._jobs.values():
            if (
                existing.content_hash == job.content_hash
                and existing.state not in ("published", "failed", "cancelled")
                and existing.platform == job.platform
            ):
                return {
                    "status": "duplicate",
                    "existing_job_id": existing.job_id,
                    "message": f"Same content already queued for {job.platform}: {existing.job_id}",
                }

        self._jobs[job.job_id] = job
        self._save_jobs()
        logger.info(
            "Autopublish job submitted: %s → %s/%s (scheduled=%s)",
            job.job_id, job.profile_id, job.platform,
            job.scheduled_at or "immediate",
        )
        return {"status": "submitted", "job_id": job.job_id, "job": job.to_dict()}

    # --- Guards ---

    def check_quality_gate(self, job_id: str, passed: bool, score: float = 0.0) -> dict:
        """Mark a job as approved or blocked by QualityGate."""
        job = self._jobs.get(job_id)
        if not job:
            return {"error": f"Job {job_id} not found"}

        job.quality_gate_passed = passed
        job.quality_gate_score = score
        job.updated_at = time.time()

        if passed:
            job.state = "approved"
            job.approved_at = time.time()
            logger.info("Job %s approved by QualityGate (score=%.2f)", job_id, score)
        else:
            job.state = "failed"
            job.last_error = f"QualityGate rejected (score={score:.2f})"
            logger.warning("Job %s rejected by QualityGate (score=%.2f)", job_id, score)
            self._save_to_history(job)

        self._save_jobs()
        return {"job_id": job_id, "state": job.state, "quality_gate_passed": passed, "score": score}

    def check_auth(self, job_id: str, auth_state: str) -> dict:
        """Update auth state for a job. Blocks publishing if not connected, unblocks when connected."""
        job = self._jobs.get(job_id)
        if not job:
            return {"error": f"Job {job_id} not found"}

        job.auth_state = auth_state
        job.updated_at = time.time()

        if auth_state != "connected" and job.state == "approved":
            job.state = "auth_blocked"
            job.last_error = f"Authentication required: {auth_state}"
            logger.warning("Job %s blocked: auth_state=%s", job_id, auth_state)
        elif auth_state == "connected" and job.state == "auth_blocked" and job.quality_gate_passed:
            # Unblock: restore to approved so it becomes eligible again
            job.state = "approved"
            job.last_error = ""
            logger.info("Job %s unblocked: auth connected, QG passed", job_id)

        self._save_jobs()
        return {"job_id": job_id, "auth_state": auth_state, "state": job.state}

    # --- Scheduling & execution ---

    def get_eligible_jobs(self, limit: int = 10) -> list[AutoPublishJob]:
        """Get jobs that are ready for publishing right now.

        Eligible = state is 'approved', scheduled_at <= now (or None),
        auth_state is 'connected', retry delay has passed.
        """
        now = time.time()
        eligible = []
        for job in self._jobs.values():
            if job.state != "approved":
                continue
            if job.auth_state != "connected":
                continue
            if job.scheduled_at and job.scheduled_at > now:
                continue
            if job.next_retry_at and job.next_retry_at > now:
                continue
            eligible.append(job)

        # Sort by scheduled_at (None first = immediate), then created_at
        eligible.sort(key=lambda j: (j.scheduled_at or 0, j.created_at))
        return eligible[:limit]

    def mark_publishing(self, job_id: str) -> dict:
        """Mark a job as currently being published."""
        job = self._jobs.get(job_id)
        if not job:
            return {"error": f"Job {job_id} not found"}
        job.state = "publishing"
        job.updated_at = time.time()
        self._save_jobs()
        return {"job_id": job_id, "state": "publishing"}

    def mark_published(self, job_id: str, platform_post_id: str = "", permalink: str = "") -> dict:
        """Mark a job as successfully published."""
        job = self._jobs.get(job_id)
        if not job:
            return {"error": f"Job {job_id} not found"}
        job.state = "published"
        job.platform_post_id = platform_post_id
        job.permalink = permalink
        job.published_at = time.time()
        job.updated_at = time.time()
        self._save_to_history(job)
        del self._jobs[job_id]
        self._save_jobs()
        logger.info("Job %s published: %s", job_id, permalink or platform_post_id)
        return {"job_id": job_id, "state": "published", "permalink": permalink}

    def mark_failed(self, job_id: str, error: str, retry: bool = True) -> dict:
        """Mark a job as failed, optionally scheduling a retry with backoff."""
        job = self._jobs.get(job_id)
        if not job:
            return {"error": f"Job {job_id} not found"}

        job.last_error = error
        job.updated_at = time.time()

        if retry and job.retry_count < job.max_retries:
            job.retry_count += 1
            delay = BASE_RETRY_DELAY_SECONDS * (2 ** (job.retry_count - 1))
            job.next_retry_at = time.time() + delay
            job.state = "pending"  # Back to pending for retry
            logger.info(
                "Job %s failed (attempt %d/%d), retry in %ds: %s",
                job_id, job.retry_count, job.max_retries, delay, error[:100],
            )
        else:
            job.state = "failed"
            logger.error("Job %s permanently failed after %d attempts: %s", job_id, job.retry_count, error[:200])
            self._save_to_history(job)
            del self._jobs[job_id]

        self._save_jobs()
        return {"job_id": job_id, "state": job.state, "retry_count": job.retry_count, "error": error}

    # --- Management ---

    def cancel_job(self, job_id: str) -> dict:
        """Cancel a pending/approved job."""
        job = self._jobs.get(job_id)
        if not job:
            return {"error": f"Job {job_id} not found"}
        if job.state in ("published", "cancelled"):
            return {"error": f"Cannot cancel job in state '{job.state}'"}
        job.state = "cancelled"
        job.updated_at = time.time()
        self._save_to_history(job)
        del self._jobs[job_id]
        self._save_jobs()
        logger.info("Job %s cancelled", job_id)
        return {"job_id": job_id, "state": "cancelled"}

    def reschedule_job(self, job_id: str, new_scheduled_at: float) -> dict:
        """Reschedule a pending/approved job to a new time."""
        job = self._jobs.get(job_id)
        if not job:
            return {"error": f"Job {job_id} not found"}
        if job.state in ("published", "cancelled", "failed"):
            return {"error": f"Cannot reschedule job in state '{job.state}'"}
        job.scheduled_at = new_scheduled_at
        job.state = "rescheduled" if job.state == "approved" else job.state
        job.updated_at = time.time()
        self._save_jobs()
        logger.info("Job %s rescheduled to %s", job_id, time.ctime(new_scheduled_at))
        return {"job_id": job_id, "state": job.state, "scheduled_at": new_scheduled_at}

    def get_job(self, job_id: str) -> Optional[dict]:
        """Get a single job by ID."""
        job = self._jobs.get(job_id)
        return job.to_dict() if job else None

    def list_jobs(self, profile_id: Optional[str] = None, state: Optional[str] = None, limit: int = 50) -> list[dict]:
        """List active jobs with optional filters."""
        jobs = list(self._jobs.values())
        if profile_id:
            jobs = [j for j in jobs if j.profile_id == profile_id]
        if state:
            jobs = [j for j in jobs if j.state == state]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return [j.to_dict() for j in jobs[:limit]]

    def get_history(self, profile_id: Optional[str] = None, limit: int = 50) -> list[dict]:
        """Get historical completed/failed/cancelled jobs."""
        if not self.history_path.exists():
            return []
        try:
            history = json.loads(self.history_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        if profile_id:
            history = [h for h in history if h.get("profile_id") == profile_id]
        return history[-limit:]

    # --- Global queue control (persistent) ---

    STATE_FILE = "scheduler_state.json"

    def _load_state(self) -> dict:
        """Load persistent scheduler state from disk."""
        state_path = self.scheduler_dir / self.STATE_FILE
        if not state_path.exists():
            return {"status": "stopped", "paused_at": None, "resumed_at": None}
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"status": "stopped", "paused_at": None, "resumed_at": None}

    def _save_state(self, state: dict) -> None:
        """Persist scheduler state to disk."""
        state_path = self.scheduler_dir / self.STATE_FILE
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def start_queue(self) -> dict:
        """Start the autopublish queue processing."""
        state = self._load_state()
        state["status"] = "running"
        state["resumed_at"] = time.time()
        state["started_at"] = state.get("started_at") or time.time()
        self._save_state(state)
        logger.info("Autopublish queue STARTED")
        return {"status": "running", "message": "Fila de publicação iniciada"}

    def pause_queue(self) -> dict:
        """Pause the autopublish queue (jobs stay queued, no new processing)."""
        state = self._load_state()
        state["status"] = "paused"
        state["paused_at"] = time.time()
        self._save_state(state)
        logger.info("Autopublish queue PAUSED")
        return {"status": "paused", "message": "Fila de publicação pausada"}

    def resume_queue(self) -> dict:
        """Resume a paused autopublish queue."""
        state = self._load_state()
        if state["status"] != "paused":
            return {"status": state["status"], "message": f"Fila não está pausada (estado={state['status']})"}
        state["status"] = "running"
        state["resumed_at"] = time.time()
        self._save_state(state)
        logger.info("Autopublish queue RESUMED")
        return {"status": "running", "message": "Fila de publicação retomada"}

    def stop_queue(self) -> dict:
        """Stop the autopublish queue completely."""
        state = self._load_state()
        state["status"] = "stopped"
        state["stopped_at"] = time.time()
        self._save_state(state)
        logger.info("Autopublish queue STOPPED")
        return {"status": "stopped", "message": "Fila de publicação parada"}

    def get_queue_status(self) -> dict:
        """Get current queue control status with job counts."""
        state = self._load_state()
        summary = self.get_status_summary()
        return {
            "queue_status": state.get("status", "stopped"),
            "started_at": state.get("started_at"),
            "paused_at": state.get("paused_at"),
            "resumed_at": state.get("resumed_at"),
            "stopped_at": state.get("stopped_at"),
            "active_jobs": summary["active_jobs"],
            "eligible_now": summary["eligible_now"] if state.get("status") == "running" else 0,
            "state_counts": summary["state_counts"],
            "platform_counts": summary["platform_counts"],
            "history_count": summary["history_count"],
        }

    def get_status_summary(self) -> dict:
        """Get overall scheduler status summary."""
        state_counts: dict[str, int] = {}
        platform_counts: dict[str, int] = {}
        profile_counts: dict[str, int] = {}
        for job in self._jobs.values():
            state_counts[job.state] = state_counts.get(job.state, 0) + 1
            platform_counts[job.platform] = platform_counts.get(job.platform, 0) + 1
            profile_counts[job.profile_id] = profile_counts.get(job.profile_id, 0) + 1

        history_count = 0
        if self.history_path.exists():
            try:
                history = json.loads(self.history_path.read_text(encoding="utf-8"))
                history_count = len(history)
            except json.JSONDecodeError:
                pass

        return {
            "active_jobs": len(self._jobs),
            "state_counts": state_counts,
            "platform_counts": platform_counts,
            "profile_counts": profile_counts,
            "history_count": history_count,
            "eligible_now": len(self.get_eligible_jobs()),
        }

    # --- Launchd integration (DISABLED by default) ---

    def get_launchd_plist_path(self) -> Path:
        """Get the path where the launchd plist would be installed."""
        return Path.home() / "Library" / "LaunchAgents" / self.LAUNCHD_PLIST

    def is_launchd_enabled(self) -> bool:
        """Check if the autopublish launchd service is enabled."""
        plist_path = self.get_launchd_plist_path()
        return plist_path.exists()

    def generate_launchd_plist(self) -> str:
        """Generate the launchd plist content (does NOT install it)."""
        import sys
        python_path = sys.executable
        script_path = str(self.data_root.parent / "scripts" / "autopublish_worker.py")
        log_path = "/tmp/jhc_autopublish.log"

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.jhc.autopublish</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>{script_path}</string>
    </array>
    <key>RunAtLoad</key>
    <false/>
    <key>StartInterval</key>
    <integer>300</integer>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>JHC_DATA_ROOT</key>
        <string>{self.data_root}</string>
    </dict>
</dict>
</plist>"""

    def get_launchd_status(self) -> dict:
        """Get launchd integration status."""
        plist_path = self.get_launchd_plist_path()
        return {
            "enabled": plist_path.exists(),
            "plist_path": str(plist_path),
            "note": "Launchd service is DISABLED by default. Enable via dashboard after explicit owner authorization.",
        }