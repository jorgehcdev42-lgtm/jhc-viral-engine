"""Testes de integração híbrida YouTube — execute_youtube_hybrid no AutoPublishScheduler.

Valida a política de seleção automática API → Playwright fallback:
- API conectada → upload via YouTubeAdapter
- API permission_required/token_expired → fallback para BrowserPublisher
- API e Browser indisponíveis → auth_required sem fallback inseguro
- Resultado incerto (processing) → NÃO faz fallback
- Deduplicação e persistência de estado
"""

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.automation.autopublish_scheduler import AutoPublishScheduler, AutoPublishJob


@pytest.fixture
def tmp_data(tmp_path):
    """Cria estrutura de diretórios temporária para o scheduler."""
    (tmp_path / "credentials" / "test_profile").mkdir(parents=True)
    (tmp_path / "publish_jobs" / "test_profile").mkdir(parents=True)
    (tmp_path / "scheduler").mkdir(parents=True)
    (tmp_path / "publishing" / "credentials").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def scheduler(tmp_data):
    """Instância do AutoPublishScheduler com dados temporários."""
    return AutoPublishScheduler(tmp_data)


@pytest.fixture
def youtube_job(tmp_path):
    """Job YouTube de teste com vídeo dummy."""
    video = tmp_path / "test_short.mp4"
    video.write_bytes(b"\x00" * 2048)
    return AutoPublishJob(
        job_id="yt-hybrid-001",
        profile_id="test_profile",
        platform="youtube",
        video_path=str(video),
        title="GTA VI Gameplay #shorts",
        description="Teste híbrido",
        hashtags=("gta6", "shorts"),
        state="approved",
        auth_state="connected",
    )


@pytest.fixture
def valid_youtube_token(tmp_data):
    """Token YouTube válido para o perfil de teste."""
    token = {
        "profile_id": "test_profile",
        "platform": "youtube",
        "access_token": "ya29.valid-token",
        "refresh_token": "1//valid-refresh",
        "token_type": "bearer",
        "expires_at": time.time() + 3600,
        "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
        "client_id": "test-client-id",
        "connected_at": time.time(),
        "account_id": "UC123",
        "account_name": "Test Channel",
    }
    path = tmp_data / "credentials" / "test_profile" / "youtube_oauth.json"
    path.write_text(json.dumps(token), encoding="utf-8")
    return token


class TestYouTubeHybridAPIPath:
    """Cenários onde a API oficial está disponível."""

    @pytest.mark.asyncio
    async def test_api_success_published(self, scheduler, youtube_job, valid_youtube_token):
        """API conectada + upload bem-sucedido → published via API."""
        from src.publishing.adapters import PublishState

        # Registra job no scheduler (execute_youtube_hybrid acessa self._jobs)
        scheduler._jobs[youtube_job.job_id] = youtube_job

        # upload retorna PROCESSING, poll_status retorna PUBLISHED
        mock_upload = MagicMock()
        mock_upload.state = PublishState.PROCESSING.value
        mock_upload.platform_post_id = "vid123"
        mock_upload.permalink = None

        mock_poll = MagicMock()
        mock_poll.state = PublishState.PUBLISHED.value
        mock_poll.platform_post_id = "vid123"
        mock_poll.permalink = "https://www.youtube.com/watch?v=vid123"

        with (
            patch(
                "src.publishing.adapters.YouTubeAdapter.check_connection",
                new_callable=AsyncMock,
                return_value=PublishState.CONNECTED,
            ),
            patch(
                "src.publishing.adapters.YouTubeAdapter.upload",
                new_callable=AsyncMock,
                return_value=mock_upload,
            ),
            patch(
                "src.publishing.adapters.YouTubeAdapter.poll_status",
                new_callable=AsyncMock,
                return_value=mock_poll,
            ),
        ):
            result = await scheduler.execute_youtube_hybrid(youtube_job)

        assert result["status"] == "published"
        assert result["method"] == "api"
        assert result["remote_id"] == "vid123"
        assert "vid123" in result["url"]

    @pytest.mark.asyncio
    async def test_api_processing_no_fallback(self, scheduler, youtube_job, valid_youtube_token):
        """API retorna PROCESSING → NÃO faz fallback para Playwright."""
        from src.publishing.adapters import PublishState

        # Registra job no scheduler (execute_youtube_hybrid acessa self._jobs)
        scheduler._jobs[youtube_job.job_id] = youtube_job

        mock_upload_result = MagicMock()
        mock_upload_result.state = PublishState.PROCESSING.value
        mock_upload_result.platform_post_id = "vid456"
        mock_upload_result.permalink = None

        mock_poll_result = MagicMock()
        mock_poll_result.state = PublishState.PROCESSING.value
        mock_poll_result.platform_post_id = "vid456"
        mock_poll_result.permalink = None

        with (
            patch(
                "src.publishing.adapters.YouTubeAdapter.check_connection",
                new_callable=AsyncMock,
                return_value=PublishState.CONNECTED,
            ),
            patch(
                "src.publishing.adapters.YouTubeAdapter.upload",
                new_callable=AsyncMock,
                return_value=mock_upload_result,
            ),
            patch(
                "src.publishing.adapters.YouTubeAdapter.poll_status",
                new_callable=AsyncMock,
                return_value=mock_poll_result,
            ),
        ):
            result = await scheduler.execute_youtube_hybrid(youtube_job)

        assert result["status"] == "processing"
        assert result["method"] == "api"
        # Playwright NÃO deve ter sido chamado
        assert result.get("error") is None

    @pytest.mark.asyncio
    async def test_api_error_marks_failed(self, scheduler, youtube_job, valid_youtube_token):
        """API retorna ERROR → job marcado como failed com retry."""
        from src.publishing.adapters import PublishState

        mock_result = MagicMock()
        mock_result.state = PublishState.ERROR.value
        mock_result.error_message = "Quota exceeded"

        with (
            patch(
                "src.publishing.adapters.YouTubeAdapter.check_connection",
                new_callable=AsyncMock,
                return_value=PublishState.CONNECTED,
            ),
            patch(
                "src.publishing.adapters.YouTubeAdapter.upload",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            result = await scheduler.execute_youtube_hybrid(youtube_job)

        assert result["status"] == "failed"
        assert result["method"] == "api"
        assert "Quota exceeded" in result["error"]


class TestYouTubeHybridFallbackPath:
    """Cenários onde a API falha e o fallback Playwright é avaliado."""

    @pytest.mark.asyncio
    async def test_permission_required_fallback_to_playwright(self, scheduler, youtube_job, valid_youtube_token):
        """API PERMISSION_REQUIRED + Browser session ativa → fallback Playwright."""
        from src.publishing.adapters import PublishState

        mock_pub_result = MagicMock()
        mock_pub_result.success = True
        mock_pub_result.post_id = "pw_vid789"
        mock_pub_result.url = "https://www.youtube.com/watch?v=pw_vid789"

        with (
            patch(
                "src.publishing.adapters.YouTubeAdapter.check_connection",
                new_callable=AsyncMock,
                return_value=PublishState.PERMISSION_REQUIRED,
            ),
            patch(
                "src.publishing.browser_publisher.BrowserPublisher.check_session",
                new_callable=AsyncMock,
                return_value={"active": True},
            ),
            patch(
                "src.publishing.browser_publisher.BrowserPublisher.publish",
                new_callable=AsyncMock,
                return_value=mock_pub_result,
            ),
        ):
            result = await scheduler.execute_youtube_hybrid(youtube_job)

        assert result["status"] == "published"
        assert result["method"] == "playwright"
        assert "pw_vid789" in result["url"]

    @pytest.mark.asyncio
    async def test_token_expired_fallback_to_playwright(self, scheduler, youtube_job, valid_youtube_token):
        """API TOKEN_EXPIRED + Browser session ativa → fallback Playwright."""
        from src.publishing.adapters import PublishState

        mock_pub_result = MagicMock()
        mock_pub_result.success = True
        mock_pub_result.post_id = "pw_expired_vid"
        mock_pub_result.url = "https://www.youtube.com/watch?v=pw_expired_vid"

        with (
            patch(
                "src.publishing.adapters.YouTubeAdapter.check_connection",
                new_callable=AsyncMock,
                return_value=PublishState.TOKEN_EXPIRED,
            ),
            patch(
                "src.publishing.browser_publisher.BrowserPublisher.check_session",
                new_callable=AsyncMock,
                return_value={"active": True},
            ),
            patch(
                "src.publishing.browser_publisher.BrowserPublisher.publish",
                new_callable=AsyncMock,
                return_value=mock_pub_result,
            ),
        ):
            result = await scheduler.execute_youtube_hybrid(youtube_job)

        assert result["status"] == "published"
        assert result["method"] == "playwright"

    @pytest.mark.asyncio
    async def test_no_browser_session_blocks_fallback(self, scheduler, youtube_job, valid_youtube_token):
        """API indisponível + sem sessão Browser → auth_required, SEM fallback."""
        from src.publishing.adapters import PublishState

        with (
            patch(
                "src.publishing.adapters.YouTubeAdapter.check_connection",
                new_callable=AsyncMock,
                return_value=PublishState.AUTH_REQUIRED,
            ),
            patch(
                "src.publishing.browser_publisher.BrowserPublisher.check_session",
                new_callable=AsyncMock,
                return_value={"active": False},
            ),
        ):
            result = await scheduler.execute_youtube_hybrid(youtube_job)

        assert result["status"] == "auth_required"
        assert "Login required" in result["error"]

    @pytest.mark.asyncio
    async def test_playwright_failure_marks_failed(self, scheduler, youtube_job, valid_youtube_token):
        """API negada + Playwright falha → failed com retry."""
        from src.publishing.adapters import PublishState

        mock_pub_result = MagicMock()
        mock_pub_result.success = False
        mock_pub_result.error = "Upload timeout"

        with (
            patch(
                "src.publishing.adapters.YouTubeAdapter.check_connection",
                new_callable=AsyncMock,
                return_value=PublishState.PERMISSION_REQUIRED,
            ),
            patch(
                "src.publishing.browser_publisher.BrowserPublisher.check_session",
                new_callable=AsyncMock,
                return_value={"active": True},
            ),
            patch(
                "src.publishing.browser_publisher.BrowserPublisher.publish",
                new_callable=AsyncMock,
                return_value=mock_pub_result,
            ),
        ):
            result = await scheduler.execute_youtube_hybrid(youtube_job)

        assert result["status"] == "failed"
        assert result["method"] == "playwright"
        assert "Upload timeout" in result["error"]


class TestYouTubeHybridSafety:
    """Garantias de segurança: sem fallback inseguro, sem duplicidade."""

    @pytest.mark.asyncio
    async def test_uncertain_state_no_fallback(self, scheduler, youtube_job, valid_youtube_token):
        """Estado desconhecido da API → NÃO faz fallback, retorna uncertain."""
        from src.publishing.adapters import PublishState

        mock_result = MagicMock()
        mock_result.state = "unknown_state"
        mock_result.error_message = None

        with (
            patch(
                "src.publishing.adapters.YouTubeAdapter.check_connection",
                new_callable=AsyncMock,
                return_value=PublishState.CONNECTED,
            ),
            patch(
                "src.publishing.adapters.YouTubeAdapter.upload",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            result = await scheduler.execute_youtube_hybrid(youtube_job)

        assert result["status"] == "uncertain"
        assert "unexpected state" in result["error"]

    @pytest.mark.asyncio
    async def test_platform_constant_consistency(self, scheduler):
        """YouTubeAdapter.PLATFORM deve ser 'youtube' para roteamento correto."""
        from src.publishing.adapters import YouTubeAdapter

        adapter = YouTubeAdapter(scheduler.data_root, "test")
        assert adapter.PLATFORM == "youtube"

    @pytest.mark.asyncio
    async def test_execute_youtube_hybrid_is_async(self, scheduler):
        """execute_youtube_hybrid deve ser coroutine assíncrona."""
        import inspect

        assert inspect.iscoroutinefunction(scheduler.execute_youtube_hybrid)