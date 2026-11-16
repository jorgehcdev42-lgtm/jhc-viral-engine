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
import threading
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
    """Importador massivo reutilizável para packs de vídeos e imagens."""

    PROGRESS_FILE = "import_progress.json"
    ENTRIES_FILE = "download_entries.json"
    MANIFEST_FILE = "pack_manifest.json"
    IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

    MIN_SSD_FREE_BYTES = 2 * 1024 * 1024 * 1024  # 2GB reserva segura

    def __init__(self, ssd_root: str, data_root: str = "data", cookies: str = "", max_concurrent: int = 2):
        self.ssd_root = Path(ssd_root)
        self.data_root = Path(data_root)
        self.import_dir = self.data_root / "bulk_import"
        self.downloads_dir = self.ssd_root / "JHC-VIRAL-IMPORTS"
        self.state_dir = self.import_dir / "state"
        self.cookies = cookies  # Cookie header string for authenticated requests
        self.max_concurrent = max_concurrent
        self._semaphore = threading.Semaphore(max_concurrent)

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

    def load_catalog_from_file(self, catalog_path: str, target_dir: str = "", max_entries: int = 0) -> dict:
        """Carrega catálogo JSON local (pro_catalog.json) e adiciona à fila.

        Args:
            catalog_path: Caminho para arquivo JSON com lista de entradas
            target_dir: Subpasta dentro de downloads_dir (ex: 'VIDEOS CORTES')
            max_entries: Limite de entradas a carregar (0 = todas)

        Returns:
            {"loaded": int, "videos": int, "images": int, "skipped": int}
        """
        path = Path(catalog_path)
        if not path.exists():
            return {"error": f"Arquivo não encontrado: {catalog_path}", "loaded": 0}

        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            return {"error": f"JSON inválido: {e}", "loaded": 0}

        if not isinstance(data, list):
            return {"error": "Catálogo deve ser uma lista JSON", "loaded": 0}

        # Determinar diretório de destino
        if target_dir:
            dest_base = self.ssd_root / target_dir
        else:
            dest_base = self.downloads_dir / "monetizegta6_pack"
        dest_base.mkdir(parents=True, exist_ok=True)

        loaded = 0
        videos = 0
        images = 0
        skipped = 0

        for item in data:
            if max_entries > 0 and loaded >= max_entries:
                break

            drive_id = item.get("drive", "")
            title = item.get("t", "untitled")
            item_type = item.get("type", "v")
            is_hd = item.get("hd", 0)

            if not drive_id:
                skipped += 1
                continue

            # Construir URL de download autenticada
            download_url = f"https://drive.usercontent.google.com/download?id={drive_id}&export=download&confirm=t"

            # Verificar duplicata por drive_id (não por URL completa)
            existing_keys = [k for k in self._entries.keys() if drive_id in k]
            if existing_keys:
                skipped += 1
                continue

            # Determinar extensão e nome do arquivo
            safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in title).strip()
            if item_type == "img":
                ext = ".jpg"
                images += 1
            else:
                ext = ".mp4"
                videos += 1

            filename = f"{safe_title}{ext}"
            dest_path = dest_base / filename

            # Evitar colisão de nomes
            counter = 1
            while dest_path.exists() or any(e.dest_path == str(dest_path) for e in self._entries.values()):
                filename = f"{safe_title}_{counter:03d}{ext}"
                dest_path = dest_base / filename
                counter += 1

            entry = DownloadEntry(
                url=download_url,
                filename=filename,
                dest_path=str(dest_path),
                tags=[f"hd={is_hd}", f"type={item_type}"] if is_hd else [f"type={item_type}"],
                category="cortes" if item_type != "img" else "imagens",
                source_pack="monetizegta6_gta6",
                created_at=time.time(),
            )
            self._entries[download_url] = entry
            loaded += 1

        self._progress.total_discovered = len(self._entries)
        self._progress.total_duplicates += skipped
        self._save_state()

        return {
            "loaded": loaded,
            "videos": videos,
            "images": images,
            "skipped": skipped,
            "total_in_queue": len(self._entries),
            "dest_dir": str(dest_base),
        }

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

    def _backoff_delay(self, retries: int) -> float:
        """Backoff exponencial: 2^retries segundos, max 60s."""
        return min(2 ** retries, 60)

    def process_next(self) -> Optional[dict]:
        """Processa próxima entrada pendente. Retorna resultado ou None se fila vazia."""
        self._progress.ssd_free_bytes = self._compute_ssd_free()

        # Verificar espaço mínimo com reserva segura (2GB)
        if self._progress.ssd_free_bytes < self.MIN_SSD_FREE_BYTES:
            free_gb = self._progress.ssd_free_bytes / (1024**3)
            return {
                "error": f"Espaço insuficiente no SSD ({free_gb:.1f}GB livres, mínimo {self.MIN_SSD_FREE_BYTES // (1024**3)}GB)",
                "free_gb": free_gb,
                "paused": True,
            }

        # Pausa verificada
        if self._progress.is_paused:
            return {"error": "Importação pausada", "paused": True}

        # Encontrar próxima entrada pendente
        pending = [
            e for e in self._entries.values()
            if e.state == DownloadState.PENDING.value
        ]
        if not pending:
            return None

        entry = pending[0]

        # Backoff antes de retry
        if entry.retries > 0:
            delay = self._backoff_delay(entry.retries)
            time.sleep(delay)

        # Adquire semaphore para limitar concorrência
        self._semaphore.acquire()
        try:
            entry.state = DownloadState.DOWNLOADING.value
            entry.started_at = time.time()
            entry.retries += 1
            self._save_state()

            # Determinar tipo de download
            success = False
            error = ""

            if "drive.usercontent.google.com" in entry.url or "drive.google.com" in entry.url:
                # Extrair file ID da URL autenticada ou padrão
                file_id = entry.url
                for pattern in ["id=", "/d/", "/file/d/"]:
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
            elif self._is_image_url(entry.url):
                success, error = self._download_image(entry.url, Path(entry.dest_path))
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
        finally:
            self._semaphore.release()

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

    def pause(self) -> dict:
        """Pausa importação. Downloads em andamento terminam, novos não iniciam."""
        self._progress.is_paused = True
        self._progress.is_running = False
        self._save_state()
        return {"paused": True, "message": "Importação pausada. Use resume() para continuar."}

    def resume(self) -> dict:
        """Retoma importação pausada."""
        self._progress.is_paused = False
        self._progress.is_running = True
        self._save_state()
        return {"paused": False, "message": "Importação retomada."}

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

    def _is_image_url(self, url: str) -> bool:
        """Verifica se URL aponta para imagem baseada na extensão."""
        lower = url.lower().split("?")[0]
        return any(lower.endswith(ext) for ext in self.IMAGE_EXTS)

    def _download_image(self, url: str, dest: Path) -> tuple[bool, str]:
        """Baixa imagem via curl com validação de formato."""
        try:
            result = subprocess.run(
                ["curl", "-L", "-o", str(dest), "-s", "-S",
                 "--max-time", "120", "--retry", "2", url],
                capture_output=True, text=True, timeout=140
            )
            if dest.exists() and dest.stat().st_size > 512:
                # Verificar magic bytes para confirmar que é imagem
                with open(dest, "rb") as f:
                    header = f.read(16)
                is_jpg = header[:2] == b"\xff\xd8"
                is_png = header[:8] == b"\x89PNG\r\n\x1a\n"
                is_webp = header[:4] == b"RIFF" and header[8:12] == b"WEBP"
                is_gif = header[:3] in (b"GIF", b"GIF")
                if is_jpg or is_png or is_webp or is_gif:
                    return True, ""
                else:
                    # Pode ser SVG ou outro formato válido; aceita se > 1KB
                    if dest.stat().st_size > 1024:
                        return True, ""
                    dest.unlink(missing_ok=True)
                    return False, "Arquivo não é imagem válida"
            else:
                dest.unlink(missing_ok=True)
                return False, "Download falhou ou arquivo muito pequeno"
        except subprocess.TimeoutExpired:
            return False, "Timeout"
        except Exception as e:
            return False, str(e)

    def parse_monetizegta6_catalog(self, html: str) -> list[dict]:
        """Extrai entradas de catálogo da plataforma monetizegta6 (vídeos + imagens)."""
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

        # Extrair URLs de imagens (thumbnails, banners, etc.)
        img_re = r'https?://[^"\'<>\s]*?\.(jpg|jpeg|png|webp|gif)(?:[^"\'<>\s]*)?'
        for match in re.finditer(img_re, html, re.IGNORECASE):
            url = match.group(0)
            if url in seen_ids:
                continue
            # Skip tiny icons and tracking pixels
            if any(x in url.lower() for x in ['icon', 'pixel', 'tracking', '1x1', 'spacer']):
                continue
            seen_ids.add(url)
            fname = url.split("/")[-1].split("?")[0]
            ext = "." + match.group(1).lower()
            if not fname.endswith(ext):
                fname = f"img_{len(entries)}{ext}"
            entries.append({
                "url": url,
                "filename": fname,
                "source_pack": "monetizegta6_gta6",
                "category": "images",
                "tags": ["gta6", "image"],
            })

        # Extrair thumbnails do Google Drive (thumbnail?id=...)
        thumb_re = r'https://drive\.google\.com/thumbnail\?id=([a-zA-Z0-9_-]+)'
        for match in re.finditer(thumb_re, html):
            file_id = match.group(1)
            key = f"gdrive_thumb_{file_id}"
            if key in seen_ids:
                continue
            seen_ids.add(key)
            entries.append({
                "url": f"https://drive.google.com/thumbnail?id={file_id}&sz=w1000",
                "filename": f"gta6_thumb_{file_id[:8]}.jpg",
                "source_pack": "monetizegta6_gta6",
                "category": "images",
                "tags": ["gta6", "thumbnail"],
            })

        return entries