"""PackBulkImporter — Importador massivo de packs de vídeos comprados.

Descobre, baixa, verifica e organiza milhares de arquivos do SSD externo.
Suporta Google Drive, YouTube, Instagram, arquivos locais e packs customizados.
Persistência de progresso, retomada após interrupção, deduplicação, integridade.

Estados: PENDING, DOWNLOADING, VERIFYING, COMPLETED, FAILED, BLOCKED_AUTH
"""

import os
import json
import time
import hashlib
import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional
from enum import Enum


class DownloadState(str, Enum):
    PENDING = "PENDING"
    DOWNLOADING = "DOWNLOADING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED_AUTH = "BLOCKED_AUTH"


@dataclass
class DownloadEntry:
    url: str
    filename: str
    dest_path: str = ""
    state: str = DownloadState.PENDING.value
    size_bytes: int = 0
    expected_size: int = 0
    sha256: str = ""
    tags: list[str] = field(default_factory=list)
    category: str = "uncategorized"
    source_pack: str = ""
    error: str = ""
    retries: int = 0
    max_retries: int = 3
    started_at: float = 0.0
    completed_at: float = 0.0
    created_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DownloadEntry":
        valid = {k for k in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in valid})


@dataclass
class ImportProgress:
    total_discovered: int = 0
    total_downloaded: int = 0
    total_failed: int = 0
    total_duplicates: int = 0
    total_blocked_auth: int = 0
    bytes_downloaded: int = 0
    current_speed_bps: float = 0.0
    ssd_free_bytes: int = 0
    last_updated: float = 0.0
    is_running: bool = False
    is_paused: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class PackBulkImporter:
    """Importador massivo reutilizável para packs de vídeos."""

    PROGRESS_FILE = "import_progress.json"
    ENTRIES_FILE = "download_entries.json"
    MANIFEST_FILE = "pack_manifest.json"

    def __init__(self, ssd_root: str, data_root: str = "data", cookies: str = ""):
        self.ssd_root = Path(ssd_root)
        self.data_root = Path(data_root)
        self.import_dir = self.data_root / "bulk_import"
        self.downloads_dir = self.ssd_root / "JHC-VIRAL-IMPORTS"
        self.state_dir = self.import_dir / "state"
        self.cookies = cookies  # Cookie header string for authenticated requests

        for d in [self.import_dir, self.downloads_dir, self.state_dir]:
            d.mkdir(parents=True, exist_ok=True)

        self.progress_file = self.state_dir / self.PROGRESS_FILE
        self.entries_file = self.state_dir / self.ENTRIES_FILE
        self.manifest_file = self.state_dir / self.MANIFEST_FILE

        self._entries: dict[str, DownloadEntry] = {}
        self._progress = ImportProgress()
        self._load_state()

    def _load_state(self):
        """Carrega estado persistente para retomada."""
        if self.entries_file.exists():
            try:
                data = json.loads(self.entries_file.read_text())
                for item in data:
                    entry = DownloadEntry.from_dict(item)
                    self._entries[entry.url] = entry
            except Exception:
                pass

        if self.progress_file.exists():
            try:
                data = json.loads(self.progress_file.read_text())
                self._progress = ImportProgress(**data)
            except Exception:
                pass

    def _save_state(self):
        """Persiste estado atual para retomada."""
        entries_data = [e.to_dict() for e in self._entries.values()]
        self.entries_file.write_text(json.dumps(entries_data, indent=2))
        self._progress.last_updated = time.time()
        self.progress_file.write_text(
            json.dumps(self._progress.to_dict(), indent=2)
        )

    def _compute_ssd_free(self) -> int:
        """Verifica espaço livre no SSD."""
        try:
            stat = shutil.disk_usage(str(self.ssd_root))
            return stat.free
        except Exception:
            return 0

    def _file_hash(self, path: Path) -> str:
        """SHA256 parcial (primeiros + últimos 1MB) para verificação rápida."""
        try:
            h = hashlib.sha256()
            size = path.stat().st_size
            with open(path, "rb") as f:
                h.update(f.read(min(1024 * 1024, size)))
                if size > 2 * 1024 * 1024:
                    f.seek(-1024 * 1024, 2)
                    h.update(f.read(1024 * 1024))
            return h.hexdigest()
        except Exception:
            return ""

    def _download_gdrive(self, file_id: str, dest: Path) -> tuple[bool, str]:
        """Baixa arquivo do Google Drive via gdown ou curl."""
        # Tentar gdown primeiro
        try:
            result = subprocess.run(
                ["gdown", "--fuzzy", file_id, "-O", str(dest)],
                capture_output=True, text=True, timeout=600
            )
            if result.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
                return True, ""
        except FileNotFoundError:
            pass
        except subprocess.TimeoutExpired:
            return False, "Timeout gdown"

        # Fallback: curl com link direto
        direct_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        try:
            result = subprocess.run(
                ["curl", "-L", "-o", str(dest), "-s", "-S",
                 "--max-time", "600", direct_url],
                capture_output=True, text=True, timeout=620
            )
            if dest.exists() and dest.stat().st_size > 1024:
                # Verificar se não é página HTML de erro/confirmação
                with open(dest, "rb") as f:
                    header = f.read(200)
                if b"<html" in header.lower() or b"virus scan" in header.lower():
                    dest.unlink(missing_ok=True)
                    return False, "Google Drive requer confirmação manual ou auth"
                return True, ""
            else:
                dest.unlink(missing_ok=True)
                return False, "Download falhou ou arquivo vazio"
        except subprocess.TimeoutExpired:
            return False, "Timeout curl"
        except Exception as e:
            return False, str(e)

    def _download_direct(self, url: str, dest: Path) -> tuple[bool, str]:
        """Baixa arquivo via URL direta com curl."""
        try:
            result = subprocess.run(
                ["curl", "-L", "-o", str(dest), "-s", "-S",
                 "--max-time", "600", "--retry", "2", url],
                capture_output=True, text=True, timeout=620
            )
            if dest.exists() and dest.stat().st_size > 1024:
                return True, ""
            else:
                dest.unlink(missing_ok=True)
                return False, "Download falhou ou arquivo vazio"
        except subprocess.TimeoutExpired:
            return False, "Timeout"
        except Exception as e:
            return False, str(e)

    def add_entries(self, entries: list[dict]) -> dict:
        """Adiciona entradas de download ao queue."""
        added = 0
        duplicates = 0
        for item in entries:
            url = item.get("url", "")
            if not url:
                continue
            if url in self._entries:
                duplicates += 1
                continue

            filename = item.get("filename", url.split("/")[-1].split("?")[0])
            if not filename or "." not in filename:
                filename = f"{hashlib.md5(url.encode()).hexdigest()[:8]}.mp4"

            pack_name = item.get("source_pack", "unknown")
            pack_dir = self.downloads_dir / pack_name
            pack_dir.mkdir(parents=True, exist_ok=True)
            dest = pack_dir / filename

            entry = DownloadEntry(
                url=url,
                filename=filename,
                dest_path=str(dest),
                tags=item.get("tags", []),
                category=item.get("category", "uncategorized"),
                source_pack=pack_name,
                created_at=time.time(),
            )
            self._entries[url] = entry
            added += 1

        self._progress.total_discovered = len(self._entries)
        self._progress.total_duplicates += duplicates
        self._save_state()
        return {"added": added, "duplicates": duplicates, "total": len(self._entries)}

    def process_next(self) -> Optional[dict]:
        """Processa próxima entrada pendente. Retorna resultado ou None se fila vazia."""
        self._progress.ssd_free_bytes = self._compute_ssd_free()

        # Verificar espaço mínimo (1GB)
        if self._progress.ssd_free_bytes < 1024 * 1024 * 1024:
            return {"error": "Espaço insuficiente no SSD", "free_gb": self._progress.ssd_free_bytes / (1024**3)}

        # Encontrar próxima entrada pendente
        pending = [
            e for e in self._entries.values()
            if e.state == DownloadState.PENDING.value
        ]
        if not pending:
            return None

        entry = pending[0]
        entry.state = DownloadState.DOWNLOADING.value
        entry.started_at = time.time()
        entry.retries += 1
        self._save_state()

        # Determinar tipo de download
        success = False
        error = ""

        if "drive.google.com" in entry.url:
            # Extrair file ID
            file_id = entry.url
            for pattern in ["/d/", "/file/d/", "id="]:
                if pattern in file_id:
                    idx = file_id.index(pattern) + len(pattern)
                    end = file_id[idx:].find("/")
                    if end == -1:
                        end = file_id[idx:].find("&")
                    if end == -1:
                        file_id = file_id[idx:]
                    else:
                        file_id = file_id[idx:idx+end]
                    break
            success, error = self._download_gdrive(file_id, Path(entry.dest_path))
        else:
            success, error = self._download_direct(entry.url, Path(entry.dest_path))

        if success:
            entry.state = DownloadState.VERIFYING.value
            dest = Path(entry.dest_path)
            entry.size_bytes = dest.stat().st_size
            entry.sha256 = self._file_hash(dest)

            # Verificar integridade básica
            if entry.size_bytes < 1024:
                entry.state = DownloadState.FAILED.value
                entry.error = "Arquivo muito pequeno (<1KB)"
                self._progress.total_failed += 1
            else:
                entry.state = DownloadState.COMPLETED.value
                entry.completed_at = time.time()
                self._progress.total_downloaded += 1
                self._progress.bytes_downloaded += entry.size_bytes
        else:
            if "auth" in error.lower() or "confirmação" in error.lower():
                entry.state = DownloadState.BLOCKED_AUTH.value
                self._progress.total_blocked_auth += 1
            elif entry.retries >= entry.max_retries:
                entry.state = DownloadState.FAILED.value
                entry.error = error
                self._progress.total_failed += 1
            else:
                entry.state = DownloadState.PENDING.value  # Retry
                entry.error = error

        self._save_state()
        return entry.to_dict()

    def process_batch(self, batch_size: int = 5) -> list[dict]:
        """Processa lote de entradas."""
        results = []
        for _ in range(batch_size):
            result = self.process_next()
            if result is None:
                break
            results.append(result)
        return results

    def retry_failed(self) -> int:
        """Reenfileira entradas falhadas para nova tentativa."""
        count = 0
        for entry in self._entries.values():
            if entry.state == DownloadState.FAILED.value and entry.retries < entry.max_retries:
                entry.state = DownloadState.PENDING.value
                entry.error = ""
                count += 1
        self._save_state()
        return count

    def get_progress(self) -> dict:
        """Retorna progresso atual."""
        self._progress.ssd_free_bytes = self._compute_ssd_free()
        self._progress.total_discovered = len(self._entries)
        by_state = {}
        for e in self._entries.values():
            by_state[e.state] = by_state.get(e.state, 0) + 1
        return {
            **self._progress.to_dict(),
            "by_state": by_state,
            "ssd_free_gb": round(self._progress.ssd_free_bytes / (1024**3), 2),
        }

    def get_entries(self, state: str = "", limit: int = 100) -> list[dict]:
        """Lista entradas filtradas por estado."""
        results = []
        for e in sorted(self._entries.values(), key=lambda x: x.created_at, reverse=True):
            if state and e.state != state:
                continue
            results.append(e.to_dict())
            if len(results) >= limit:
                break
        return results

    def save_manifest(self, pack_name: str, metadata: dict) -> str:
        """Salva manifesto do pack importado."""
        manifest = {
            "pack_name": pack_name,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "metadata": metadata,
            "entries_count": sum(
                1 for e in self._entries.values()
                if e.source_pack == pack_name
            ),
            "completed_count": sum(
                1 for e in self._entries.values()
                if e.source_pack == pack_name
                and e.state == DownloadState.COMPLETED.value
            ),
        }
        path = self.state_dir / f"manifest_{pack_name}.json"
        path.write_text(json.dumps(manifest, indent=2))
        return str(path)

    def fetch_authenticated_catalog(self, url: str = "https://monetizegta6.vercel.app/membros/pro/") -> dict:
        """Busca catálogo autenticado via curl com cookies de sessão.

        Returns dict with 'html', 'entries', 'error' keys.
        Cookies must be set via self.cookies before calling.
        """
        if not self.cookies:
            return {"html": "", "entries": [], "error": "Cookies não configurados. Forneça cookies de sessão autenticada."}

        try:
            result = subprocess.run(
                ["curl", "-s", "-S", "-L", "--max-time", "30",
                 "-H", f"Cookie: {self.cookies}",
                 "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                 url],
                capture_output=True, text=True, timeout=45
            )
            html = result.stdout
            if not html or len(html) < 1000:
                return {"html": html, "entries": [], "error": f"Resposta vazia ou muito curta ({len(html)} bytes). Cookies podem estar expirados."}

            # Check for login redirect or auth failure
            if "sign in" in html.lower()[:2000] or "login" in html.lower()[:2000]:
                return {"html": html, "entries": [], "error": "Redirecionado para login. Cookies expirados ou inválidos."}

            entries = self.parse_monetizegta6_catalog(html)
            return {"html": html, "entries": entries, "error": None}

        except subprocess.TimeoutExpired:
            return {"html": "", "entries": [], "error": "Timeout ao acessar plataforma"}
        except Exception as e:
            return {"html": "", "entries": [], "error": str(e)}

    def parse_monetizegta6_catalog(self, html: str) -> list[dict]:
        """Extrai entradas de catálogo da plataforma monetizegta6."""
        import re
        entries = []
        seen_ids = set()

        # Extrair links do Google Drive
        matches = re.findall(r'https://drive\.google\.com/(?:file/d/|uc\?id=)([a-zA-Z0-9_-]+)', html)
        for file_id in matches:
            if file_id in seen_ids:
                continue
            seen_ids.add(file_id)
            entries.append({
                "url": f"https://drive.google.com/file/d/{file_id}",
                "filename": f"gta6_{file_id[:8]}.mp4",
                "source_pack": "monetizegta6_gta6",
                "category": "gta6",
                "tags": ["gta6", "leonida"],
            })

        # Extrair URLs de vídeo diretas
        video_re = r'https?://[^"\'<>\s]*?\.(mp4|webm|mov)(?:[^"\'<>\s]*)?'
        for match in re.finditer(video_re, html, re.IGNORECASE):
            url = match.group(0)
            if "drive.google.com" in url:
                continue
            if url in seen_ids:
                continue
            seen_ids.add(url)
            fname = url.split("/")[-1].split("?")[0]
            entries.append({
                "url": url,
                "filename": fname or f"video_{len(entries)}.mp4",
                "source_pack": "monetizegta6_gta6",
                "category": "gta6",
                "tags": ["gta6"],
            })

        return entries