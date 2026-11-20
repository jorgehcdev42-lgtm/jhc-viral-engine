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
        # OAuth saves to instagram_oauth.json; legacy path was instagram_token.json
        token_path = self.credentials_dir / "instagram_oauth.json"
        legacy_path = self.credentials_dir / "instagram_token.json"
        path = token_path if token_path.exists() else legacy_path
        if not path.exists():
            return PublishState.AUTH_REQUIRED
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            expires = data.get("expires_at", 0)
            if expires and time.time() > expires:
                return PublishState.TOKEN_EXPIRED
            if not data.get("access_token"):
                return PublishState.AUTH_REQUIRED
            return PublishState.CONNECTED
        except (json.JSONDecodeError, KeyError):
            return PublishState.ERROR

    GRAPH_API_VERSION = "v21.0"
    BASE_URL = "https://graph.facebook.com"
    MAX_POLL_ATTEMPTS = 5
    POLL_INTERVAL_SECONDS = 60

    async def upload(self, job: PublishJob) -> PublishJob:
        """Upload Reel via Instagram Content Publishing API (3-step flow).

        Step 1: POST /{ig_user_id}/media → create REELS container
        Step 2: GET /{container_id}?fields=status_code → poll until FINISHED
        Step 3: POST /{ig_user_id}/media_publish → publish finished container

        Requires: instagram_business_basic + instagram_business_content_publish scopes.
        Rate limit: 100 API-published posts per rolling 24h window.
        """
        state = await self.check_connection()
        if state != PublishState.CONNECTED:
            return PublishJob(**{
                **job.to_dict(),
                "state": state.value,
                "error_message": f"Instagram not connected: {state.value}",
            })

        token_path = self.credentials_dir / "instagram_oauth.json"
        legacy_path = self.credentials_dir / "instagram_token.json"
        path = token_path if token_path.exists() else legacy_path
        try:
            token_data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            return PublishJob(**{**job.to_dict(), "state": PublishState.ERROR.value, "error_message": f"Cannot read Instagram token: {e}"})

        access_token = token_data.get("access_token", "")
        ig_user_id = token_data.get("account_id", "")
        if not access_token or not ig_user_id:
            return PublishJob(**{**job.to_dict(), "state": PublishState.AUTH_REQUIRED.value, "error_message": "Missing access_token or account_id in Instagram credentials"})

        import httpx
        import re as _re

        # Resolve video URL: if local path, host temporarily via Netlify; if already HTTPS, use directly
        video_url = job.video_path
        hosted_filename = None
        if not video_url:
            return PublishJob(**{
                **job.to_dict(),
                "state": PublishState.ERROR.value,
                "error_message": "video_path is empty",
            })

        if not _re.match(r'^https?://', video_url):
            # Local file — host temporarily via VideoHost (Netlify static site)
            from pathlib import Path as _Path
            local_path = _Path(video_url)
            if not local_path.exists():
                return PublishJob(**{
                    **job.to_dict(),
                    "state": PublishState.ERROR.value,
                    "error_message": f"Local video file not found: {video_url}",
                })
            try:
                from src.publishing.video_host import VideoHost
                project_root = self.credentials_dir.parent.parent  # data/credentials → project root
                host = VideoHost(project_root)
                host_result = host.host_video(local_path)
                if not host_result.get("success"):
                    return PublishJob(**{
                        **job.to_dict(),
                        "state": PublishState.ERROR.value,
                        "error_message": f"Failed to host video: {host_result.get('error', 'unknown')}",
                    })
                video_url = host_result["url"]
                hosted_filename = host_result.get("filename", "")
                logger.info(
                    "Local video hosted for Instagram upload: %s → %s (%.1fMB)",
                    local_path.name, hosted_filename, host_result.get("size_mb", 0),
                )
            except Exception as e:
                logger.error("Video hosting failed: %s", e)
                return PublishJob(**{
                    **job.to_dict(),
                    "state": PublishState.ERROR.value,
                    "error_message": f"Video hosting error: {str(e)[:200]}",
                })

        # Build caption with hashtags
        caption = job.description or ""
        if job.hashtags:
            tag_str = " ".join(f"#{t}" for t in job.hashtags[:30])
            caption = f"{caption}\n\n{tag_str}".strip()

        # --- Step 1: Create REELS media container ---
        container_url = f"{self.BASE_URL}/{self.GRAPH_API_VERSION}/{ig_user_id}/media"
        container_payload = {
            "media_type": "REELS",
            "video_url": job.video_path,
            "caption": caption[:2200],
            "share_to_feed": "true",
            "access_token": access_token,
        }
        if job.thumbnail_path:
            container_payload["cover_url"] = job.thumbnail_path

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(container_url, data=container_payload)
                data = resp.json()

            if resp.status_code != 200 or "id" not in data:
                error_msg = data.get("error", {}).get("message", str(data))[:300]
                # Permission errors → explicit state
                if "permission" in error_msg.lower() or "not authorized" in error_msg.lower():
                    return PublishJob(**{
                        **job.to_dict(),
                        "state": PublishState.PERMISSION_REQUIRED.value,
                        "error_message": f"Instagram API permission denied: {error_msg}",
                    })
                return PublishJob(**{
                    **job.to_dict(),
                    "state": PublishState.ERROR.value,
                    "error_message": f"Container creation failed: {error_msg}",
                })

            container_id = data["id"]
            logger.info("Instagram container created: %s for %s", container_id, job.title[:40])

        except Exception as e:
            logger.error("Instagram container creation error: %s", e)
            return PublishJob(**{**job.to_dict(), "state": PublishState.ERROR.value, "error_message": f"Network error creating container: {str(e)[:200]}"})

        # --- Step 2: Poll container status until FINISHED ---
        status_url = f"{self.BASE_URL}/{self.GRAPH_API_VERSION}/{container_id}"
        final_status = None
        for attempt in range(self.MAX_POLL_ATTEMPTS):
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    poll_resp = await client.get(
                        status_url,
                        params={"fields": "status_code", "access_token": access_token},
                    )
                    poll_data = poll_resp.json()

                status_code = poll_data.get("status_code", "UNKNOWN")
                logger.debug(
                    "Instagram poll %d/%d: container=%s status=%s",
                    attempt + 1, self.MAX_POLL_ATTEMPTS, container_id, status_code,
                )

                if status_code == "FINISHED":
                    final_status = "FINISHED"
                    break
                elif status_code in ("ERROR", "EXPIRED"):
                    error_info = poll_data.get("status_code", status_code)
                    return PublishJob(**{
                        **job.to_dict(),
                        "state": PublishState.ERROR.value,
                        "error_message": f"Container processing failed: {error_info}",
                        "platform_post_id": container_id,
                    })
                # IN_PROGRESS → wait and retry
                import asyncio
                await asyncio.sleep(self.POLL_INTERVAL_SECONDS)

            except Exception as e:
                logger.warning("Instagram poll error (attempt %d): %s", attempt + 1, e)
                import asyncio
                await asyncio.sleep(self.POLL_INTERVAL_SECONDS)

        if final_status != "FINISHED":
            return PublishJob(**{
                **job.to_dict(),
                "state": PublishState.PROCESSING.value,
                "error_message": f"Container still processing after {self.MAX_POLL_ATTEMPTS} polls — retry later",
                "platform_post_id": container_id,
            })

        # --- Step 3: Publish the finished container ---
        publish_url = f"{self.BASE_URL}/{self.GRAPH_API_VERSION}/{ig_user_id}/media_publish"
        publish_payload = {
            "creation_id": container_id,
            "access_token": access_token,
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                pub_resp = await client.post(publish_url, data=publish_payload)
                pub_data = pub_resp.json()

            if pub_resp.status_code != 200 or "id" not in pub_data:
                error_msg = pub_data.get("error", {}).get("message", str(pub_data))[:300]
                return PublishJob(**{
                    **job.to_dict(),
                    "state": PublishState.ERROR.value,
                    "error_message": f"Publish failed: {error_msg}",
                    "platform_post_id": container_id,
                })

            media_id = pub_data["id"]

            # Fetch shortcode for proper Reel permalink (media_id alone is not a valid URL slug)
            shortcode = ""
            try:
                async with httpx.AsyncClient(timeout=15) as meta_client:
                    meta_resp = await meta_client.get(
                        f"{self.BASE_URL}/{self.GRAPH_API_VERSION}/{media_id}",
                        params={"fields": "shortcode,permalink", "access_token": access_token},
                    )
                    meta_data = meta_resp.json()
                    shortcode = meta_data.get("shortcode", "")
                    if not shortcode:
                        shortcode = meta_data.get("permalink", "").rstrip("/").split("/")[-1]
            except Exception as e:
                logger.warning("Failed to fetch shortcode for media_id=%s: %s", media_id, e)

            permalink = f"https://www.instagram.com/reel/{shortcode}/" if shortcode else ""
            logger.info("Instagram Reel published: media_id=%s shortcode=%s", media_id, shortcode)

            return PublishJob(**{
                **job.to_dict(),
                "state": PublishState.PUBLISHED.value,
                "platform_post_id": media_id,
                "permalink": permalink,
            })

        except Exception as e:
            logger.error("Instagram publish error: %s", e)
            return PublishJob(**{
                **job.to_dict(),
                "state": PublishState.ERROR.value,
                "error_message": f"Network error publishing: {str(e)[:200]}",
                "platform_post_id": container_id,
            })

    async def poll_status(self, job: PublishJob) -> PublishJob:
        """Poll container or post status from Instagram Graph API."""
        if job.state == PublishState.PUBLISHED.value:
            return job
        if not job.platform_post_id:
            return job

        token_path = self.credentials_dir / "instagram_oauth.json"
        legacy_path = self.credentials_dir / "instagram_token.json"
        path = token_path if token_path.exists() else legacy_path
        if not path.exists():
            return job

        try:
            token_data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return job

        access_token = token_data.get("access_token", "")
        if not access_token:
            return job

        import httpx
        status_url = f"{self.BASE_URL}/{self.GRAPH_API_VERSION}/{job.platform_post_id}"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    status_url,
                    params={"fields": "status_code", "access_token": access_token},
                )
                data = resp.json()

            status_code = data.get("status_code", "")
            if status_code == "FINISHED":
                # Container ready but not yet published — caller should re-upload
                return job
            elif status_code == "PUBLISHED":
                return PublishJob(**{
                    **job.to_dict(),
                    "state": PublishState.PUBLISHED.value,
                })
            elif status_code in ("ERROR", "EXPIRED"):
                return PublishJob(**{
                    **job.to_dict(),
                    "state": PublishState.ERROR.value,
                    "error_message": f"Instagram container status: {status_code}",
                })
            return job

        except Exception as e:
            logger.warning("Instagram poll_status error: %s", e)
            return job


class YouTubeAdapter(BaseAdapter):
    """YouTube Data API v3 adapter.

    Uses resumable upload for video files. Supports Shorts and standard videos.
    Requires: Google Cloud project with YouTube Data API enabled,
    OAuth 2.0 credentials with youtube.upload scope.

    Upload flow (resumable):
      1. POST /upload/youtube/v3/videos?uploadType=resumable → get upload_url
      2. PUT chunks to upload_url with Content-Range headers
      3. On completion, response contains video resource with id
      4. Poll GET /youtube/v3/videos?id={id}&part=status for processing
    """

    PLATFORM = "youtube"
    UPLOAD_INIT_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
    DATA_API_URL = "https://www.googleapis.com/youtube/v3/videos"
    CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB chunks (Google recommends multiples of 256KB)
    MAX_POLL_ATTEMPTS = 30
    POLL_INTERVAL = 10  # seconds between status polls

    async def check_connection(self) -> PublishState:
        """Check YouTube connection via OAuthManager (auto-refreshes expired tokens)."""
        from src.publishing.oauth import OAuthManager

        manager = OAuthManager(self.data_root)
        creds = manager.load_credentials(self.profile_id, "youtube", auto_refresh=True)

        if creds is None:
            return PublishState.AUTH_REQUIRED
        if creds.is_expired:
            return PublishState.TOKEN_EXPIRED
        if not creds.access_token:
            return PublishState.AUTH_REQUIRED
        return PublishState.CONNECTED

    async def _get_access_token(self) -> Optional[str]:
        """Get a valid access token, refreshing if needed."""
        from src.publishing.oauth import OAuthManager

        manager = OAuthManager(self.data_root)
        creds = manager.load_credentials(self.profile_id, "youtube", auto_refresh=True)

        if creds is None or creds.is_expired or not creds.access_token:
            return None
        return creds.access_token

    async def upload(self, job: PublishJob) -> PublishJob:
        """Real YouTube resumable upload via httpx."""
        import os
        import httpx

        access_token = await self._get_access_token()
        if not access_token:
            state = await self.check_connection()
            return PublishJob(**{
                **job.to_dict(),
                "state": state.value,
                "error_message": f"YouTube not connected: {state.value}",
            })

        video_path = Path(job.video_path)
        if not video_path.exists():
            return PublishJob(**{
                **job.to_dict(),
                "state": PublishState.ERROR.value,
                "error_message": f"Video file not found: {job.video_path}",
            })

        file_size = video_path.stat().st_size
        logger.info(
            "YouTube resumable upload starting: %s (%.1f MB)",
            job.title[:40], file_size / 1_048_576,
        )

        # --- Step 1: Initiate resumable upload ---
        body = {
            "snippet": {
                "title": (job.title or "Untitled")[:100],
                "description": (job.description or "")[:5000],
                "tags": list(job.hashtags[:30]) if job.hashtags else [],
                "categoryId": "20",  # Gaming
            },
            "status": {
                "privacyStatus": job.privacy or "public",
                "selfDeclaredMadeForKids": False,
            },
        }

        # Add scheduled publish time if specified
        if job.scheduled_at and job.scheduled_at > time.time():
            import datetime
            dt = datetime.datetime.fromtimestamp(job.scheduled_at, tz=datetime.timezone.utc)
            body["status"]["publishAt"] = dt.isoformat()
            body["status"]["privacyStatus"] = "private"  # Required for scheduled videos

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                init_resp = await client.post(
                    self.UPLOAD_INIT_URL,
                    params={"uploadType": "resumable", "part": "snippet,status"},
                    json=body,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json; charset=UTF-8",
                        "X-Upload-Content-Type": "video/mp4",
                        "X-Upload-Content-Length": str(file_size),
                    },
                )

            if init_resp.status_code != 200:
                error_msg = init_resp.text[:300]
                if init_resp.status_code == 401:
                    return PublishJob(**{
                        **job.to_dict(),
                        "state": PublishState.TOKEN_EXPIRED.value,
                        "error_message": f"YouTube auth expired during upload init: {error_msg}",
                    })
                if init_resp.status_code == 403:
                    return PublishJob(**{
                        **job.to_dict(),
                        "state": PublishState.PERMISSION_REQUIRED.value,
                        "error_message": f"YouTube API permission denied: {error_msg}",
                    })
                return PublishJob(**{
                    **job.to_dict(),
                    "state": PublishState.ERROR.value,
                    "error_message": f"Upload init failed (HTTP {init_resp.status_code}): {error_msg}",
                })

            upload_url = init_resp.headers.get("location")
            if not upload_url:
                return PublishJob(**{
                    **job.to_dict(),
                    "state": PublishState.ERROR.value,
                    "error_message": "Upload init succeeded but no Location header returned",
                })

            logger.info("YouTube resumable upload session created for %s", job.title[:40])

        except Exception as e:
            logger.error("YouTube upload init error: %s", e)
            return PublishJob(**{
                **job.to_dict(),
                "state": PublishState.ERROR.value,
                "error_message": f"Network error during upload init: {str(e)[:200]}",
            })

        # --- Step 2: Upload video in chunks ---
        uploaded = 0
        max_retries = 5

        try:
            with open(video_path, "rb") as f:
                while uploaded < file_size:
                    chunk_end = min(uploaded + self.CHUNK_SIZE, file_size)
                    chunk_size = chunk_end - uploaded
                    chunk = f.read(chunk_size)

                    content_range = f"bytes {uploaded}-{chunk_end - 1}/{file_size}"

                    retry_count = 0
                    while retry_count < max_retries:
                        try:
                            async with httpx.AsyncClient(timeout=120) as client:
                                put_resp = await client.put(
                                    upload_url,
                                    content=chunk,
                                    headers={
                                        "Content-Range": content_range,
                                        "Content-Type": "video/mp4",
                                    },
                                )

                            # 308 = Resume Incomplete (more chunks expected)
                            # 200/201 = Upload complete
                            if put_resp.status_code in (200, 201):
                                # Upload complete — parse response
                                result_data = put_resp.json()
                                video_id = result_data.get("id", "")
                                permalink = f"https://www.youtube.com/watch?v={video_id}" if video_id else None

                                logger.info(
                                    "YouTube upload complete: %s → %s",
                                    job.title[:40], video_id,
                                )

                                return PublishJob(**{
                                    **job.to_dict(),
                                    "state": PublishState.PROCESSING.value,
                                    "platform_post_id": video_id,
                                    "permalink": permalink,
                                })

                            elif put_resp.status_code == 308:
                                # Chunk accepted, continue
                                uploaded = chunk_end
                                break  # Exit retry loop, continue outer while

                            elif put_resp.status_code == 401:
                                return PublishJob(**{
                                    **job.to_dict(),
                                    "state": PublishState.TOKEN_EXPIRED.value,
                                    "error_message": "Token expired during chunk upload",
                                })

                            else:
                                retry_count += 1
                                if retry_count >= max_retries:
                                    return PublishJob(**{
                                        **job.to_dict(),
                                        "state": PublishState.ERROR.value,
                                        "error_message": f"Chunk upload failed after {max_retries} retries (HTTP {put_resp.status_code})",
                                    })
                                await asyncio.sleep(2 ** retry_count)

                        except Exception as e:
                            retry_count += 1
                            if retry_count >= max_retries:
                                return PublishJob(**{
                                    **job.to_dict(),
                                    "state": PublishState.ERROR.value,
                                    "error_message": f"Chunk upload network error after {max_retries} retries: {str(e)[:200]}",
                                })
                            await asyncio.sleep(2 ** retry_count)

        except Exception as e:
            logger.error("YouTube chunk upload error: %s", e)
            return PublishJob(**{
                **job.to_dict(),
                "state": PublishState.ERROR.value,
                "error_message": f"File read error during upload: {str(e)[:200]}",
            })

        # Should not reach here, but safety net
        return PublishJob(**{
            **job.to_dict(),
            "state": PublishState.ERROR.value,
            "error_message": "Upload completed without receiving video ID from YouTube",
        })

    async def poll_status(self, job: PublishJob) -> PublishJob:
        """Poll YouTube Data API for video processing status."""
        import httpx

        if job.state == PublishState.PUBLISHED.value:
            return job

        video_id = job.platform_post_id
        if not video_id:
            return job

        access_token = await self._get_access_token()
        if not access_token:
            logger.warning("Cannot poll YouTube status: no valid access token")
            return job

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    self.DATA_API_URL,
                    params={"id": video_id, "part": "status,snippet"},
                    headers={"Authorization": f"Bearer {access_token}"},
                )

            if resp.status_code != 200:
                logger.warning("YouTube status poll failed (HTTP %d) for %s", resp.status_code, video_id)
                return job

            data = resp.json()
            items = data.get("items", [])
            if not items:
                logger.warning("YouTube video %s not found in API response", video_id)
                return job

            video = items[0]
            status = video.get("status", {})
            upload_status = status.get("uploadStatus", "")
            privacy = status.get("privacyStatus", "")

            # uploadStatus: uploaded, processed, rejected, failed, deleted
            if upload_status == "processed":
                logger.info("YouTube video %s fully processed and published", video_id)
                return PublishJob(**{
                    **job.to_dict(),
                    "state": PublishState.PUBLISHED.value,
                    "permalink": f"https://www.youtube.com/watch?v={video_id}",
                })
            elif upload_status == "rejected":
                reason = status.get("rejectionReason", "unknown")
                return PublishJob(**{
                    **job.to_dict(),
                    "state": PublishState.ERROR.value,
                    "error_message": f"YouTube rejected video: {reason}",
                })
            elif upload_status == "failed":
                reason = status.get("failureReason", "unknown")
                return PublishJob(**{
                    **job.to_dict(),
                    "state": PublishState.ERROR.value,
                    "error_message": f"YouTube processing failed: {reason}",
                })
            elif upload_status == "deleted":
                return PublishJob(**{
                    **job.to_dict(),
                    "state": PublishState.ERROR.value,
                    "error_message": "Video was deleted on YouTube",
                })
            else:
                # Still processing or uploaded
                logger.debug("YouTube video %s status: %s", video_id, upload_status)
                return PublishJob(**{
                    **job.to_dict(),
                    "state": PublishState.PROCESSING.value,
                })

        except Exception as e:
            logger.warning("YouTube status poll error for %s: %s", video_id, e)
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
        """Upload video via TikTok Content Posting API v2.

        Flow: init publish → upload video bytes → poll status.
        Requires approved app with video.publish + video.upload scopes.
        Falls back to PERMISSION_REQUIRED if app not yet approved.
        """
        state = await self.check_connection()
        if state != PublishState.CONNECTED:
            return PublishJob(**{
                **job.to_dict(),
                "state": state.value,
                "error_message": f"TikTok not connected: {state.value}",
            })

        token_path = self.credentials_dir / "tiktok_token.json"
        try:
            token_data = json.loads(token_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return PublishJob(**{**job.to_dict(), "state": PublishState.ERROR.value, "error_message": "Cannot read TikTok token"})

        access_token = token_data.get("access_token", "")
        video_path = Path(job.video_path) if job.video_path else None

        if not video_path or not video_path.exists():
            return PublishJob(**{**job.to_dict(), "state": PublishState.ERROR.value, "error_message": f"Video file not found: {job.video_path}"})

        file_size = video_path.stat().st_size
        chunk_size = min(file_size, 10 * 1024 * 1024)  # max 10MB per chunk

        # Step 1: Init publish
        init_url = "https://open.tiktokapis.com/v2/post/publish/content/init/"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

        caption = job.description or ""
        if job.hashtags:
            tag_str = " ".join(f"#{t}" for t in job.hashtags[:30])
            caption = f"{caption} {tag_str}".strip()

        init_body = {
            "post_info": {
                "title": caption[:150],
                "description": caption[:2200],
                "privacy_level": "SELF_ONLY",  # Safe default; change to PUBLIC when app approved
                "disable_comment": False,
                "disable_duet": False,
                "disable_stitch": False,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": chunk_size,
                "total_chunk_count": max(1, (file_size + chunk_size - 1) // chunk_size),
            },
        }

        import httpx
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                init_resp = await client.post(init_url, json=init_body, headers=headers)
                init_data = init_resp.json()

            if init_resp.status_code != 200 or init_data.get("data", {}).get("publish_id") is None:
                error_msg = init_data.get("error", {}).get("message", str(init_data))
                # App not approved → fall back gracefully
                if "not_authorized" in error_msg.lower() or "permission" in error_msg.lower():
                    return PublishJob(**{
                        **job.to_dict(),
                        "state": PublishState.PERMISSION_REQUIRED.value,
                        "error_message": f"TikTok app not approved for Direct Post: {error_msg}",
                    })
                return PublishJob(**{**job.to_dict(), "state": PublishState.ERROR.value, "error_message": f"Init failed: {error_msg}"})

            publish_id = init_data["data"]["publish_id"]
            upload_url = init_data["data"].get("upload_url", "")

            if not upload_url:
                return PublishJob(**{**job.to_dict(), "state": PublishState.ERROR.value, "error_message": "No upload_url in init response"})

            # Step 2: Upload video bytes
            upload_headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "video/mp4",
                "Content-Length": str(file_size),
            }

            async with httpx.AsyncClient(timeout=120) as client:
                with open(video_path, "rb") as f:
                    upload_resp = await client.put(upload_url, content=f.read(), headers=upload_headers)

            if upload_resp.status_code not in (200, 201):
                return PublishJob(**{
                    **job.to_dict(),
                    "state": PublishState.ERROR.value,
                    "error_message": f"Upload failed: HTTP {upload_resp.status_code}",
                    "remote_id": publish_id,
                })

            logger.info("TikTok upload complete: publish_id=%s", publish_id)
            return PublishJob(**{
                **job.to_dict(),
                "state": PublishState.PROCESSING.value,
                "remote_id": publish_id,
                "published_url": "",  # Available after processing
            })

        except Exception as e:
            logger.error("TikTok upload error: %s", e)
            return PublishJob(**{**job.to_dict(), "state": PublishState.ERROR.value, "error_message": str(e)[:200]})

    async def poll_status(self, job: PublishJob) -> PublishJob:
        """Poll TikTok publish status via /v2/post/publish/status/fetch/."""
        if job.state == PublishState.PUBLISHED.value:
            return job
        if not job.remote_id:
            return job

        token_path = self.credentials_dir / "tiktok_token.json"
        if not token_path.exists():
            return job

        try:
            token_data = json.loads(token_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return job

        access_token = token_data.get("access_token", "")
        status_url = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }
        body = {"publish_id": job.remote_id}

        import httpx
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(status_url, json=body, headers=headers)
                data = resp.json()

            status_data = data.get("data", {})
            status = status_data.get("status", "")
            fail_reason = status_data.get("fail_reason", "")

            if status == "PUBLISH_COMPLETE":
                item_id = status_data.get("item_id", "")
                published_url = f"https://www.tiktok.com/@user/video/{item_id}" if item_id else ""
                return PublishJob(**{
                    **job.to_dict(),
                    "state": PublishState.PUBLISHED.value,
                    "published_url": published_url,
                    "remote_id": job.remote_id,
                })
            elif status == "FAILED":
                return PublishJob(**{
                    **job.to_dict(),
                    "state": PublishState.ERROR.value,
                    "error_message": f"TikTok publish failed: {fail_reason}",
                    "remote_id": job.remote_id,
                })
            # SEND_TO_USER_INBOX, PROCESSING_DOWNLOAD, etc. → still processing
            return job

        except Exception as e:
            logger.warning("TikTok poll_status error: %s", e)
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