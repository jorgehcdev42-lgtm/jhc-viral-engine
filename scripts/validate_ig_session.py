"""Valida sessao Instagram em modo visivel (nao headless) para bypass anti-bot."""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright


async def check_headful_session():
    profile_dir = Path("data/browser_sessions/instagram_profile")
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            viewport={"width": 1280, "height": 900},
            locale="pt-BR",
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://www.instagram.com/", timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=15000)
        url = page.url
        is_logged_in = "login" not in url.lower() and "accounts" not in url.lower()
        print(f"Modo: headless=False (visivel)")
        print(f"URL: {url[:80]}")
        print(f"Logado: {is_logged_in}")

        if is_logged_in:
            create_sels = [
                '[aria-label="Nova publicação"]',
                '[aria-label="New post"]',
                'svg[aria-label*="create"]',
                'svg[aria-label*="Create"]',
                '[role="button"]:has-text("Criar")',
                'a[href="/create/style/"]',
            ]
            for sel in create_sels:
                try:
                    count = await page.locator(sel).count()
                    if count > 0:
                        print(f"Criar encontrado: {sel} (count={count})")
                except Exception:
                    pass

            elements = await page.evaluate("""
                () => {
                    const results = [];
                    document.querySelectorAll('button, [role="button"], svg[aria-label]').forEach(el => {
                        const text = (el.innerText || '').trim().substring(0, 60);
                        const ariaLabel = el.getAttribute('aria-label') || '';
                        if (text || ariaLabel) results.push(text || ariaLabel);
                    });
                    return results.slice(0, 40);
                }
            """)
            print(f"Elementos interativos: {len(elements)}")
            for e in elements[:20]:
                print(f"  - {e}")
        else:
            print("SESSAO_INVALIDA: Instagram redirecionou para login em modo visivel")

        await context.close()
        print("BROWSER_FECHADO")


asyncio.run(check_headful_session())