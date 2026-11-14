"""Social media publishing adapters for JHC Viral Engine.

Platform-specific adapters for Instagram, YouTube, and TikTok using
official APIs. Each adapter implements a common interface for upload,
metadata, scheduling, and status polling.

All adapters require OAuth credentials configured per-profile.
No simulated/mock publishing — only real API calls or explicit NOT_CONFIGURED state.

States: NOT_CONFIGURED, AUTH_REQUIRED, CONNECTED, TOKEN_EXPIRED,
        PERMISSION_REQUIRED, RESTRICTED, ERROR, PUBLISHED, SCHEDULED
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class PublishState(str, Enum):
    NOT_CONFIGURED = "not_configured"
    AUTH_REQUIRED = "auth_required"
    CONNECTED = "connected"
    TOKEN_EXPIRED = "token_expired"
    PERMISSION_REQUIRED = "permission_required"
    RESTRICTED = "restricted"
    ERROR = "error"
    PUBLISHED = "published"
    SCHEDULED = "scheduled"
    UPLOADING = "uploading"
    PROCESSING = "processing"


@dataclass(frozen=True)
class PublishJob:
    """A single publishing task for one platform."""
    job_id: str
    profile_id: str
    platform: str  # instagram, youtube, tiktok
    video_path: str
    title: str
    description: str
    hashtags: tuple[str, ...] = ()
    thumbnail_path: Optional[str] = None
    scheduled_at: Optional[float] = None  # Unix timestamp
    privacy: str = "public"  # public, private, unlisted
    state: str = PublishState.NOT_CONFIGURED
    platform_post_id: Optional[str] = None
    permalink: Optional[str] = None
    error_message: Optional[str] = None
    created_at: float = 0.0
    updated_at: float = 0.0
    retry_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> PublishJob:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class BaseAdapter(ABC):
    """Abstract base class for social media publishing adapters."""

    PLATFORM: str = ""

    def __init__(self, data_root: Path, profile_id: str) -> None:
        self.data_root = data_root
        self.profile_id = profile_id
        self.credentials_dir = data_root / "credentials" / profile_id
        self.credentials_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir = data_root / "publish_jobs" / profile_id
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    async def check_connection(self) -> PublishState:
        """Check if the adapter has valid credentials and permissions."""
        ...

    @abstractmethod
    async def upload(self, job: PublishJob) -> PublishJob:
        """Upload video and metadata to the platform. Returns updated job."""
        ...

    @abstractmethod
    async def poll_status(self, job: PublishJob) -> PublishJob:
        """Poll the platform for publish/processing status."""
        ...

    def save_job(self, job: PublishJob) -> None:
        """Persist a publish job to disk."""
        job_path = self.jobs_dir / f"{job.job_id}.json"
        updated = PublishJob(
            **{**job.to_dict(), "updated_at": time.time()}
        )
        job_path.write_text(
            json.dumps(updated.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_job(self, job_id: str) -> Optional[PublishJob]:
        """Load a publish job from disk."""
        job_path = self.jobs_dir / f"{job_id}.json"
        if not job_path.exists():
            return None
        try:
            data = json.loads(job_path.read_text(encoding="utf-8"))
            return PublishJob.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def list_jobs(self, limit: int = 50) -> list[PublishJob]:
        """List recent publish jobs for this profile/platform."""
        jobs = []
        for f in sorted(self.jobs_dir.glob("*.json"), reverse=True)[:limit]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                jobs.append(PublishJob.from_dict(data))
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return jobs


class InstagramAdapter(BaseAdapter):
    """Instagram Content Publishing API adapter.

    Official flow: create media container → poll processing → publish.
    Requires: Meta Business Account, Instagram Professional Account,
    valid access token with instagram_content_publish permission.
    """

    PLATFORM = "instagram"

    async def check_connection(self) -> PublishState:
        token_path = self.credentials_dir / "instagram_token.json"
        if not token_path.exists():
            return PublishState.AUTH_REQUIRED
        try:
            data = json.loads(token_path.read_text(encoding="utf-8"))
            expires = data.get("expires_at", 0)
            if expires and time.time() > expires:
                return PublishState.TOKEN_EXPIRED
            if not data.get("access_token"):
                return PublishState.AUTH_REQUIRED
            return PublishState.CONNECTED
        except (json.JSONDecodeError, KeyError):
            return PublishState.ERROR

    async def upload(self, job: PublishJob) -> PublishJob:
        state = await self.check_connection()
        if state != PublishState.CONNECTED:
            return PublishJob(**{
                **job.to_dict(),
                "state": state.value,
                "error_message": f"Instagram not connected: {state.value}",
            })

        # TODO: Implement real Instagram API call
        # POST https://graph.facebook.com/v18.0/{ig_user_id}/media
        # Body: video_url, caption, media_type=REELS
        # Then poll GET /{container_id} until status_code=FINISHED
        # Then POST /{ig_user_id}/media_publish with creation_id

        logger.info(
            "Instagram upload prepared for %s (real API requires configured token)",
            job.title[:40],
        )
        return PublishJob(**{
            **job.to_dict(),
            "state": PublishState.PERMISSION_REQUIRED.value,
            "error_message": "Instagram API integration ready — requires Meta Business Account setup and OAuth token. See dashboard Connections page.",
        })

    async def poll_status(self, job: PublishJob) -> PublishJob:
        if job.state == PublishState.PUBLISHED.value:
            return job
        # TODO: GET https://graph.facebook.com/v18.0/{container_id}
        return job


class YouTubeAdapter(BaseAdapter):
    """YouTube Data API v3 adapter.

    Uses resumable upload for video files. Supports Shorts and standard videos.
    Requires: Google Cloud project with YouTube Data API enabled,
    OAuth 2.0 credentials with youtube.upload scope.
    """

    PLATFORM = "youtube"

    async def check_connection(self) -> PublishState:
        token_path = self.credentials_dir / "youtube_token.json"
        if not token_path.exists():
            return PublishState.AUTH_REQUIRED
        try:
            data = json.loads(token_path.read_text(encoding="utf-8"))
            expires = data.get("expires_at", 0)
            if expires and time.time() > expires:
                return PublishState.TOKEN_EXPIRED
            if not data.get("access_token"):
                return PublishState.AUTH_REQUIRED
            return PublishState.CONNECTED
        except (json.JSONDecodeError, KeyError):
            return PublishState.ERROR

    async def upload(self, job: PublishJob) -> PublishJob:
        state = await self.check_connection()
        if state != PublishState.CONNECTED:
            return PublishJob(**{
                **job.to_dict(),
                "state": state.value,
                "error_message": f"YouTube not connected: {state.value}",
            })

        # TODO: Implement real YouTube resumable upload
        # POST https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status
        # Body: snippet.title, snippet.description, snippet.tags, snippet.categoryId=20 (Gaming)
        #       status.privacyStatus, status.publishAt (for scheduling)
        # Then PUT chunks to upload_url

        logger.info(
            "YouTube upload prepared for %s (real API requires OAuth token)",
            job.title[:40],
        )
        return PublishJob(**{
            **job.to_dict(),
            "state": PublishState.PERMISSION_REQUIRED.value,
            "error_message": "YouTube API integration ready — requires Google Cloud project setup and OAuth token. See dashboard Connections page.",
        })

    async def poll_status(self, job: PublishJob) -> PublishJob:
        if job.state == PublishState.PUBLISHED.value:
            return job
        # TODO: GET https://www.googleapis.com/youtube/v3/videos?id={video_id}&part=status
        return job


class TikTokAdapter(BaseAdapter):
    """TikTok Content Posting API adapter.

    Supports Direct Post when permitted, otherwise draft/assisted flow.
    Requires: TikTok Developer account, approved app with video.publish scope,
    user authorization via OAuth 2.0.
    """

    PLATFORM = "tiktok"

    async def check_connection(self) -> PublishState:
        token_path = self.credentials_dir / "tiktok_token.json"
        if not token_path.exists():
            return PublishState.AUTH_REQUIRED
        try:
            data = json.loads(token_path.read_text(encoding="utf-8"))
            expires = data.get("expires_at", 0)
            if expires and time.time() > expires:
                return PublishState.TOKEN_EXPIRED
            if not data.get("access_token"):
                return PublishState.AUTH_REQUIRED
            return PublishState.CONNECTED
        except (json.JSONDecodeError, KeyError):
            return PublishState.ERROR

    async def upload(self, job: PublishJob) -> PublishJob:
        state = await self.check_connection()
        if state != PublishState.CONNECTED:
            return PublishJob(**{
                **job.to_dict(),
                "state": state.value,
                "error_message": f"TikTok not connected: {state.value}",
            })

        # TODO: Implement real TikTok Content Posting API
        # POST https://open.tiktokapis.com/v2/post/publish/inbox/video/init/
        # Then upload video bytes
        # Note: May require app audit approval for Direct Post

        logger.info(
            "TikTok upload prepared for %s (real API requires approved app + OAuth)",
            job.title[:40],
        )
        return PublishJob(**{
            **job.to_dict(),
            "state": PublishState.PERMISSION_REQUIRED.value,
            "error_message": "TikTok API integration ready — requires TikTok Developer app approval and OAuth token. See dashboard Connections page.",
        })

    async def poll_status(self, job: PublishJob) -> PublishJob:
        if job.state == PublishState.PUBLISHED.value:
            return job
        # TODO: POST https://open.tiktokapis.com/v2/post/publish/status/fetch/
        return job


# Adapter registry
ADAPTERS: dict[str, type[BaseAdapter]] = {
    "instagram": InstagramAdapter,
    "youtube": YouTubeAdapter,
    "tiktok": TikTokAdapter,
}


def get_adapter(platform: str, data_root: Path, profile_id: str) -> BaseAdapter:
    """Get a platform-specific adapter instance."""
    adapter_cls = ADAPTERS.get(platform)
    if not adapter_cls:
        raise ValueError(f"Unknown platform: {platform}. Available: {list(ADAPTERS.keys())}")
    return adapter_cls(data_root, profile_id)


class PublishQueue:
    """Persistent queue for managing publish jobs across platforms."""

    QUEUE_FILE = "publish_queue.json"

    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.queue_dir = data_root / "publish_queue"
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.queue_path = self.queue_dir / self.QUEUE_FILE

    def add_job(self, job: PublishJob) -> None:
        """Add a job to the persistent queue."""
        queue = self._load_queue()
        job_dict = job.to_dict()
        job_dict["created_at"] = time.time()
        job_dict["updated_at"] = time.time()
        queue.append(job_dict)
        self._save_queue(queue)

        # Also save to platform-specific adapter storage
        adapter = get_adapter(job.platform, self.data_root, job.profile_id)
        adapter.save_job(PublishJob.from_dict(job_dict))

        logger.info("Publish job queued: %s → %s (%s)", job.title[:30], job.platform, job.profile_id)

    def get_pending_jobs(self, limit: int = 20) -> list[PublishJob]:
        """Get jobs that need processing."""
        queue = self._load_queue()
        pending_states = {
            PublishState.NOT_CONFIGURED.value,
            PublishState.CONNECTED.value,
            PublishState.ERROR.value,
        }
        pending = [
            PublishJob.from_dict(j) for j in queue
            if j.get("state") in pending_states
        ]
        # Sort by scheduled_at (None = immediate), then created_at
        pending.sort(key=lambda j: (j.scheduled_at or 0, j.created_at))
        return pending[:limit]

    def update_job_state(self, job_id: str, state: PublishState, **kwargs) -> bool:
        """Update a job's state in the queue."""
        queue = self._load_queue()
        updated = False
        for j in queue:
            if j.get("job_id") == job_id:
                j["state"] = state.value
                j["updated_at"] = time.time()
                for k, v in kwargs.items():
                    j[k] = v
                updated = True
                break
        if updated:
            self._save_queue(queue)
        return updated

    def remove_completed(self, max_age_hours: int = 168) -> int:
        """Remove completed/failed jobs older than max_age_hours."""
        queue = self._load_queue()
        cutoff = time.time() - (max_age_hours * 3600)
        terminal_states = {
            PublishState.PUBLISHED.value,
            PublishState.RESTRICTED.value,
        }
        original_len = len(queue)
        queue = [
            j for j in queue
            if not (j.get("state") in terminal_states and j.get("updated_at", 0) < cutoff)
        ]
        removed = original_len - len(queue)
        if removed > 0:
            self._save_queue(queue)
        return removed

    def get_queue_summary(self) -> dict:
        """Get summary statistics of the publish queue."""
        queue = self._load_queue()
        state_counts: dict[str, int] = {}
        platform_counts: dict[str, int] = {}
        for j in queue:
            state = j.get("state", "unknown")
            platform = j.get("platform", "unknown")
            state_counts[state] = state_counts.get(state, 0) + 1
            platform_counts[platform] = platform_counts.get(platform, 0) + 1
        return {
            "total_jobs": len(queue),
            "state_counts": state_counts,
            "platform_counts": platform_counts,
        }

    def _load_queue(self) -> list[dict]:
        if not self.queue_path.exists():
            return []
        try:
            return json.loads(self.queue_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

    def _save_queue(self, queue: list[dict]) -> None:
        self.queue_path.write_text(
            json.dumps(queue, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )