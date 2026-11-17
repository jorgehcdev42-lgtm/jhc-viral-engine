#!/usr/bin/env python3
"""Autenticação interativa persistente para plataformas sociais.

Abre navegador visível (não headless) para login em cada plataforma.
Salva sessão em perfil separado por plataforma para reuso automático.

Uso:
    python scripts/auth_platforms.py tiktok
    python scripts/auth_platforms.py instagram
    python scripts/auth_platforms.py youtube
    python scripts/auth_platforms.py all       # todas sequencialmente
    python scripts/auth_platforms.py status     # verifica sessões salvas
"""

import asyncio
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SESSIONS_DIR = BASE / "data" / "browser_sessions"

PLATFORM_URLS = {
    "tiktok": "https://www.tiktok.com/login",
    "instagram": "https://www.instagram.com/accounts/login/",
    "youtube": "https://studio.youtube.com/",
}

async def authenticate_platform(platform: str) -> bool:
    """Abre navegador visível para login e salva sessão."""
    from playwright.async_api import async_playwright

    profile_dir = SESSIONS_DIR / f"{platform}_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n🔐 Abrindo {platform.upper()} para login...")
    print(f"   Perfil: {profile_dir}")
    print(f"   URL: {PLATFORM_URLS[platform]}")
    print(f"   ⚠️  Faça login manualmente. O navegador fechará automaticamente.")
    print(f"   Pressione ENTER no terminal quando estiver logado.\n")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            viewport={"width": 1280, "height": 900},
            locale="pt-BR",
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(PLATFORM_URLS[platform], wait_until="domcontentloaded")

        # Aguarda usuário fazer login e pressionar Enter
        input(f"   👉 Pressione ENTER após fazer login no {platform.upper()}... ")

        # Salva cookies e storage state
        cookies = await context.cookies()
        storage_state = await context.storage_state()

        cookie_file = SESSIONS_DIR / f"{platform}_cookies.json"
        state_file = SESSIONS_DIR / f"{platform}_state.json"

        cookie_file.write_text(json.dumps(cookies, indent=2, ensure_ascii=False))
        state_file.write_text(json.dumps(storage_state, indent=2, ensure_ascii=False))

        await context.close()

    print(f"   ✅ Sessão {platform.upper()} salva!")
    print(f"      Cookies: {len(cookies)} | State: {state_file.stat().st_size} bytes")
    return True


def check_status():
    """Verifica status das sessões salvas."""
    print("\n📋 Status das sessões:\n")
    for platform in PLATFORM_URLS:
        cookie_file = SESSIONS_DIR / f"{platform}_cookies.json"
        state_file = SESSIONS_DIR / f"{platform}_state.json"
        profile_dir = SESSIONS_DIR / f"{platform}_profile"

        if cookie_file.exists() and state_file.exists():
            cookies = json.loads(cookie_file.read_text())
            age_hours = (Path(__file__).stat().st_mtime - cookie_file.stat().st_mtime) / 3600
            print(f"   ✅ {platform.upper():10s} — {len(cookies):3d} cookies — salvo há {abs(age_hours):.1f}h")
        elif profile_dir.exists() and any(profile_dir.iterdir()):
            print(f"   ⚠️  {platform.upper():10s} — perfil existe mas sem cookies exportados")
        else:
            print(f"   ❌ {platform.upper():10s} — não autenticado")
    print()


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    target = sys.argv[1].lower()

    if target == "status":
        check_status()
        return

    if target == "all":
        platforms = list(PLATFORM_URLS.keys())
    elif target in PLATFORM_URLS:
        platforms = [target]
    else:
        print(f"❌ Plataforma desconhecida: {target}")
        print(f"   Disponíveis: {', '.join(PLATFORM_URLS.keys())}, all, status")
        sys.exit(1)

    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    for plat in platforms:
        try:
            await authenticate_platform(plat)
        except Exception as e:
            print(f"   ❌ Erro ao autenticar {plat}: {e}")
            continue

    print("\n🎉 Autenticação concluída!")
    check_status()


if __name__ == "__main__":
    asyncio.run(main())