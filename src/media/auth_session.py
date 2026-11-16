"""AuthSession — Gerenciador de sessão autenticada para monetizegta6.

Usa Playwright com contexto persistente para login interativo, captura real
de cookies httpOnly+Secure, detecção de expiração por conteúdo (não só URL)
e retomada automática. Credenciais nunca logadas nem commitadas.

Fluxo:
1. Verifica user_data_dir com sessão salva → se válido, reusa
2. Se expirado ou inexistente → abre navegador visível para login interativo
3. Após login → valida acesso a conteúdo protegido (não só redirect)
4. Salva storage_state + cookies completos
5. Expor cookies como dict/string para PackBulkImporter
"""

import json
import time
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

AUTH_DIR = Path("data/auth")
USER_DATA_DIR = AUTH_DIR / "browser_profile"
STORAGE_STATE_PATH = AUTH_DIR / "monetizegta6_state.json"
COOKIES_CACHE_PATH = AUTH_DIR / "monetizegta6_cookies.json"
PLATFORM_URL = "https://monetizegta6.vercel.app"
MEMBERS_URL = f"{PLATFORM_URL}/membros/pro/"
LOGIN_INDICATORS = ["/login", "/entrar", "/sign-in", "/auth"]
SESSION_VALID_INDICATORS = ["/membros", "/pro/", "/dashboard", "/area"]
# Elementos que comprovam acesso autenticado (não só URL)
AUTH_CONTENT_MARKERS = [
    "meus downloads",
    "meus arquivos",
    "biblioteca",
    "acesso pro",
    "plano pro",
    "download pack",
    "pack gta",
    "vídeos exclusivos",
    "conteúdo exclusivo",
    "sair",
    "logout",
    "minha conta",
]


class AuthSession:
    """Gerencia sessão autenticada para monetizegta6 via Playwright persistente."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None
        AUTH_DIR.mkdir(parents=True, exist_ok=True)
        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    def has_saved_state(self) -> bool:
        """Verifica se existe perfil persistente com dados."""
        if not USER_DATA_DIR.exists():
            return False
        # Verifica se há cookies ou localStorage no perfil
        cookies_file = USER_DATA_DIR / "Default" / "Cookies"
        state_file = STORAGE_STATE_PATH
        return (cookies_file.exists() and cookies_file.stat().st_size > 0) or \
               (state_file.exists() and state_file.stat().st_size > 10)

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
        """Inicia Playwright com contexto persistente."""
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()

        # launch_persistent_context mantém cookies, localStorage, IndexedDB
        # entre sessões automaticamente no user_data_dir
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=self.headless,
            viewport={"width": 1280, "height": 900},
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            accept_downloads=False,
            args=["--disable-blink-features=AutomationControlled"],
        )

        # Usa primeira página existente ou cria nova
        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()

    async def _save_state(self) -> None:
        """Salva storage state e cookies completos."""
        if self._context:
            await self._context.storage_state(path=str(STORAGE_STATE_PATH))
            cookies = await self._context.cookies()
            COOKIES_CACHE_PATH.write_text(json.dumps(cookies, indent=2))
            logger.info(f"Estado salvo: {len(cookies)} cookies")

    async def _check_authenticated_content(self) -> bool:
        """Verifica se página atual tem conteúdo de área autenticada.

        Não confia apenas na URL — busca marcadores textuais que só existem
        quando o usuário está realmente logado.
        """
        if not self._page:
            return False
        try:
            content = await self._page.content()
            content_lower = content.lower()

            # Busca marcadores de conteúdo autenticado
            found_markers = []
            for marker in AUTH_CONTENT_MARKERS:
                if marker.lower() in content_lower:
                    found_markers.append(marker)

            if found_markers:
                logger.info(f"Conteúdo autenticado confirmado: {found_markers[:3]}")
                return True

            # Fallback: verifica se há links de download ou elementos de membro
            download_links = await self._page.query_selector_all(
                "a[href*='download'], a[href*='drive.google'], button[class*='download']"
            )
            if len(download_links) > 2:
                logger.info(f"Links de download encontrados: {len(download_links)}")
                return True

            return False
        except Exception as e:
            logger.warning(f"Erro ao verificar conteúdo autenticado: {e}")
            return False

    async def _is_session_valid(self) -> bool:
        """Verifica se sessão atual é válida por URL E conteúdo."""
        if not self._page:
            return False
        try:
            await self._page.goto(MEMBERS_URL, wait_until="domcontentloaded", timeout=20000)
            await self._page.wait_for_timeout(2000)  # Aguarda JS renderizar

            current_url = self._page.url.lower()

            # Se redirecionou para login, sessão expirou
            for indicator in LOGIN_INDICATORS:
                if indicator in current_url:
                    logger.info(f"Sessão expirada: redirecionado para {current_url}")
                    return False

            # URL parece válida — confirma por conteúdo
            has_content = await self._check_authenticated_content()
            if has_content:
                logger.info(f"Sessão válida confirmada por conteúdo: {current_url}")
                return True

            # URL válida mas sem conteúdo confirmado — pode ser loading lento
            # Tenta aguardar mais um pouco
            await self._page.wait_for_timeout(3000)
            has_content = await self._check_authenticated_content()
            if has_content:
                logger.info(f"Sessão válida após espera adicional: {current_url}")
                return True

            logger.warning(f"URL válida ({current_url}) mas conteúdo não confirmado")
            return False

        except Exception as e:
            logger.warning(f"Erro ao verificar sessão: {e}")
            return False

    async def ensure_authenticated(self, interactive: bool = True) -> dict:
        """Garante sessão autenticada. Retorna status.

        Args:
            interactive: Se True, abre navegador visível para login quando necessário.

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
                    await self._save_state()
                    cookies = await self._context.cookies()
                    result.update({
                        "authenticated": True,
                        "method": "saved_state",
                        "cookies_count": len(cookies),
                    })
                    logger.info("Sessão restaurada com sucesso")
                    return result
                else:
                    logger.info("Sessão salva expirada ou inválida")

            # Precisa de login interativo
            if not interactive:
                result["error"] = "Sessão expirada e modo não-interativo ativo"
                return result

            # Abre navegador visível para login
            logger.info("Abrindo navegador para login interativo...")

            # Fecha contexto atual e reabre em modo headed
            if self._context:
                await self._context.close()
            if self._playwright:
                await self._playwright.stop()

            self.headless = False
            await self._start_browser()

            # Navega para página de membros/login
            await self._page.goto(MEMBERS_URL, wait_until="domcontentloaded", timeout=30000)

            # Aguarda usuário fazer login (até 5 minutos)
            logger.info("AGUARDANDO LOGIN... Faça login no navegador aberto.")
            print("\n" + "=" * 60)
            print("NAVEGADOR ABERTO — FAÇA LOGIN NA PÁGINA")
            print("Timeout: 5 minutos")
            print("=" * 60 + "\n")

            # Polling manual: verifica a cada 3s se login foi concluído
            start_time = time.time()
            timeout_seconds = 300  # 5 minutos
            logged_in = False

            while time.time() - start_time < timeout_seconds:
                await self._page.wait_for_timeout(3000)
                current_url = self._page.url.lower()

                # Verifica se saiu da página de login
                is_login_page = any(ind in current_url for ind in LOGIN_INDICATORS)
                if is_login_page:
                    continue

                # Verifica conteúdo autenticado
                has_auth_content = await self._check_authenticated_content()
                if has_auth_content:
                    logged_in = True
                    logger.info("Login detectado por conteúdo!")
                    break

                # Fallback: URL mudou para área de membros
                is_members_url = any(ind in current_url for ind in SESSION_VALID_INDICATORS)
                if is_members_url:
                    # Aguarda mais um ciclo para confirmar conteúdo
                    await self._page.wait_for_timeout(2000)
                    has_auth_content = await self._check_authenticated_content()
                    if has_auth_content:
                        logged_in = True
                        logger.info("Login detectado por URL + conteúdo!")
                        break

            if not logged_in:
                result["error"] = "Timeout aguardando login (5 min) ou conteúdo não confirmado"
                return result

            # Login confirmado — salva estado
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

    async def close(self) -> None:
        """Fecha browser e limpa recursos."""
        try:
            if self._context:
                await self._context.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None

    async def discover_catalog(self) -> dict:
        """Descobre catálogo completo usando sessão autenticada.

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
            await self._page.goto(MEMBERS_URL, wait_until="networkidle", timeout=30000)
            await self._page.wait_for_timeout(3000)

            # Extrai todos os links da página
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
                if "drive.google.com" in lower:
                    if any(lower.endswith(ext) for ext in video_exts):
                        result["videos"].append({"url": href, "source": "gdrive"})
                    elif any(lower.endswith(ext) for ext in image_exts):
                        result["images"].append({"url": href, "source": "gdrive"})
                    elif "/file/d/" in lower or "/uc?" in lower:
                        result["videos"].append({"url": href, "source": "gdrive_generic"})
                elif any(lower.endswith(ext) for ext in video_exts):
                    result["videos"].append({"url": href, "source": "direct"})
                elif any(lower.endswith(ext) for ext in image_exts):
                    result["images"].append({"url": href, "source": "direct"})
                elif "thumbnail" in lower or "thumb" in lower:
                    result["images"].append({"url": href, "source": "thumbnail"})

            result["pages_scraped"] = 1
            result["total_videos"] = len(result["videos"])
            result["total_images"] = len(result["images"])

            # Tenta scroll infinito para carregar mais conteúdo
            prev_height = 0
            scroll_attempts = 0
            max_scrolls = 20
            while scroll_attempts < max_scrolls:
                await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await self._page.wait_for_timeout(1500)
                new_height = await self._page.evaluate("document.body.scrollHeight")
                if new_height == prev_height:
                    break
                prev_height = new_height
                scroll_attempts += 1

                # Re-extrai links após scroll
                new_links = await self._page.eval_on_selector_all(
                    "a[href]", "els => els.map(e => ({href: e.href, text: e.textContent.trim()}))"
                )
                for link in new_links:
                    href = link.get("href", "").strip()
                    if not href or href in seen_urls:
                        continue
                    seen_urls.add(href)
                    lower = href.lower()
                    if "drive.google.com" in lower:
                        if any(lower.endswith(ext) for ext in video_exts):
                            result["videos"].append({"url": href, "source": "gdrive"})
                        elif "/file/d/" in lower or "/uc?" in lower:
                            result["videos"].append({"url": href, "source": "gdrive_generic"})
                    elif any(lower.endswith(ext) for ext in video_exts):
                        result["videos"].append({"url": href, "source": "direct"})
                    elif any(lower.endswith(ext) for ext in image_exts):
                        result["images"].append({"url": href, "source": "direct"})

            result["total_videos"] = len(result["videos"])
            result["total_images"] = len(result["images"])
            result["pages_scraped"] = 1 + scroll_attempts

            logger.info(
                f"Catálogo: {result['total_videos']} vídeos, "
                f"{result['total_images']} imagens, "
                f"{result['pages_scraped']} scrolls"
            )

        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Erro na descoberta do catálogo: {e}")

        return result


def get_cached_cookies_sync() -> Optional[dict]:
    """Versão síncrona de get_cached_cookies."""
    session = AuthSession()
    return session.get_cached_cookies()


def cookies_as_string_sync() -> str:
    """Versão síncrona de cookies_as_string."""
    session = AuthSession()
    return session.cookies_as_string()