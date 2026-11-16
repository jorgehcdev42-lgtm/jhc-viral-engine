#!/usr/bin/env python3
"""Login interativo monetizegta6 v3 — contexto persistente, captura cookies
direto do SQLite após login confirmado, validação por conteúdo protegido.

Uso: PYTHONPATH="$PWD" .venv/bin/python scripts/login_monetizegta6.py
"""

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

AUTH_DIR = Path("data/auth")
PROFILE_DIR = AUTH_DIR / "browser_profile"
COOKIES_CACHE = AUTH_DIR / "monetizegta6_cookies.json"
STATE_FILE = AUTH_DIR / "monetizegta6_state.json"

AUTH_DIR.mkdir(parents=True, exist_ok=True)
PROFILE_DIR.mkdir(parents=True, exist_ok=True)


def extract_cookies_from_sqlite() -> list:
    """Lê cookies diretamente do SQLite do Chromium após contexto fechar."""
    db_path = PROFILE_DIR / "Default" / "Cookies"
    if not db_path.exists():
        return []
    try:
        # Cópia para evitar lock
        import shutil, tempfile
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name
        shutil.copy2(str(db_path), tmp_path)

        conn = sqlite3.connect(tmp_path)
        cursor = conn.execute(
            "SELECT name, value, host_key, path, expires_utc, is_secure, is_httponly "
            "FROM cookies WHERE host_key LIKE '%monetizegta6%' OR host_key LIKE '%vercel%'"
        )
        cookies = []
        for row in cursor.fetchall():
            cookies.append({
                "name": row[0],
                "value": row[1],
                "domain": row[2],
                "path": row[3],
                "expires": row[4],
                "secure": bool(row[5]),
                "httpOnly": bool(row[6]),
            })
        conn.close()
        Path(tmp_path).unlink(missing_ok=True)
        return cookies
    except Exception as e:
        print(f"  Aviso: erro lendo SQLite: {e}")
        return []


async def main():
    from playwright.async_api import async_playwright

    print("=" * 60)
    print("JHC VIRAL ENGINE — Login monetizegta6 v3")
    print("Contexto persistente + extração SQLite + validação conteúdo")
    print("=" * 60)
    print()

    pw = await async_playwright().start()

    # Contexto persistente mantém cookies entre sessões
    context = await pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        viewport={"width": 1280, "height": 900},
        locale="pt-BR",
        timezone_id="America/Sao_Paulo",
        args=["--disable-blink-features=AutomationControlled"],
    )

    page = context.pages[0] if context.pages else await context.new_page()

    # Navega para área de membros
    print("Navegando para monetizegta6/membros/pro/ ...")
    await page.goto("https://monetizegta6.vercel.app/membros/pro/",
                     wait_until="domcontentloaded", timeout=30000)

    current_url = page.url.lower()
    login_indicators = ["/login", "/entrar", "/sign-in", "/auth"]
    is_login = any(ind in current_url for ind in login_indicators)

    if is_login:
        print()
        print("=" * 60)
        print("NAVEGADOR ABERTO — FAÇA LOGIN NA PÁGINA")
        print("O sistema detecta automaticamente quando concluir.")
        print("Timeout: 5 minutos.")
        print("=" * 60)
        print()

        # Polling: verifica a cada 3s se login concluiu
        import time
        start = time.time()
        logged_in = False

        while time.time() - start < 300:
            await page.wait_for_timeout(3000)
            url = page.url.lower()

            # Ainda na página de login?
            if any(ind in url for ind in login_indicators):
                continue

            # Verifica conteúdo autenticado
            content = await page.content()
            content_lower = content.lower()
            auth_markers = ["meus downloads", "biblioteca", "acesso pro",
                           "download pack", "pack gta", "vídeos exclusivos",
                           "sair", "logout", "minha conta"]
            found = [m for m in auth_markers if m in content_lower]

            if found:
                print(f"✅ Login detectado! Marcadores: {found[:3]}")
                logged_in = True
                break

            # URL mudou para membros mas sem marcadores claros
            if "/membros" in url or "/pro/" in url:
                await page.wait_for_timeout(3000)
                content = await page.content()
                content_lower = content.lower()
                found = [m for m in auth_markers if m in content_lower]
                if found:
                    print(f"✅ Login detectado (2ª verificação)! Marcadores: {found[:3]}")
                    logged_in = True
                    break

        if not logged_in:
            print("❌ Timeout ou login não confirmado por conteúdo.")
            await context.close()
            await pw.stop()
            sys.exit(1)
    else:
        # Já estava logado (sessão persistida)
        content = await page.content()
        content_lower = content.lower()
        auth_markers = ["meus downloads", "biblioteca", "acesso pro",
                       "download pack", "pack gta", "vídeos exclusivos",
                       "sair", "logout", "minha conta"]
        found = [m for m in auth_markers if m in content_lower]
        if found:
            print(f"✅ Sessão persistida válida! Marcadores: {found[:3]}")
        else:
            print(f"⚠️ URL não é login ({current_url}) mas conteúdo não confirmado.")
            print("   Tentando prosseguir mesmo assim...")

    # Salva storage_state ANTES de fechar
    print("\nSalvando estado da sessão...")
    try:
        state = await context.storage_state()
        STATE_FILE.write_text(json.dumps(state, indent=2))
        print(f"  storage_state: {len(state.get('cookies', []))} cookies via API")
    except Exception as e:
        print(f"  storage_state falhou: {e}")

    # Tenta cookies via API antes de fechar
    api_cookies = []
    try:
        api_cookies = await context.cookies()
        print(f"  context.cookies(): {len(api_cookies)} cookies")
    except Exception as e:
        print(f"  context.cookies() falhou: {e}")

    # Fecha contexto (libera lock do SQLite)
    await context.close()
    await pw.stop()

    # Se API retornou cookies vazios, extrai do SQLite
    if len(api_cookies) == 0:
        print("\nAPI retornou 0 cookies. Extraindo do SQLite...")
        sqlite_cookies = extract_cookies_from_sqlite()
        print(f"  SQLite: {len(sqlite_cookies)} cookies encontrados")
        if sqlite_cookies:
            COOKIES_CACHE.write_text(json.dumps(sqlite_cookies, indent=2))
            print(f"  ✅ Cookies salvos em {COOKIES_CACHE}")
        else:
            print("  ⚠️ Nenhum cookie encontrado no SQLite também.")
    else:
        COOKIES_CACHE.write_text(json.dumps(api_cookies, indent=2))
        print(f"✅ {len(api_cookies)} cookies salvos em {COOKIES_CACHE}")

    # Resultado final
    final_cookies = api_cookies if api_cookies else extract_cookies_from_sqlite()
    print()
    print("=" * 60)
    if len(final_cookies) > 0:
        print(f"✅ LOGIN BEM-SUCEDIDO!")
        print(f"   Cookies capturados: {len(final_cookies)}")
        print(f"   Perfil persistente: {PROFILE_DIR}")
        print(f"   Cache cookies: {COOKIES_CACHE}")
    else:
        print("⚠️ Login pode ter funcionado mas cookies não foram capturados.")
        print("   O perfil persistente ainda pode conter a sessão.")
        print("   Verifique acessando /api/auth/session/status")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())