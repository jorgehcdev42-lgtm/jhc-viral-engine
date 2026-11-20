#!/usr/bin/env python3
"""Importa cookies do Chrome real para perfis Playwright.

Lê o banco de cookies do Chrome no macOS, decifra via Keychain,
e exporta para o formato Playwright storage_state por domínio.

Uso:
 python scripts/import_chrome_cookies.py          # importa TikTok + Instagram + YouTube
 python scripts/import_chrome_cookies.py tiktok    # só TikTok
 python scripts/import_chrome_cookies.py status    # verifica resultado
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SESSIONS_DIR = BASE / "data" / "browser_sessions"

PLATFORM_DOMAINS = {
    "tiktok": [".tiktok.com", "www.tiktok.com", "tiktok.com"],
    "instagram": [".instagram.com", "www.instagram.com", "instagram.com"],
    "youtube": [".youtube.com", "www.youtube.com", "youtube.com", ".google.com", "accounts.google.com", "studio.youtube.com"],
}

CHROME_COOKIES_DB = Path.home() / "Library" / "Application Support" / "Google" / "Chrome" / "Default" / "Cookies"
CHROME_LOCAL_STATE = Path.home() / "Library" / "Application Support" / "Google" / "Chrome" / "Local State"


def get_chrome_encryption_key():
    """Obtém chave de descriptografia do Chrome via Keychain."""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-w", "-s", "Chrome Safe Storage", "-a", "Chrome"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            print("   ⚠️  Senha do Chrome não encontrada na Keychain.")
            return None
        password = result.stdout.strip()

        # Derivar chave usando PBKDF2 (igual ao Chrome)
        import hashlib
        key = hashlib.pbkdf2_hmac("sha1", password.encode("utf-8"), b"saltysalt", 1003, dklen=16)
        return key
    except Exception as e:
        print(f"   ❌ Erro ao obter chave: {e}")
        return None


def decrypt_cookie_value(encrypted_value, key):
    """Decifra valor de cookie do Chrome."""
    if not encrypted_value:
        return ""
    if encrypted_value[:3] == b"v10":
        encrypted_value = encrypted_value[3:]
        # AES-128-CBC com IV de 16 zeros (padrão Chrome macOS)
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            iv = b" " * 16
            cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
            decryptor = cipher.decryptor()
            decrypted = decryptor.update(encrypted_value) + decryptor.finalize()
            # Remover PKCS7 padding
            padding_len = decrypted[-1]
            if isinstance(padding_len, int) and 1 <= padding_len <= 16:
                decrypted = decrypted[:-padding_len]
            return decrypted.decode("utf-8", errors="replace")
        except ImportError:
            # Fallback sem cryptography
            return _decrypt_openssl(encrypted_value, key)
        except Exception:
            return ""
    else:
        return encrypted_value.decode("utf-8", errors="replace")


def _decrypt_openssl(encrypted_value, key):
    """Fallback de descriptografia usando openssl."""
    try:
        import base64
        key_b64 = base64.b64encode(key).decode()
        iv = " " * 16
        proc = subprocess.run(
            ["openssl", "enc", "-aes-128-cbc", "-d", "-K", key.hex(), "-iv", iv.encode().hex()],
            input=encrypted_value, capture_output=True, timeout=5,
        )
        if proc.returncode == 0:
            return proc.stdout.decode("utf-8", errors="replace")
    except Exception:
        pass
    return ""


def import_cookies_for_platform(platform: str, key: bytes) -> int:
    """Importa cookies do Chrome para um perfil Playwright."""
    domains = PLATFORM_DOMAINS.get(platform, [])
    if not domains:
        print(f"   ❌ Plataforma desconhecida: {platform}")
        return 0

    # Copiar DB para temp (Chrome pode estar com lock)
    tmp_db = Path(tempfile.mktemp(suffix=".db"))
    try:
        shutil.copy2(CHROME_COOKIES_DB, tmp_db)
    except (OSError, shutil.SameFileError) as e:
        print(f"   ❌ Não consegui copiar Cookies DB: {e}")
        return 0

    cookies = []
    try:
        conn = sqlite3.connect(str(tmp_db))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Buscar cookies dos domínios relevantes
        domain_clauses = " OR ".join([f"host_key LIKE '%{d.lstrip('.')}'" for d in domains])
        query = f"""
            SELECT host_key, name, value, encrypted_value, path, expires_utc,
                   is_secure, is_httponly, samesite
            FROM cookies
            WHERE {domain_clauses}
            ORDER BY host_key, name
        """
        cursor.execute(query)

        for row in cursor.fetchall():
            # Decifra valor se necessário
            value = row["value"]
            if not value and row["encrypted_value"]:
                value = decrypt_cookie_value(row["encrypted_value"], key)

            # Chrome epoch: Jan 1, 1601. Converter para Unix timestamp
            chrome_ts = row["expires_utc"]
            if chrome_ts and chrome_ts > 0:
                # Chrome timestamps são microsegundos desde 1601-01-01
                unix_ts = (chrome_ts / 1_000_000) - 11644473600
            else:
                unix_ts = -1  # Session cookie

            # SameSite mapping: 0=unspecified(-1), 1=no_restriction(0), 2=lax(1), 3=strict(2)
            samesite_map = {0: -1, 1: 0, 2: 1, 3: 2}
            samesite = samesite_map.get(row["samesite"], -1)

            cookie = {
                "name": row["name"],
                "value": value or "",
                "domain": row["host_key"],
                "path": row["path"] or "/",
                "expires": unix_ts if unix_ts > 0 else -1,
                "secure": bool(row["is_secure"]),
                "httpOnly": bool(row["is_httponly"]),
                "sameSite": ["Strict", "Lax", "None"][samesite] if samesite in (0, 1, 2) else "Lax",
            }
            cookies.append(cookie)

        conn.close()
    except Exception as e:
        print(f"   ❌ Erro ao ler cookies: {e}")
        tmp_db.unlink(missing_ok=True)
        return 0
    finally:
        tmp_db.unlink(missing_ok=True)

    if not cookies:
        print(f"   ⚠️  Nenhum cookie encontrado para {platform.upper()} no Chrome.")
        return 0

    # Salvar no formato Playwright
    profile_dir = SESSIONS_DIR / f"{platform}_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    cookie_file = SESSIONS_DIR / f"{platform}_cookies.json"
    state_file = SESSIONS_DIR / f"{platform}_state.json"

    cookie_file.write_text(json.dumps(cookies, indent=2, ensure_ascii=False))

    # Criar storage_state compatível
    storage_state = {
        "cookies": cookies,
        "origins": [],
    }
    state_file.write_text(json.dumps(storage_state, indent=2, ensure_ascii=False))

    print(f"   ✅ {platform.upper()}: {len(cookies)} cookies importados")
    return len(cookies)


def check_status():
    """Verifica cookies importados."""
    import time
    print("\n📋 Status das sessões importadas do Chrome:\n")
    for platform in PLATFORM_DOMAINS:
        cookie_file = SESSIONS_DIR / f"{platform}_cookies.json"
        if cookie_file.exists():
            cookies = json.loads(cookie_file.read_text())
            age_hours = (time.time() - cookie_file.stat().st_mtime) / 3600
            domains = set(c.get("domain", "") for c in cookies)
            print(f"   ✅ {platform.upper():10s} — {len(cookies):3d} cookies — {len(domains)} domínios — {age_hours:.1f}h atrás")
        else:
            print(f"   ❌ {platform.upper():10s} — não importado")
    print()


def main():
    if len(sys.argv) < 2:
        targets = list(PLATFORM_DOMAINS.keys())
    elif sys.argv[1].lower() == "status":
        check_status()
        return
    elif sys.argv[1].lower() in PLATFORM_DOMAINS:
        targets = [sys.argv[1].lower()]
    elif sys.argv[1].lower() == "all":
        targets = list(PLATFORM_DOMAINS.keys())
    else:
        print(f"❌ Plataforma desconhecida: {sys.argv[1]}")
        print(f"   Disponíveis: {', '.join(PLATFORM_DOMAINS.keys())}, all, status")
        sys.exit(1)

    if not CHROME_COOKIES_DB.exists():
        print(f"❌ Chrome Cookies DB não encontrado: {CHROME_COOKIES_DB}")
        print(f"   Certifique-se que o Google Chrome está instalado.")
        sys.exit(1)

    print("🔑 Obtendo chave de descriptografia do Chrome...")
    key = get_chrome_encryption_key()
    if not key:
        print("   ❌ Não foi possível obter a chave. Tente:")
        print("   1. Fechar o Chrome completamente (Cmd+Q)")
        print("   2. Rodar novamente este script")
        sys.exit(1)

    print("   ✅ Chave obtida\n")

    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    for platform in targets:
        print(f"📦 Importando cookies para {platform.upper()}...")
        count = import_cookies_for_platform(platform, key)
        total += count

    print(f"\n🎉 Total: {total} cookies importados para {len(targets)} plataforma(s)")
    check_status()


if __name__ == "__main__":
    main()