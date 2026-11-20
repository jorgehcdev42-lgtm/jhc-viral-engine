"""Testes do InstagramAdapter — autenticação, publicação e tratamento de falhas.

Cobre:
- check_connection: token válido, expirado, ausente, corrompido
- upload: fluxo completo com mock da Graph API v21.0
- poll_status: estados FINISHED, IN_PROGRESS, ERROR
- Tratamento de erros de permissão e rede
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.publishing.adapters import (
    InstagramAdapter,
    PublishJob,
    PublishState,
)


@pytest.fixture
def adapter(tmp_path: Path) -> InstagramAdapter:
    """Cria adapter com diretório temporário de credenciais."""
    return InstagramAdapter(data_root=tmp_path, profile_id="test_profile")


@pytest.fixture
def valid_token(adapter: InstagramAdapter) -> Path:
    """Salva token válido no disco."""
    token_data = {
        "access_token": "EAAValidToken123",
        "account_id": "17841479885114087",
        "expires_at": time.time() + 5184000,  # 60 dias
        "scopes": ["instagram_business_basic", "instagram_business_content_publish"],
        "client_id": "1819988955893243",
        "refresh_token": "",
        "token_type": "bearer",
        "connected_at": time.time(),
    }
    token_path = adapter.credentials_dir / "instagram_oauth.json"
    token_path.write_text(json.dumps(token_data), encoding="utf-8")
    return token_path


@pytest.fixture
def expired_token(adapter: InstagramAdapter) -> Path:
    """Salva token expirado no disco."""
    token_data = {
        "access_token": "EAAExpiredToken",
        "account_id": "17841479885114087",
        "expires_at": time.time() - 3600,  # Expirou há 1h
        "scopes": ["instagram_business_basic"],
    }
    token_path = adapter.credentials_dir / "instagram_oauth.json"
    token_path.write_text(json.dumps(token_data), encoding="utf-8")
    return token_path


@pytest.fixture
def sample_job() -> PublishJob:
    """Job de exemplo para testes de upload."""
    return PublishJob(
        job_id="test-job-001",
        profile_id="test_profile",
        platform="instagram",
        video_path="https://example.com/video.mp4",
        title="Test Reel GTA VI",
        description="Novo vídeo sobre GTA VI lançamento",
        hashtags=("gta6", "gtavi", "rockstargames"),
    )


# --- check_connection ---


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
        state = await adapter.check_connection()
        assert state == PublishState.TOKEN_EXPIRED

    @pytest.mark.asyncio
    async def test_error_on_corrupt_json(self, adapter):
        token_path = adapter.credentials_dir / "instagram_oauth.json"
        token_path.write_text("{invalid json", encoding="utf-8")
        state = await adapter.check_connection()
        assert state == PublishState.ERROR

    @pytest.mark.asyncio
    async def test_auth_required_when_empty_access_token(self, adapter):
        token_data = {"access_token": "", "account_id": "123", "expires_at": time.time() + 3600}
        token_path = adapter.credentials_dir / "instagram_oauth.json"
        token_path.write_text(json.dumps(token_data), encoding="utf-8")
        state = await adapter.check_connection()
        assert state == PublishState.AUTH_REQUIRED

    @pytest.mark.asyncio
    async def test_legacy_token_fallback(self, adapter):
        """Verifica fallback para instagram_token.json legado."""
        legacy_data = {
            "access_token": "EAALegacyToken",
            "expires_at": time.time() + 3600,
        }
        legacy_path = adapter.credentials_dir / "instagram_token.json"
        legacy_path.write_text(json.dumps(legacy_data), encoding="utf-8")
        state = await adapter.check_connection()
        assert state == PublishState.CONNECTED


# --- upload ---


class TestUpload:
    @pytest.mark.asyncio
    async def test_upload_returns_auth_required_without_token(self, adapter, sample_job):
        result = await adapter.upload(sample_job)
        assert result.state == PublishState.AUTH_REQUIRED.value
        assert "not connected" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_upload_full_success_flow(self, adapter, valid_token, sample_job):
        """Simula fluxo completo: container → poll → publish."""
        mock_responses = [
            # Step 1: create container
            MagicMock(status_code=200, json=MagicMock(return_value={"id": "container_123"})),
            # Step 2: poll status (FINISHED immediately)
            MagicMock(status_code=200, json=MagicMock(return_value={"status_code": "FINISHED"})),
            # Step 3: publish
            MagicMock(status_code=200, json=MagicMock(return_value={"id": "media_456"})),
        ]

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[mock_responses[0], mock_responses[2]])
        mock_client.get = AsyncMock(return_value=mock_responses[1])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await adapter.upload(sample_job)

        assert result.state == PublishState.PUBLISHED.value
        assert result.platform_post_id == "media_456"
        assert result.permalink is not None

    @pytest.mark.asyncio
    async def test_upload_rejects_missing_local_file(self, adapter, valid_token):
        """Non-existent local files must produce a clear error (VideoHost attempts hosting first)."""
        local_job = PublishJob(
            job_id="j-local", profile_id="test_profile", platform="instagram",
            video_path="/tmp/nonexistent_video.mp4", title="Test", description="",
        )
        result = await adapter.upload(local_job)
        assert result.state == PublishState.ERROR.value
        assert "not found" in result.error_message.lower() or "hosting" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_upload_rejects_empty_video_path(self, adapter, valid_token):
        empty_job = PublishJob(
            job_id="j-empty", profile_id="test_profile", platform="instagram",
            video_path="", title="Test", description="",
        )
        result = await adapter.upload(empty_job)
        assert result.state == PublishState.ERROR.value

    @pytest.mark.asyncio
    async def test_upload_permission_denied(self, adapter, valid_token, sample_job):
        """API retorna erro de permissão → PERMISSION_REQUIRED."""
        error_response = MagicMock(
            status_code=403,
            json=MagicMock(return_value={
                "error": {"message": "Permission not granted for instagram_business_content_publish"}
            }),
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=error_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await adapter.upload(sample_job)

        assert result.state == PublishState.PERMISSION_REQUIRED.value
        assert "permission" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_upload_container_creation_network_error(self, adapter, valid_token, sample_job):
        """Erro de rede na criação do container → ERROR."""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=ConnectionError("DNS resolution failed"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await adapter.upload(sample_job)

        assert result.state == PublishState.ERROR.value
        assert "network error" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_upload_caption_includes_hashtags(self, adapter, valid_token, sample_job):
        """Verifica que hashtags são anexadas à legenda."""
        captured_payload = {}

        async def capture_post(url, data=None, **kwargs):
            captured_payload.update(data or {})
            return MagicMock(status_code=200, json=MagicMock(return_value={"id": "c1"}))

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[
            MagicMock(status_code=200, json=MagicMock(return_value={"id": "c1"})),
            MagicMock(status_code=200, json=MagicMock(return_value={"id": "m1"})),
        ])
        mock_client.get = AsyncMock(return_value=MagicMock(
            status_code=200, json=MagicMock(return_value={"status_code": "FINISHED"})
        ))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await adapter.upload(sample_job)

        # O primeiro POST deve conter caption com hashtags
        first_call_data = mock_client.post.call_args_list[0]
        caption = first_call_data.kwargs.get("data", {}).get("caption", "")
        assert "#gta6" in caption
        assert "#gtavi" in caption


# --- poll_status ---


class TestPollStatus:
    @pytest.mark.asyncio
    async def test_poll_returns_published_job_unchanged(self, adapter):
        job = PublishJob(
            job_id="j1", profile_id="p1", platform="instagram",
            video_path="", title="", description="",
            state=PublishState.PUBLISHED.value,
        )
        result = await adapter.poll_status(job)
        assert result.state == PublishState.PUBLISHED.value

    @pytest.mark.asyncio
    async def test_poll_returns_job_without_platform_post_id(self, adapter):
        job = PublishJob(
            job_id="j1", profile_id="p1", platform="instagram",
            video_path="", title="", description="",
            state=PublishState.PROCESSING.value,
        )
        result = await adapter.poll_status(job)
        assert result.job_id == "j1"  # Retorna inalterado

    @pytest.mark.asyncio
    async def test_poll_detects_published_status(self, adapter, valid_token):
        job = PublishJob(
            job_id="j1", profile_id="test_profile", platform="instagram",
            video_path="", title="", description="",
            state=PublishState.PROCESSING.value,
            platform_post_id="container_789",
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=MagicMock(
            status_code=200,
            json=MagicMock(return_value={"status_code": "PUBLISHED"}),
        ))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await adapter.poll_status(job)

        assert result.state == PublishState.PUBLISHED.value

    @pytest.mark.asyncio
    async def test_poll_detects_error_status(self, adapter, valid_token):
        job = PublishJob(
            job_id="j1", profile_id="test_profile", platform="instagram",
            video_path="", title="", description="",
            state=PublishState.PROCESSING.value,
            platform_post_id="container_err",
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=MagicMock(
            status_code=200,
            json=MagicMock(return_value={"status_code": "ERROR"}),
        ))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await adapter.poll_status(job)

        assert result.state == PublishState.ERROR.value


# --- Integração com OAuth credentials existentes ---


class TestInstagramTokenRefresh:
    """Testes do método refresh_instagram_token via ig_refresh_token grant."""

    @pytest.fixture
    def oauth_manager(self, tmp_path: Path):
        from src.publishing.oauth import OAuthManager
        return OAuthManager(data_root=tmp_path)

    @pytest.fixture
    def instagram_creds(self, oauth_manager, tmp_path: Path) -> Path:
        """Salva credenciais Instagram válidas para teste de renovação."""
        from src.publishing.oauth import OAuthCredentials
        creds = OAuthCredentials(
            profile_id="test_profile",
            platform="instagram",
            access_token="EAAOldToken123",
            refresh_token="",
            token_type="bearer",
            expires_at=time.time() + 86400,  # Expira em 1 dia (dentro do buffer de 1 dia)
            scopes=("instagram_business_basic", "instagram_business_content_publish"),
            client_id="1819988955893243",
            code_verifier="",
            connected_at=time.time(),
            account_id="17841479885114087",
            account_name="leonidagta6flashbr",
        )
        oauth_manager.save_credentials(creds)
        return oauth_manager._cred_path("test_profile", "instagram")

    def test_refresh_skips_when_token_still_valid(self, oauth_manager, tmp_path: Path):
        """Token com >1 dia de validade não deve ser renovado."""
        from src.publishing.oauth import OAuthCredentials
        creds = OAuthCredentials(
            profile_id="test_profile",
            platform="instagram",
            access_token="EAAValidToken",
            refresh_token="",
            token_type="bearer",
            expires_at=time.time() + 172800,  # 2 dias
            scopes=("instagram_business_basic",),
            client_id="1819988955893243",
            code_verifier="",
            connected_at=time.time(),
            account_id="17841479885114087",
            account_name="test",
        )
        oauth_manager.save_credentials(creds)

        result = oauth_manager.refresh_instagram_token("test_profile")
        assert result["success"] is True
        assert result.get("skipped") is True
        assert "no refresh needed" in result.get("message", "").lower()

    def test_refresh_returns_auth_required_when_no_creds(self, oauth_manager):
        """Sem credenciais → auth_required."""
        result = oauth_manager.refresh_instagram_token("nonexistent_profile")
        assert result["success"] is False
        assert result["state"] == "auth_required"

    def test_refresh_calls_ig_endpoint_when_token_near_expiry(self, oauth_manager, instagram_creds):
        """Token dentro do buffer de 1 dia deve chamar endpoint ig_refresh_token."""
        mock_response = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "access_token": "EAANewRefreshedToken456",
                "expires_in": 5184000,  # 60 dias
            }),
        )

        with patch("httpx.get", return_value=mock_response) as mock_get:
            result = oauth_manager.refresh_instagram_token("test_profile")

        assert result["success"] is True
        assert result["state"] == "connected"
        assert result["expires_in_days"] == 60
        # Verifica que o endpoint correto foi chamado
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert "graph.instagram.com/refresh_access_token" in call_args[0][0]
        assert call_args[1]["params"]["grant_type"] == "ig_refresh_token"

    def test_refresh_handles_expired_token_error(self, oauth_manager, instagram_creds):
        """Token revogado/expirado → state=token_expired."""
        mock_response = MagicMock(
            status_code=400,
            text='{"error":{"message":"Invalid OAuth access token"}}',
            json=MagicMock(return_value={"error": {"message": "Invalid OAuth access token"}}),
        )

        with patch("httpx.get", return_value=mock_response):
            result = oauth_manager.refresh_instagram_token("test_profile")

        assert result["success"] is False
        assert result["state"] == "token_expired"

    def test_refresh_persists_new_token_to_disk(self, oauth_manager, instagram_creds):
        """Token renovado deve ser persistido atomicamente no disco."""
        mock_response = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "access_token": "EAAPersistedToken789",
                "expires_in": 5184000,
            }),
        )

        with patch("httpx.get", return_value=mock_response):
            result = oauth_manager.refresh_instagram_token("test_profile")

        assert result["success"] is True
        # Ler credenciais do disco e verificar novo token
        saved = oauth_manager.load_credentials("test_profile", "instagram", auto_refresh=False)
        assert saved is not None
        assert saved.access_token == "EAAPersistedToken789"
        assert saved.account_id == "17841479885114087"  # Preservado


class TestRealCredentials:
    """Testes que verificam leitura das credenciais reais do projeto (sem API calls)."""

    def test_real_credentials_file_readable(self):
        """Verifica que o arquivo de credenciais real é legível e tem estrutura válida."""
        creds_path = Path("data/credentials/leonidagta6flashbr/instagram_oauth.json")
        if not creds_path.exists():
            pytest.skip("Arquivo de credenciais reais não encontrado")

        data = json.loads(creds_path.read_text(encoding="utf-8"))
        assert "access_token" in data
        assert "account_id" in data
        assert data["account_id"] == "17841479885114087"
        assert data["client_id"] == "1819988955893243"
        assert "instagram_business_content_publish" in data.get("scopes", [])

    def test_real_token_not_expired(self):
        """Verifica que o token real ainda não expirou."""
        creds_path = Path("data/credentials/leonidagta6flashbr/instagram_oauth.json")
        if not creds_path.exists():
            pytest.skip("Arquivo de credenciais reais não encontrado")

        data = json.loads(creds_path.read_text(encoding="utf-8"))
        expires_at = data.get("expires_at", 0)
        assert expires_at > time.time(), f"Token expirado em {expires_at}"