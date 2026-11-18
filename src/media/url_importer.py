"""Importador de vídeos por URL usando yt-dlp — MISSÃO 040 FASE 1.

Suporta YouTube, Instagram e outras plataformas via yt-dlp.
Integra com SmartCatalog para deduplicação e indexação automática.
"""

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DATA_ROOT = Path(__file__).resolve().parent.parent.parent / "data"
IMPORT_DIR = DATA_ROOT / "imported_videos"
IMPORT_HISTORY_FILE = DATA_ROOT / "import_history.json"

SUPPORTED_PLATFORMS = {
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "instagram.com": "instagram",
    "tiktok.com": "tiktok",
    "twitter.com": "twitter",
    "x.com": "twitter",
    "facebook.com": "facebook",
    "vimeo.com": "vimeo",
}


@dataclass
class ImportEntry:
    url: str
    platform: str
    status: str = "pending"  # pending, downloading, completed, failed, duplicate
    title: str = ""
    author: str = ""
    duration: float = 0.0
    resolution: str = ""
    thumbnail: str = ""
    output_path: str = ""
    file_size: int = 0
    sha256: str = ""
    error: str = ""
    imported_at: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class UrlImporter:
    """Importa vídeos individuais por URL usando yt-dlp."""

    def __init__(self, data_root: Optional[Path] = None):
        self.data_root = data_root or DATA_ROOT
        self.import_dir = self.data_root / "imported_videos"
        self.import_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = self.data_root / "import_history.json"
        self._yt_dlp_bin = self._find_yt_dlp()

    def _find_yt_dlp(self) -> str:
        """Localiza binário yt-dlp no PATH ou locais conhecidos."""
        candidates = [
            shutil.which("yt-dlp"),
            "/opt/homebrew/bin/yt-dlp",
            "/usr/local/bin/yt-dlp",
            os.path.expanduser("~/Library/Python/3.15/bin/yt-dlp"),
            os.path.expanduser("~/Library/Python/3.14/bin/yt-dlp"),
            os.path.expanduser("~/Library/Python/3.13/bin/yt-dlp"),
        ]
        for c in candidates:
            if c and Path(c).exists():
                return c
        raise FileNotFoundError(
            "yt-dlp não encontrado. Instale: brew install yt-dlp"
        )

    def detect_platform(self, url: str) -> str:
        """Detecta plataforma a partir da URL."""
        url_lower = url.lower()
        for domain, platform in SUPPORTED_PLATFORMS.items():
            if domain in url_lower:
                return platform
        return "unknown"

    def fetch_metadata(self, url: str) -> dict:
        """Busca metadados do vídeo sem baixar (yt-dlp --dump-json)."""
        try:
            result = subprocess.run(
                [
                    self._yt_dlp_bin,
                    "--dump-json",
                    "--no-download",
                    "--quiet",
                    "--no-warnings",
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return {"error": f"yt-dlp metadata failed: {result.stderr[:500]}"}
            info = json.loads(result.stdout)
            return {
                "title": info.get("title", ""),
                "author": info.get("uploader", info.get("channel", "")),
                "duration": info.get("duration", 0),
                "resolution": f"{info.get('width', '?')}x{info.get('height', '?')}",
                "thumbnail": info.get("thumbnail", ""),
                "platform": info.get("extractor", self.detect_platform(url)),
                "view_count": info.get("view_count", 0),
                "upload_date": info.get("upload_date", ""),
                "description": info.get("description", "")[:500],
                "url": url,
            }
        except subprocess.TimeoutExpired:
            return {"error": "Timeout ao buscar metadados (>30s)"}
        except json.JSONDecodeError:
            return {"error": "Resposta inválida do yt-dlp"}
        except Exception as e:
            return {"error": str(e)}

    def is_duplicate(self, url: str) -> bool:
        """Verifica se URL já foi importada com sucesso."""
        history = self._load_history()
        for entry in history:
            if entry.get("url") == url and entry.get("status") == "completed":
                return True
        return False

    def download_video(self, url: str, progress_callback=None) -> ImportEntry:
        """Baixa vídeo via yt-dlp com formato otimizado para reels."""
        entry = ImportEntry(
            url=url,
            platform=self.detect_platform(url),
            status="downloading",
        )

        # Verificar duplicata
        if self.is_duplicate(url):
            entry.status = "duplicate"
            entry.error = "URL já importada anteriormente"
            self._save_entry(entry)
            return entry

        # Gerar nome de arquivo seguro
        safe_id = hashlib.md5(url.encode()).hexdigest()[:12]
        output_template = str(self.import_dir / f"{safe_id}_%(title).50s.%(ext)s")

        try:
            cmd = [
                self._yt_dlp_bin,
                "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best",
                "--merge-output-format", "mp4",
                "--output", output_template,
                "--no-playlist",
                "--quiet",
                "--no-warnings",
                "--newline",
                url,
            ]

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            start_time = time.time()
            last_progress = 0

            while process.poll() is None:
                line = process.stdout.readline()
                if line and progress_callback:
                    # Parse progress: [download] 45.2% of 120.50MiB at 5.2MiB/s ETA 00:12
                    match = re.search(r'\[download\]\s+([\d.]+)%', line)
                    if match:
                        pct = float(match.group(1))
                        if pct > last_progress + 5:
                            progress_callback(pct)
                            last_progress = pct

                # Timeout de 5 minutos
                if time.time() - start_time > 300:
                    process.kill()
                    entry.status = "failed"
                    entry.error = "Download timeout (>5min)"
                    self._save_entry(entry)
                    return entry

            rc = process.returncode
            if rc != 0:
                # Capturar output para diagnóstico (stderr foi merged em stdout)
                remaining_output = ""
                try:
                    remaining_output = process.stdout.read() if process.stdout else ""
                except Exception:
                    pass
                error_msg = f"yt-dlp exit code {rc}"
                for line in remaining_output.split("\n"):
                    if "ERROR:" in line:
                        error_msg = line.strip().replace("ERROR: ", "")[:200]
                        break
                entry.status = "failed"
                entry.error = error_msg
                self._save_entry(entry)
                return entry

            # Encontrar arquivo baixado
            downloaded = list(self.import_dir.glob(f"{safe_id}_*.mp4"))
            if not downloaded:
                entry.status = "failed"
                entry.error = "Arquivo não encontrado após download"
                self._save_entry(entry)
                return entry

            video_path = downloaded[0]
            entry.output_path = str(video_path)
            entry.file_size = video_path.stat().st_size

            # Calcular SHA-256 para deduplicação por conteúdo
            entry.sha256 = self._compute_sha256(video_path)

            # Buscar metadados pós-download
            meta = self.fetch_metadata(url)
            if "error" not in meta:
                entry.title = meta.get("title", video_path.stem)
                entry.author = meta.get("author", "")
                entry.duration = meta.get("duration", 0)
                entry.resolution = meta.get("resolution", "")
                entry.thumbnail = meta.get("thumbnail", "")
                entry.metadata = meta
            else:
                entry.title = video_path.stem

            entry.status = "completed"
            entry.imported_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            self._save_entry(entry)

            logger.info(f"Download concluído: {entry.title} ({entry.file_size} bytes)")
            return entry

        except Exception as e:
            entry.status = "failed"
            entry.error = str(e)
            self._save_entry(entry)
            logger.error(f"Falha no download de {url}: {e}")
            return entry

    def get_history(self, limit: int = 50, status_filter: str = "") -> list[dict]:
        """Retorna histórico de importações."""
        history = self._load_history()
        if status_filter:
            history = [h for h in history if h.get("status") == status_filter]
        # Mais recentes primeiro
        history.sort(key=lambda x: x.get("imported_at", ""), reverse=True)
        return history[:limit]

    def get_stats(self) -> dict:
        """Estatísticas de importação."""
        history = self._load_history()
        total = len(history)
        completed = sum(1 for h in history if h.get("status") == "completed")
        failed = sum(1 for h in history if h.get("status") == "failed")
        duplicates = sum(1 for h in history if h.get("status") == "duplicate")
        total_size = sum(h.get("file_size", 0) for h in history if h.get("status") == "completed")
        platforms = {}
        for h in history:
            p = h.get("platform", "unknown")
            platforms[p] = platforms.get(p, 0) + 1
        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "duplicates": duplicates,
            "total_size_mb": round(total_size / 1_048_576, 1),
            "platforms": platforms,
        }

    def delete_entry(self, url: str) -> bool:
        """Remove entrada do histórico e arquivo associado."""
        history = self._load_history()
        new_history = []
        deleted = False
        for h in history:
            if h.get("url") == url:
                # Remover arquivo
                path = h.get("output_path", "")
                if path and Path(path).exists():
                    Path(path).unlink(missing_ok=True)
                deleted = True
            else:
                new_history.append(h)
        if deleted:
            self._save_history(new_history)
        return deleted

    # --- Private ---

    def _load_history(self) -> list[dict]:
        if self.history_file.exists():
            try:
                return json.loads(self.history_file.read_text())
            except (json.JSONDecodeError, OSError):
                return []
        return []

    def _save_history(self, history: list[dict]) -> None:
        self.history_file.write_text(json.dumps(history, indent=2, ensure_ascii=False))

    def _save_entry(self, entry: ImportEntry) -> None:
        history = self._load_history()
        # Atualizar ou adicionar
        found = False
        for i, h in enumerate(history):
            if h.get("url") == entry.url:
                history[i] = entry.to_dict()
                found = True
                break
        if not found:
            history.append(entry.to_dict())
        self._save_history(history)

    def _compute_sha256(self, path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()