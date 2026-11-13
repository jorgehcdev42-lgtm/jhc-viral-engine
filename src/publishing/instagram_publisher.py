"""Instagram Reels publisher via Content Publishing API.

Implements the 3-step flow: create container → poll status → publish.
Requires Instagram Business account + approved app permissions.

Specs enforced:
- MP4/MOV, H.264/HEVC, AAC audio
- 9:16 aspect ratio (1080x1920)
- 5-90 seconds for Reels tab eligibility
- Max 100MB file size
- Video must be publicly accessible URL or use resumable upload

Permissions needed:
- instagram_business_basic
- instagram_business_content_publish

Rate limit: 100 API-published posts per rolling 24h window.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

import httpx

from src.core.profile_config import ProfileConfig

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v27.0"
BASE_URL = "https://graph.instagram.com"
MAX_POLL_ATTEMPTS = 5
POLL_INTERVAL_SECONDS = 60


class ContainerStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    FINISHED = "FINISHED"
    PUBLISHED = "PUBLISHED"
    EXPIRED = "EXPIRED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class PublishResult:
    success: bool
    media_id: Optional[str] = None
    error: Optional[str] = None
    container_status: Optional[str] = None


class InstagramPublisher:
    """Publish Reels to Instagram via Content Publishing API."""

    def __init__(self, profile: ProfileConfig) -> None:
        self.profile = profile
        self.access_token = profile.publishing.access_token
        self.ig_user_id = profile.publishing.instagram_account_id

    async def publish_reel(
        self,
        video_url: str,
        caption: str,
        cover_url: Optional[str] = None,
        share_to_feed: bool = True,
        is_ai_generated: bool = False,
    ) -> PublishResult:
        """Full 3-step publish flow for a Reel."""
        if not self.access_token or not self.ig_user_id:
            return PublishResult(
                success=False,
                error="Instagram credentials not configured. Set instagram_account_id and access_token in profile config.",
            )

        # Step 1: Create container
        container_id = await self._create_container(
            video_url=video_url,
            caption=caption,
            cover_url=cover_url,
            share_to_feed=share_to_feed,
            is_ai_generated=is_ai_generated,
        )
        if not container_id:
            return PublishResult(success=False, error="Failed to create media container")

        # Step 2: Poll until FINISHED
        status = await self._poll_container_status(container_id)
        if status != ContainerStatus.FINISHED:
            return PublishResult(
                success=False,
                error=f"Container not ready: status={status.value}",
                container_status=status.value,
            )

        # Step 3: Publish
        media_id = await self._publish_container(container_id)
        if not media_id:
            return PublishResult(success=False, error="Failed to publish container")

        logger.info("Reel published successfully: media_id=%s", media_id)
        return PublishResult(success=True, media_id=media_id)

    async def check_rate_limit(self) -> dict:
        """Check current publishing rate limit usage."""
        url = f"{BASE_URL}/{GRAPH_API_VERSION}/{self.ig_user_id}/content_publishing_limit"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params={"access_token": self.access_token})
            return resp.json()

    async def _create_container(
        self,
        video_url: str,
        caption: str,
        cover_url: Optional[str],
        share_to_feed: bool,
        is_ai_generated: bool,
    ) -> Optional[str]:
        """Step 1: Create REELS media container."""
        url = f"{BASE_URL}/{GRAPH_API_VERSION}/{self.ig_user_id}/media"
        payload: dict = {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "share_to_feed": str(share_to_feed).lower(),
            "access_token": self.access_token,
        }
        if cover_url:
            payload["cover_url"] = cover_url
        if is_ai_generated:
            payload["is_ai_generated"] = "true"

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload)
            data = resp.json()
            if "id" in data:
                logger.info("Container created: %s", data["id"])
                return data["id"]
            logger.error("Container creation failed: %s", data)
            return None

    async def _poll_container_status(self, container_id: str) -> ContainerStatus:
        """Step 2: Poll container until FINISHED or terminal state."""
        url = f"{BASE_URL}/{GRAPH_API_VERSION}/{container_id}"
        for attempt in range(MAX_POLL_ATTEMPTS):
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    url,
                    params={"fields": "status_code", "access_token": self.access_token},
                )
                data = resp.json()
                status_code = data.get("status_code", "UNKNOWN")
                logger.debug(
                    "Poll %d/%d: container=%s status=%s",
                    attempt + 1, MAX_POLL_ATTEMPTS, container_id, status_code,
                )
                try:
                    status = ContainerStatus(status_code)
                except ValueError:
                    status = ContainerStatus.IN_PROGRESS

                if status in (ContainerStatus.FINISHED, ContainerStatus.ERROR, ContainerStatus.EXPIRED):
                    return status

            await asyncio.sleep(POLL_INTERVAL_SECONDS)

        return ContainerStatus.IN_PROGRESS

    async def _publish_container(self, container_id: str) -> Optional[str]:
        """Step 3: Publish the finished container."""
        url = f"{BASE_URL}/{GRAPH_API_VERSION}/{self.ig_user_id}/media_publish"
        payload = {
            "creation_id": container_id,
            "access_token": self.access_token,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload)
            data = resp.json()
            if "id" in data:
                return data["id"]
            logger.error("Publish failed: %s", data)
            return None