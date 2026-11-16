#!/usr/bin/env python3
"""Abre navegador visível para Dr. Jorge digitar e-mail no formulário do pack.
Após submissão, detecta catálogo real, salva links descobertos.

Uso: PYTHONPATH="$PWD" .venv/bin/python scripts/email_pack_access.py
"""

import asyncio
import json
import time
from pathlib import Path

AUTH_DIR = Path("data/auth")
PROFILE_DIR = AUTH_DIR / "browser_profile"
CATALOG_FILE = AUTH_DIR / "catalog_discovered.json"

AUTH_DIR.mkdir(parents=True, exist_ok=True)
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

async def main():
    from playwright.async_api import async_playwright

    print("=" * 60)
    print("JHC VIRAL ENGINE — Acesso ao Pack via E-mail")
    print("=" * 60)
    print()
    print("Abrindo navegador para você digitar o e-mail da compra.")
    print("Após preencher e clicar em 'Acessar meu pack', o sistema")
    print("detecta automaticamente o catálogo e salva os links.")
    print("Timeout: 10 minutos.")
    print()

    pw = await async_playwright().start()

    context = await pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        viewport={"width": 1280, "height": 900},
        locale="pt-BR",
        timezone_id="America/Sao_Paulo",
        accept_downloads=True,
        args=["--disable-blink-features=AutomationControlled"],
    )

    page = context.pages[0] if context.pages else await context.new_page()

    # Navega para formulário de acesso
    await page.goto(
        "https://monetizegta6.vercel.app/acesso/pro/",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    await page.wait_for_timeout(2000)

    print("NAVEGADOR ABERTO — Digite o e-mail e clique em 'Acessar meu pack'")
    print("Aguardando submissão do formulário...")
    print()

    # Aguarda formulário ser submetido e URL mudar (GET form → ?email=xxx)
    start = time.time()
    timeout = 600  # 10 min
    form_submitted = False

    while time.time() - start < timeout:
        await page.wait_for_timeout(2000)
        url = page.url

        # Form method=GET → URL ganha ?email= após submit
        if "email=" in url or "?" in url:
            form_submitted = True
            print(f"✅ Formulário submetido! URL: {url}")
            break

        # Ou pode ter sido redirecionado para outra página
        body = await page.inner_text("body")
        if len(body) > 500:  # Página maior que o form inicial
            form_submitted = True
            print(f"✅ Conteúdo carregado! URL: {url}")
            break

    if not form_submitted:
        print("❌ Timeout: formulário não foi submetido em 10 minutos.")
        await context.close()
        await pw.stop()
        return

    # Aguarda catálogo carregar (pode ter JS renderizando)
    print("\nAguardando catálogo carregar...")
    await page.wait_for_timeout(5000)

    # Scroll para carregar conteúdo dinâmico
    for i in range(10):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1500)
        body_len = len(await page.inner_text("body"))
        if body_len > 5000:
            break

    # Captura estado final
    final_url = page.url
    body_text = await page.inner_text("body")
    html = await page.content()

    # Salva HTML para debug
    Path("data/auth/catalog_page.html").write_text(html)

    # Extrai TODOS os links
    all_links = await page.eval_on_selector_all(
        "a[href]",
        "els => els.map(e => ({href: e.href, text: e.textContent.trim().substring(0,120)}))",
    )

    # Categoriza links
    video_links = []
    image_links = []
    gdrive_links = []
    other_links = []

    for link in all_links:
        href = link.get("href", "")
        lower = href.lower()
        if "drive.google.com" in lower:
            gdrive_links.append(link)
            if any(lower.endswith(ext) for ext in [".mp4", ".mov", ".avi", ".mkv"]):
                video_links.append(link)
            elif any(lower.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                image_links.append(link)
        elif any(lower.endswith(ext) for ext in [".mp4", ".mov", ".avi", ".mkv", ".webm"]):
            video_links.append(link)
        elif any(lower.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]):
            image_links.append(link)
        else:
            other_links.append(link)

    # Busca botões de download
    download_elements = await page.eval_on_selector_all(
        'a[download], button:has-text("download"), a:has-text("download"), a:has-text("baixar")',
        "els => els.map(e => ({tag: e.tagName, text: e.textContent.trim().substring(0,80), href: e.href || ''}))",
    )

    # Monta resultado
    catalog = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "final_url": final_url,
        "body_length": len(body_text),
        "total_links": len(all_links),
        "video_links": len(video_links),
        "image_links": len(image_links),
        "gdrive_links": len(gdrive_links),
        "download_elements": len(download_elements),
        "videos": video_links[:50],
        "images": image_links[:50],
        "gdrive": gdrive_links[:50],
        "downloads": download_elements[:50],
        "body_preview": body_text[:2000],
    }

    CATALOG_FILE.write_text(json.dumps(catalog, indent=2, ensure_ascii=False))

    print()
    print("=" * 60)
    print("RESULTADO DA DESCOBERTA:")
    print(f"  URL final: {final_url}")
    print(f"  Tamanho página: {len(body_text)} chars")
    print(f"  Total de links: {len(all_links)}")
    print(f"  Links de vídeo: {len(video_links)}")
    print(f"  Links de imagem: {len(image_links)}")
    print(f"  Links Google Drive: {len(gdrive_links)}")
    print(f"  Elementos de download: {len(download_elements)}")
    print()

    if gdrive_links:
        print("  Primeiros links Google Drive:")
        for g in gdrive_links[:5]:
            print(f"    {g['text'][:50]} → {g['href'][:100]}")

    if video_links:
        print("  Primeiros vídeos:")
        for v in video_links[:3]:
            print(f"    {v['text'][:50]} → {v['href'][:100]}")

    if image_links:
        print("  Primeiras imagens:")
        for im in image_links[:3]:
            print(f"    {im['text'][:50]} → {im['href'][:100]}")

    print(f"\nCatálogo salvo em: {CATALOG_FILE}")
    print("=" * 60)

    # Mantém browser aberto mais 30s para inspeção manual
    print("\nNavegador ficará aberto mais 30s para inspeção...")
    await page.wait_for_timeout(30000)

    await context.close()
    await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())