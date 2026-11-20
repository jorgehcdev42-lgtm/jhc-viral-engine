"""Instagram Login Interativo — Phoenix P3.2

Abre navegador Chromium VISÍVEL (não headless) para login manual no Instagram.
Perfil persistente isolado em data/browser_sessions/instagram_profile/.
Após login confirmado, salva cookies e state para uso pelo BrowserPublisher.

Uso:
    python scripts/instagram_login.py

NÃO captura senhas, códigos 2FA ou outros segredos em logs.
NÃO contorna CAPTCHA ou desafios de segurança.
"""

import asyncio
import json
import time
from pathlib import Path


async def instagram_interactive_login():
    from playwright.async_api import async_playwright

    sessions_dir = Path("data/browser_sessions")
    sessions_dir.mkdir(parents=True, exist_ok=True)
    profile_dir = sessions_dir / "instagram_profile"
    cookies_path = sessions_dir / "instagram_cookies.json"
    state_path = sessions_dir / "instagram_state.json"
    screenshots_dir = sessions_dir / "instagram_screenshots"
    screenshots_dir.mkdir(exist_ok=True)

    async with async_playwright() as p:
        # Chromium visível com perfil persistente isolado
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            viewport={"width": 1280, "height": 900},
            locale="pt-BR",
            args=["--disable-blink-features=AutomationControlled"],
        )

        page = context.pages[0] if context.pages else await context.new_page()

        print("=" * 60)
        print("INSTAGRAM LOGIN INTERATIVO — JHC VIRAL ENGINE")
        print("=" * 60)
        print("NAVEGANDO: Abrindo https://www.instagram.com/accounts/login/")
        await page.goto("https://www.instagram.com/accounts/login/", timeout=45000)
        await page.wait_for_load_state("networkidle", timeout=30000)
        print(f"PAGINA_CARREGADA: URL = {page.url[:80]}")

        await page.screenshot(path=str(screenshots_dir / "01_login_page.png"))

        print()
        print("=" * 60)
        print("INSTRUCAO: Faca login MANUALMENTE no navegador que abriu.")
        print("Use usuario/senha, QR Code ou Facebook.")
        print("Complete qualquer verificacao de seguranca (2FA, SMS, email).")
        print("O navegador vai ficar aberto ate o login ser confirmado.")
        print("=" * 60)
        print()
        print("AGUARDANDO: Timeout de 10 minutos para autenticacao...")

        start = time.time()
        timeout = 600
        logged_in = False
        check_count = 0

        while time.time() - start < timeout:
            await asyncio.sleep(5)
            url = page.url
            elapsed = int(time.time() - start)
            check_count += 1

            # Screenshot periódico a cada 30s
            if elapsed % 30 == 0 and elapsed > 0:
                try:
                    await page.screenshot(
                        path=str(screenshots_dir / f"wait_{elapsed}s.png")
                    )
                except Exception:
                    pass

            try:
                # Detectar login bem-sucedido via múltiplos sinais
                not_login_url = (
                    "login" not in url.lower()
                    and "accounts" not in url.lower()
                    and "challenge" not in url.lower()
                )

                # Sinais de sessão autenticada no Instagram
                has_nav_bar = await page.locator(
                    'nav[role="navigation"], [role="banner"]'
                ).count() > 0
                has_create_btn = await page.locator(
                    '[aria-label="Nova publicação"], [aria-label="New post"], '
                    'svg[aria-label*="create"], svg[aria-label*="Create"]'
                ).count() > 0
                has_profile_link = await page.locator(
                    'a[href^="/"][aria-label*="profile"], '
                    'a[href^="/"][aria-label*="Perfil"], '
                    'img[alt*="profile picture"]'
                ).count() > 0
                has_feed_or_home = await page.locator(
                    'main[role="main"], [role="feed"]'
                ).count() > 0

                # Modal de login ainda visível?
                no_login_form = await page.locator(
                    'form[action*="login"], input[name="username"], '
                    '[role="dialog"]:has-text("Entrar"), '
                    '[role="dialog"]:has-text("Log In")'
                ).count() == 0

                strong_signals = sum([has_nav_bar, has_create_btn, has_profile_link, has_feed_or_home])

                if not_login_url and no_login_form and strong_signals >= 2:
                    logged_in = True
                    print(f"LOGIN_CONFIRMADO: URL = {url[:80]}")
                    print(f"  nav_bar={has_nav_bar}, create_btn={has_create_btn}, "
                          f"profile_link={has_profile_link}, feed={has_feed_or_home}")
                    await page.screenshot(
                        path=str(screenshots_dir / "04_logged_in.png")
                    )
                    break

            except Exception as e:
                if check_count % 12 == 0:
                    print(f"  check error (ignorado): {str(e)[:80]}")

            if elapsed % 15 == 0 and elapsed > 0:
                print(f" ...aguardando ({elapsed}s / {timeout}s)")

        if not logged_in:
            print("TIMEOUT: Login nao detectado em 10 minutos.")
            try:
                await page.screenshot(path=str(screenshots_dir / "timeout.png"))
            except Exception:
                pass
            print("BROWSER_MANTIDO_ABERTO: Feche manualmente ou tente novamente.")
            print("Aguardando mais 2 minutos antes de fechar...")
            await asyncio.sleep(120)
            await context.close()
            return

        # Aguardar estabilização pós-login
        await page.wait_for_timeout(3000)

        # Salvar cookies
        cookies = await context.cookies()
        cookies_path.write_text(
            json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"COOKIES_SALVOS: {len(cookies)} cookies em {cookies_path}")

        # Salvar storage state
        state = await context.storage_state()
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"STATE_SALVO: {state_path.stat().st_size} bytes")

        # Tentar extrair nome da conta
        account_name = None
        try:
            el = page.locator(
                'a[href^="/"][aria-label*="profile"], '
                'a[href^="/"][aria-label*="Perfil"]'
            ).first
            href = await el.get_attribute("href", timeout=5000)
            if href:
                account_name = href.strip("/").split("?")[0]
        except Exception:
            pass

        # Validar acesso à página de criação de conteúdo
        print("VALIDANDO: Navegando para pagina inicial...")
        upload_ok = False
        try:
            await page.goto("https://www.instagram.com/", timeout=30000)
            await page.wait_for_load_state("networkidle", timeout=20000)
            home_url = page.url
            upload_ok = "login" not in home_url.lower()

            # Verificar botão de criar publicação
            has_create = await page.locator(
                '[aria-label="Nova publicação"], [aria-label="New post"], '
                'svg[aria-label*="create"], svg[aria-label*="Create"]'
            ).count() > 0
            print(f"HOME_PAGE: url={home_url[:80]}, accessible={upload_ok}, create_btn={has_create}")
            await page.screenshot(path=str(screenshots_dir / "05_home_page.png"))
        except Exception as e:
            print(f"HOME_ERRO: {str(e)[:100]}")

        result = {
            "status": "logged_in",
            "account_name": account_name,
            "cookies_count": len(cookies),
            "current_url": page.url[:100],
            "home_accessible": upload_ok,
            "profile_dir": str(profile_dir),
            "cookies_path": str(cookies_path),
            "state_path": str(state_path),
        }
        print("RESULTADO: " + json.dumps(result, ensure_ascii=False))

        await context.close()
        print("BROWSER_FECHADO")
        print()
        print("SESSAO_PERSISTENTE: O perfil foi salvo em:")
        print(f"  {profile_dir}")
        print("O BrowserPublisher usara esta sessao automaticamente.")


asyncio.run(instagram_interactive_login())