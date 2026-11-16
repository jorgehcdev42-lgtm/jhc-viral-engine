"""Testes do AuthSession — MISSÃO 028 FASE 1.

Valida persistência de estado, cache de cookies, conversão para string,
detecção de sessão expirada e estrutura do módulo sem depender de browser real.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def auth_dir(tmp_path):
    """Diretório temporário para arquivos de auth."""
    d = tmp_path / "auth"
    d.mkdir()
    return d


@pytest.fixture
def session(tmp_path, auth_dir):
    """AuthSession com caminhos apontando para tmp_path."""
    from src.media.auth_session import AuthSession

    s = AuthSession(headless=True)
    # Redireciona caminhos para tmp
    import src.media.auth_session as mod
    mod.STORAGE_STATE_PATH = auth_dir / "state.json"
    mod.COOKIES_CACHE_PATH = auth_dir / "cookies.json"
    mod.AUTH_DIR = auth_dir
    mod.USER_DATA_DIR = auth_dir / "browser_profile"
    mod.USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    yield s
    # Restaura caminhos originais
    mod.STORAGE_STATE_PATH = Path("data/auth/monetizegta6_state.json")
    mod.COOKIES_CACHE_PATH = Path("data/auth/monetizegta6_cookies.json")
    mod.AUTH_DIR = Path("data/auth")
    mod.USER_DATA_DIR = Path("data/auth/browser_profile")


class TestAuthSessionUnit:
    """Testes unitários sem browser."""

    def test_has_saved_state_false_when_missing(self, session, auth_dir):
        # USER_DATA_DIR existe mas sem Cookies file nem storage_state válido
        import src.media.auth_session as mod
        # Garante que não há Cookies file nem state válido
        cookies_db = mod.USER_DATA_DIR / "Default" / "Cookies"
        if cookies_db.exists():
            cookies_db.unlink()
        mod.STORAGE_STATE_PATH.write_text("")
        assert session.has_saved_state() is False

    def test_has_saved_state_true_when_exists(self, session, auth_dir):
        import src.media.auth_session as mod
        # Cria storage_state com conteúdo válido (>10 bytes)
        mod.STORAGE_STATE_PATH.write_text('{"cookies": [{"name":"x"}]}')
        assert session.has_saved_state() is True

    def test_has_saved_state_false_when_empty(self, session, auth_dir):
        import src.media.auth_session as mod
        mod.STORAGE_STATE_PATH.write_text("")
        # Garante que não há Cookies file no perfil persistente
        cookies_db = mod.USER_DATA_DIR / "Default" / "Cookies"
        if cookies_db.exists():
            cookies_db.unlink()
        assert session.has_saved_state() is False

    def test_get_cached_cookies_none_when_missing(self, session):
        assert session.get_cached_cookies() is None

    def test_get_cached_cookies_returns_dict(self, session, auth_dir):
        import src.media.auth_session as mod
        cookies = [
            {"name": "session_id", "value": "abc123"},
            {"name": "token", "value": "xyz789"},
        ]
        mod.COOKIES_CACHE_PATH.write_text(json.dumps(cookies))
        result = session.get_cached_cookies()
        assert result == {"session_id": "abc123", "token": "xyz789"}

    def test_get_cached_cookies_handles_invalid_json(self, session, auth_dir):
        import src.media.auth_session as mod
        mod.COOKIES_CACHE_PATH.write_text("not json")
        assert session.get_cached_cookies() is None

    def test_cookies_as_string_empty(self, session):
        assert session.cookies_as_string() == ""

    def test_cookies_as_string_format(self, session, auth_dir):
        import src.media.auth_session as mod
        cookies = [
            {"name": "a", "value": "1"},
            {"name": "b", "value": "2"},
        ]
        mod.COOKIES_CACHE_PATH.write_text(json.dumps(cookies))
        result = session.cookies_as_string()
        assert "a=1" in result
        assert "b=2" in result
        assert "; " in result

    def test_cookies_as_string_with_explicit_dict(self, session):
        result = session.cookies_as_string({"x": "10", "y": "20"})
        assert "x=10" in result
        assert "y=20" in result


class TestAuthSessionAsync:
    """Testes async com mocks do Playwright."""

    @pytest.mark.asyncio
    async def test_ensure_authenticated_no_state_non_interactive(self, session, auth_dir):
        import src.media.auth_session as mod
        # Garante que não há estado salvo nem Cookies file
        cookies_db = mod.USER_DATA_DIR / "Default" / "Cookies"
        if cookies_db.exists():
            cookies_db.unlink()
        mod.STORAGE_STATE_PATH.write_text("")
        # Mock _start_browser para evitar Playwright real em teste unitário
        from unittest.mock import AsyncMock
        session._start_browser = AsyncMock()
        result = await session.ensure_authenticated(interactive=False)
        assert result["authenticated"] is False
        assert result["method"] == "none"

    @pytest.mark.asyncio
    async def test_discover_catalog_without_browser(self, session):
        result = await session.discover_catalog()
        assert result["error"] is not None
        assert "Browser" in result["error"] or "browser" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_close_safe_without_browser(self, session):
        # Não deve lançar exceção
        await session.close()


class TestAuthEndpoints:
    """Testa endpoints de auth registrados no main.py."""

    def test_auth_endpoints_registered(self):
        """Verifica que os 3 endpoints de auth existem no app."""
        from src.api.main import app

        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/api/auth/session/login" in routes
        assert "/api/auth/session/status" in routes
        assert "/api/auth/session/discover" in routes