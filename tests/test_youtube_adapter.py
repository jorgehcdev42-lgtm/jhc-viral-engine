"""Unit tests for YouTubeAdapter — resumable upload, poll_status, and OAuth integration.

Tests use mocked HTTP responses (no real API calls). Validates:
- check_connection with valid/expired/missing tokens
- upload init + chunked transfer + error handling
- poll_status for all YouTube processing states
- Token refresh integration via OAuthManager
"""

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.publishing.adapters import YouTubeAdapter, PublishJob, PublishState


@pytest.fixture
def tmp_data(tmp_path):
    """Create a temporary data directory structure."""
    profile_dir = tmp_path / "credentials" / "test_profile"
    profile_dir.mkdir(parents=True)
    jobs_dir = tmp_path / "publish_jobs" / "test_profile"
    jobs_dir.mkdir(parents=True)
    return tmp_path


@pytest.fixture
def adapter(tmp_data):
    """Create a YouTubeAdapter instance with temp directories."""
    return YouTubeAdapter(tmp_data, "test_profile")


@pytest.fixture
def sample_job(tmp_path):
    """Create a sample PublishJob with a dummy video file."""
    video = tmp_path / "test_video.mp4"
    video.write_bytes(b"\x00" * 1024)  # 1KB dummy file
    return PublishJob(
        job_id="test-job-001",
        profile_id="test_profile",
        platform="youtube",
        video_path=str(video),
        title="Test GTA VI Short",
        description="Amazing gameplay clip #gta6",
        hashtags=("gta6", "gameplay"),
        privacy="public",
        state=PublishState.NOT_CONFIGURED.value,
    )


@pytest.fixture
def valid_token(tmp_data):
    """Write a valid (non-expired) token file."""
    token_data = {
        "profile_id": "test_profile",
        "platform": "youtube",
        "access_token": "ya29.valid-access-token",
        "refresh_token": "1//valid-refresh-token",
        "token_type": "bearer",
        "expires_at": time.time() + 3600,
        "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
        "client_id": "test-client-id",
        "connected_at": time.time(),
        "account_id": "UC123456",
        "account_name": "Test Channel",
    }
    token_path = tmp_data / "credentials" / "test_profile" / "youtube_oauth.json"
    token_path.write_text(json.dumps(token_data), encoding="utf-8")
    return token_data


@pytest.fixture
def expired_token(tmp_data):
    """Write an expired token file with refresh token."""
    token_data = {
        "profile_id": "test_profile",
        "platform": "youtube",
        "access_token": "ya29.expired-access-token",
        "refresh_token": "1//valid-refresh-token",
        "token_type": "bearer",
        "expires_at": time.time() - 3600,  # Expired 1 hour ago
        "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
        "client_id": "test-client-id",
        "connected_at": time.time() - 7200,
        "account_id": "UC123456",
        "account_name": "",
    }
    token_path = tmp_data / "credentials" / "test_profile" / "youtube_oauth.json"
    token_path.write_text(json.dumps(token_data), encoding="utf-8")
    return token_data


# --- check_connection tests ---


class TestCheckConnection:
    @pytest.mark.asyncio
    async def test_connected_with_valid_token(self, adapter, valid_token):
        state = await adapter.check_connection()
        assert state == PublishState.CONNECTED

    @pytest.mark.asyncio
    async def test_auth_required_when_no_token(self, adapter):
        state = await adapter.check_connection()
        assert state == PublishState.AUTH_REQUIRED

    @pytest.mark.asyncio
    async def test_token_expired(self, adapter, expired_token):
        """Expired token should trigger auto-refresh via OAuthManager.
        Since we can't hit Google in tests, it will remain expired."""
        with patch("src.publishing.oauth.OAuthManager.refresh_token_if_needed") as mock_refresh:
            # Simulate refresh failing (returns same expired creds)
            from src.publishing.oauth import OAuthCredentials

            mock_refresh.return_value = OAuthCredentials(
                profile_id="test_profile",
                platform="youtube",
                access_token="ya29.expired",
                refresh_token="1//refresh",
                expires_at=time.time() - 3600,
            )
            state = await adapter.check_connection()
            assert state == PublishState.TOKEN_EXPIRED

    @pytest.mark.asyncio
    async def test_corrupt_token_file(self, adapter, tmp_data):
        token_path = tmp_data / "credentials" / "test_profile" / "youtube_oauth.json"
        token_path.write_text("{invalid json", encoding="utf-8")
        state = await adapter.check_connection()
        assert state == PublishState.AUTH_REQUIRED


# --- upload tests ---


class TestUpload:
    @pytest.mark.asyncio
    async def test_upload_no_credentials(self, adapter, sample_job):
        result = await adapter.upload(sample_job)
        assert result.state in (
            PublishState.AUTH_REQUIRED.value,
            PublishState.TOKEN_EXPIRED.value,
        )

    @pytest.mark.asyncio
    async def test_upload_missing_video_file(self, adapter, valid_token, tmp_path):
        job = PublishJob(
            job_id="test-missing",
            profile_id="test_profile",
            platform="youtube",
            video_path="/nonexistent/video.mp4",
            title="Missing Video",
            description="Test",
            state=PublishState.NOT_CONFIGURED.value,
        )
        result = await adapter.upload(job)
        assert result.state == PublishState.ERROR.value
        assert "not found" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_upload_init_failure_403(self, adapter, valid_token, sample_job):
        """Simulate 403 permission denied during upload init."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Access Not Configured: YouTube Data API has not been used"

        with patch(
            "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response
        ):
            result = await adapter.upload(sample_job)
            assert result.state == PublishState.PERMISSION_REQUIRED.value

    @pytest.mark.asyncio
    async def test_upload_init_failure_401(self, adapter, valid_token, sample_job):
        """Simulate 401 expired token during upload init."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Request had invalid authentication credentials"

        with patch(
            "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response
        ):
            result = await adapter.upload(sample_job)
            assert result.state == PublishState.TOKEN_EXPIRED.value

    @pytest.mark.asyncio
    async def test_upload_success_full_flow(self, adapter, valid_token, sample_job):
        """Simulate successful resumable upload: init → single chunk → completion.

        sample_job is 1KB which fits in one chunk (< CHUNK_SIZE), so only one
        PUT call occurs and it must return 201 with the video ID directly.
        """
        # Mock init response (returns Location header)
        init_response = MagicMock()
        init_response.status_code = 200
        init_response.headers = {"location": "https://upload.youtube.com/resumable/session123"}

        # Single chunk completes the upload (file < CHUNK_SIZE)
        final_response = MagicMock(
            status_code=201,
            json=MagicMock(return_value={"id": "dQw4w9WgXcQ"}),
        )

        with (
            patch(
                "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=init_response
            ),
            patch(
                "httpx.AsyncClient.put",
                new_callable=AsyncMock,
                return_value=final_response,
            ),
        ):
            result = await adapter.upload(sample_job)
            assert result.state == PublishState.PROCESSING.value
            assert result.platform_post_id == "dQw4w9WgXcQ"
            assert "dQw4w9WgXcQ" in result.permalink

    @pytest.mark.asyncio
    async def test_upload_no_location_header(self, adapter, valid_token, sample_job):
        """Init succeeds but no Location header → error."""
        init_response = MagicMock()
        init_response.status_code = 200
        init_response.headers = {}

        with patch(
            "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=init_response
        ):
            result = await adapter.upload(sample_job)
            assert result.state == PublishState.ERROR.value
            assert "Location" in result.error_message

    @pytest.mark.asyncio
    async def test_upload_scheduled_video(self, adapter, valid_token, tmp_path):
        """Scheduled videos should set publishAt and privacyStatus=private."""
        video = tmp_path / "scheduled.mp4"
        video.write_bytes(b"\x00" * 512)
        future_time = time.time() + 86400  # Tomorrow
        job = PublishJob(
            job_id="sched-001",
            profile_id="test_profile",
            platform="youtube",
            video_path=str(video),
            title="Scheduled Upload",
            description="Test scheduled",
            scheduled_at=future_time,
            state=PublishState.NOT_CONFIGURED.value,
        )

        init_response = MagicMock()
        init_response.status_code = 200
        init_response.headers = {"location": "https://upload.youtube.com/resumable/sched"}

        final_response = MagicMock(
            status_code=201,
            json=MagicMock(return_value={"id": "schedVideoId"}),
        )

        with (
            patch(
                "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=init_response
            ) as mock_post,
            patch(
                "httpx.AsyncClient.put", new_callable=AsyncMock, return_value=final_response
            ),
        ):
            result = await adapter.upload(job)
            assert result.state == PublishState.PROCESSING.value

            # Verify the init request body included publishAt and private status
            call_kwargs = mock_post.call_args
            body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
            assert body["status"]["privacyStatus"] == "private"
            assert "publishAt" in body["status"]


# --- poll_status tests ---


class TestPollStatus:
    @pytest.mark.asyncio
    async def test_poll_already_published(self, adapter):
        job = PublishJob(
            job_id="pub-001",
            profile_id="test_profile",
            platform="youtube",
            video_path="/dummy.mp4",
            title="Published",
            description="Done",
            state=PublishState.PUBLISHED.value,
            platform_post_id="abc123",
        )
        result = await adapter.poll_status(job)
        assert result.state == PublishState.PUBLISHED.value

    @pytest.mark.asyncio
    async def test_poll_no_video_id(self, adapter):
        job = PublishJob(
            job_id="noid-001",
            profile_id="test_profile",
            platform="youtube",
            video_path="/dummy.mp4",
            title="No ID",
            description="Test",
            state=PublishState.PROCESSING.value,
        )
        result = await adapter.poll_status(job)
        assert result.state == PublishState.PROCESSING.value  # Unchanged

    @pytest.mark.asyncio
    async def test_poll_processed_video(self, adapter, valid_token):
        """Video fully processed → PUBLISHED."""
        job = PublishJob(
            job_id="proc-001",
            profile_id="test_profile",
            platform="youtube",
            video_path="/dummy.mp4",
            title="Processed",
            description="Test",
            state=PublishState.PROCESSING.value,
            platform_post_id="processedVid",
        )

        api_response = MagicMock()
        api_response.status_code = 200
        api_response.json = MagicMock(
            return_value={
                "items": [{"status": {"uploadStatus": "processed", "privacyStatus": "public"}}]
            }
        )

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=api_response):
            result = await adapter.poll_status(job)
            assert result.state == PublishState.PUBLISHED.value
            assert "processedVid" in result.permalink

    @pytest.mark.asyncio
    async def test_poll_rejected_video(self, adapter, valid_token):
        """Video rejected by YouTube → ERROR with reason."""
        job = PublishJob(
            job_id="rej-001",
            profile_id="test_profile",
            platform="youtube",
            video_path="/dummy.mp4",
            title="Rejected",
            description="Test",
            state=PublishState.PROCESSING.value,
            platform_post_id="rejectedVid",
        )

        api_response = MagicMock()
        api_response.status_code = 200
        api_response.json = MagicMock(
            return_value={
                "items": [
                    {
                        "status": {
                            "uploadStatus": "rejected",
                            "rejectionReason": "copyrightViolation",
                        }
                    }
                ]
            }
        )

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=api_response):
            result = await adapter.poll_status(job)
            assert result.state == PublishState.ERROR.value
            assert "copyrightViolation" in result.error_message

    @pytest.mark.asyncio
    async def test_poll_failed_processing(self, adapter, valid_token):
        """Video processing failed → ERROR."""
        job = PublishJob(
            job_id="fail-001",
            profile_id="test_profile",
            platform="youtube",
            video_path="/dummy.mp4",
            title="Failed",
            description="Test",
            state=PublishState.PROCESSING.value,
            platform_post_id="failedVid",
        )

        api_response = MagicMock()
        api_response.status_code = 200
        api_response.json = MagicMock(
            return_value={
                "items": [{"status": {"uploadStatus": "failed", "failureReason": "codecError"}}]
            }
        )

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=api_response):
            result = await adapter.poll_status(job)
            assert result.state == PublishState.ERROR.value
            assert "codecError" in result.error_message

    @pytest.mark.asyncio
    async def test_poll_still_processing(self, adapter, valid_token):
        """Video still uploading/processing → stays PROCESSING."""
        job = PublishJob(
            job_id="wait-001",
            profile_id="test_profile",
            platform="youtube",
            video_path="/dummy.mp4",
            title="Waiting",
            description="Test",
            state=PublishState.PROCESSING.value,
            platform_post_id="pendingVid",
        )

        api_response = MagicMock()
        api_response.status_code = 200
        api_response.json = MagicMock(
            return_value={"items": [{"status": {"uploadStatus": "uploaded"}}]}
        )

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=api_response):
            result = await adapter.poll_status(job)
            assert result.state == PublishState.PROCESSING.value

    @pytest.mark.asyncio
    async def test_poll_api_error_graceful(self, adapter, valid_token):
        """API returns non-200 → job unchanged (graceful degradation)."""
        job = PublishJob(
            job_id="err-001",
            profile_id="test_profile",
            platform="youtube",
            video_path="/dummy.mp4",
            title="Error",
            description="Test",
            state=PublishState.PROCESSING.value,
            platform_post_id="errVid",
        )

        api_response = MagicMock()
        api_response.status_code = 500

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=api_response):
            result = await adapter.poll_status(job)
            assert result.state == PublishState.PROCESSING.value  # Unchanged


# --- Integration: dedup between API and Browser paths ---


class TestHybridDeduplication:
    @pytest.mark.asyncio
    async def test_adapter_platform_constant(self):
        """YouTubeAdapter must declare correct PLATFORM name."""
        adapter = YouTubeAdapter(Path("/tmp"), "test")
        assert adapter.PLATFORM == "youtube"

    @pytest.mark.asyncio
    async def test_check_connection_is_async(self, adapter):
        """check_connection must be an async coroutine."""
        import inspect

        assert inspect.iscoroutinefunction(adapter.check_connection)

    @pytest.mark.asyncio
    async def test_upload_is_async(self, adapter):
        """upload must be an async coroutine."""
        import inspect

        assert inspect.iscoroutinefunction(adapter.upload)

    @pytest.mark.asyncio
    async def test_poll_status_is_async(self, adapter):
        """poll_status must be an async coroutine."""
        import inspect

        assert inspect.iscoroutinefunction(adapter.poll_status)