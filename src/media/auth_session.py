"""AuthSession — Gerenciador de sessão autenticada para monetizegta6.

Usa Playwright para login interativo, persistência de cookies/storage state,
detecção de expiração e retomada automática. Credenciais nunca logadas nem commitadas.

Fluxo:
1. Verifica storage_state salvo → se válido, reusa
2. Se expirado ou inexistente → abre navegador para login interativo
3. Após login → salva storage_state + cookies
4. Expor cookies como dict/string para PackBulkImporter
"""

import json
import time
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

STORAGE_STATE_PATH = Path("data/auth/monetizegta6_state.json")
COOKIES_CACHE_PATH = Path("data/auth/monetizegta6_cookies.json")
AUTH_DIR = Path("data/auth")
PLATFORM_URL = "https://monetizegta6.vercel.app"
MEMBERS_URL = f"{PLATFORM_URL}/membros/pro/"
LOGIN_INDICATORS = ["/login", "/entrar", "/sign-in", "/auth"]
SESSION_VALID_INDICATORS = ["/membros", "/pro/", "/dashboard", "/area"]


class AuthSession:
    """Gerencia sessão autenticada para monetizegta6 via Playwright."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None
        AUTH_DIR.mkdir(parents=True, exist_ok=True)

    def _ensure_dirs(self) -> None:
        AUTH_DIR.mkdir(parents=True, exist_ok=True)

    def has_saved_state(self) -> bool:
        return STORAGE_STATE_PATH.exists() and STORAGE_STATE_PATH.stat().st_size > 10

    def get_cached_cookies(self) -> Optional[dict]:
        """Retorna cookies cacheados se existirem."""
        if not COOKIES_CACHE_PATH.exists():
            return None
        try:
            data = json.loads(COOKIES_CACHE_PATH.read_text())
            if isinstance(data, list) and len(data) > 0:
                return {c["name"]: c["value"] for c in data if "name" in c and "value" in c}
        except (json.JSONDecodeError, KeyError):
            pass
        return None

    def cookies_as_string(self, cookies: Optional[dict] = None) -> str:
        """Converte cookies dict para string Cookie header."""
        if cookies is None:
            cookies = self.get_cached_cookies()
        if not cookies:
            return ""
        return "; ".join(f"{k}={v}" for k, v in cookies.items())

    async def _start_browser(self):
        """Inicia Playwright + browser."""
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        launch_args = {"headless": self.headless}
        self._browser = await self._playwright.chromium.launch(**launch_args)

        # Tenta carregar storage state salvo
        context_opts = {}
        if self.has_saved_state():
            context_opts["storage_state"] = str(STORAGE_STATE_PATH)
            logger.info("Carregando storage_state salvo")

        self._context = await self._browser.new_context(**context_opts)
        self._page = await self._context.new_page()

    async def _save_state(self) -> None:
        """Salva storage state e cookies."""
        self._ensure_dirs()
        if self._context:
            await self._context.storage_state(path=str(STORAGE_STATE_PATH))
            cookies = await self._context.cookies()
            COOKIES_CACHE_PATH.write_text(json.dumps(cookies, indent=2))
            logger.info(f"Estado salvo: {len(cookies)} cookies")

    async def _is_session_valid(self) -> bool:
        """Verifica se sessão atual está válida acessando área de membros."""
        if not self._page:
            return False
        try:
            await self._page.goto(MEMBERS_URL, wait_until="domcontentloaded", timeout=15000)
            current_url = self._page.url.lower()
            # Se redirecionou para login, sessão expirou
            for indicator in LOGIN_INDICATORS:
                if indicator in current_url:
                    logger.info(f"Sessão expirada: redirecionado para {current_url}")
                    return False
            # Verifica se está na área de membros
            for indicator in SESSION_VALID_INDICATORS:
                if indicator in current_url:
                    logger.info(f"Sessão válida: {current_url}")
                    return True
            # URL não mudou significativamente — pode ser válida
            if MEMBERS_URL.lower() in current_url or PLATFORM_URL.lower() in current_url:
                return True
            return False
        except Exception as e:
            logger.warning(f"Erro ao verificar sessão: {e}")
            return False

    async def ensure_authenticated(self, interactive: bool = True) -> dict:
        """Garante sessão autenticada. Retorna status.

        Args:
            interactive: Se True, abre navegador visível para login quando necessário.
                        Se False, apenas verifica estado salvo.

        Returns:
            {"authenticated": bool, "method": str, "cookies_count": int, "error": str|None}
        """
        result = {"authenticated": False, "method": "none", "cookies_count": 0, "error": None}

        try:
            await self._start_browser()

            # Tenta sessão salva primeiro
            if self.has_saved_state():
                valid = await self._is_session_valid()
                if valid:
                    await self._save_state()  # Atualiza timestamps
                    cookies = await self._context.cookies()
                    result.update({
                        "authenticated": True,
                        "method": "saved_state",
                        "cookies_count": len(cookies),
                    })
                    logger.info("Sessão restaurada com sucesso")
                    return result
                else:
                    logger.info("Sessão salva expirada, tentando novo login")

            # Precisa de login interativo
            if not interactive:
                result["error"] = "Sessão expirada e modo não-interativo ativo"
                return result

            # Abre navegador visível para login
            logger.info("Abrindo navegador para login interativo...")
            # Fecha contexto headless e abre headed
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()

            # Reinicia em modo headed
            self.headless = False
            await self._start_browser()

            # Navega para página de login/membros
            await self._page.goto(MEMBERS_URL, wait_until="domcontentloaded", timeout=30000)

            # Aguarda usuário fazer login (até 5 minutos)
            logger.info("AGUARDANDO LOGIN... Faça login no navegador aberto.")
            try:
                # Espera até estar na área de membros
                await self._page.wait_for_url(
                    lambda url: any(ind in url.lower() for ind in SESSION_VALID_INDICATORS),
                    timeout=300000,  # 5 minutos
                )
                logger.info("Login detectado!")
            except Exception:
                # Timeout — verifica manualmente
                valid = await self._is_session_valid()
                if not valid:
                    result["error"] = "Timeout aguardando login (5 min)"
                    return result

            # Salva estado após login
            await self._save_state()
            cookies = await self._context.cookies()
            result.update({
                "authenticated": True,
                "method": "interactive_login",
                "cookies_count": len(cookies),
            })
            return result

        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Erro na autenticação: {e}")
            return result
        finally:
            # Não fecha browser aqui — pode ser reusado
            pass

    async def close(self) -> None:
        """Fecha browser e limpa recursos."""
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None

    async def discover_catalog(self) -> dict:
        """Descobre catálogo completo da plataforma usando sessão autenticada.

        Returns:
            {"videos": [...], "images": [...], "total_videos": int, "total_images": int,
             "pages_scraped": int, "error": str|None}
        """
        result = {
            "videos": [], "images": [], "total_videos": 0, "total_images": 0,
            "pages_scraped": 0, "error": None,
        }

        if not self._page:
            result["error"] = "Browser não iniciado. Chame ensure_authenticated() primeiro."
            return result

        try:
            # Navega para área de membros
            await self._page.goto(MEMBERS_URL, wait_until="networkidle", timeout=30000)
            await self._page.wait_for_timeout(2000)

            # Extrai links de vídeo e imagem da página
            all_links = await self._page.eval_on_selector_all(
                "a[href]", "els => els.map(e => ({href: e.href, text: e.textContent.trim()}))"
            )

            video_exts = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
            image_exts = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

            seen_urls = set()
            for link in all_links:
                href = link.get("href", "").strip()
                if not href or href in seen_urls:
                    continue
                seen_urls.add(href)

                lower = href.lower()
                # Google Drive links
                if "drive.google.com" in lower:
                    if any(lower.endswith(ext) for ext in video_exts):
                        result["videos"].append({"url": href, "source": "gdrive"})
                    elif any(lower.endswith(ext) for ext in image_exts):
                        result["images"].append({"url": href, "source": "gdrive"})
                    elif "/file/d/" in lower or "/uc?" in lower:
                        result["videos"].append({"url": href, "source": "gdrive_generic"})
                # Direct media links
                elif any(lower.endswith(ext) for ext in video_exts):
                    result["videos"].append({"url": href, "source": "direct"})
                elif any(lower.endswith(ext) for ext in image_exts):
                    result["images"].append({"url": href, "source": "direct"})
                # Thumbnail patterns
                elif "thumbnail" in lower or "thumb" in lower:
                    result["images"].append({"url": href, "source": "thumbnail"})

            result["pages_scraped"] = 1
            result["total_videos"] = len(result["videos"])
            result["total_images"] = len(result["images"])

            # Tenta encontrar paginação ou scroll infinito
            pagination = await self._page.query_selector_all(
                "a[href*='page'], button.load-more, .pagination a"
            )
            if pagination:
                logger.info(f"Paginação detectada: {len(pagination)} elementos")

            logger.info(
                f"Catálogo descoberto: {result['total_videos']} vídeos, "
                f"{result['total_images']} imagens"
            )

        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Erro na descoberta do catálogo: {e}")

        return result


# Funções síncronas wrapper para uso fora de async context
def get_cached_cookies_sync() -> Optional[dict]:
    """Versão síncrona de get_cached_cookies."""
    session = AuthSession()
    return session.get_cached_cookies()


def cookies_as_string_sync() -> str:
    """Versão síncrona de cookies_as_string."""
    session = AuthSession()
    return session.cookies_as_string()