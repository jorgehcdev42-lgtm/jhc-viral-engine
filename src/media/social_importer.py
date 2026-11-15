"""Social Media Importer — MISSÃO 018.

Importa vídeos de plataformas sociais por URL:
- Suporte a Instagram (Reels, Posts, Stories), YouTube (Shorts, vídeos), TikTok
- Extração via yt-dlp com fallback para ffmpeg direto
- Metadados automáticos (título, autor, duração, views quando disponível)
- Download em qualidade máxima compatível
- Organização automática por plataforma e perfil
- Integração com ReferenceLab para análise pós-importação
- Cache local no SSD para evitar re-downloads

Uso:
    importer = SocialImporter(data_root)
    result = importer.import_video("https://instagram.com/reel/ABC123")
    print(result.local_path, result.metadata)
"""

import json
import subprocess
import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from datetime import datetime


@dataclass
class ImportMetadata:
    """Metadados extraídos do vídeo importado."""
    source_url: str
    platform: str  # "instagram", "youtube", "tiktok", "unknown"
    title: str
    author: str
    duration_sec: float
    width: int
    height: int
    fps: float
    file_size_mb: float
    upload_date: str  # YYYY-MM-DD se disponível
    view_count: int | None = None
    like_count: int | None = None
    description: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class ImportResult:
    """Resultado da importação de um vídeo."""
    local_path: str
    metadata: ImportMetadata
    imported_at: str  # ISO timestamp
    cache_key: str  # hash da URL para cache lookup
    was_cached: bool = False
    analysis_ready: bool = True  # pronto para ReferenceLab


class SocialImporter:
    """Importador de vídeos de plataformas sociais."""

    PLATFORM_PATTERNS = {
        "instagram": ["instagram.com", "instagr.am"],
        "youtube": ["youtube.com", "youtu.be", "youtube-nocookie.com"],
        "tiktok": ["tiktok.com", "vm.tiktok.com"],
    }

    def __init__(self, data_root: Path | str):
        self.data_root = Path(data_root)
        self.imports_dir = self.data_root / "imports"
        self.imports_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir = self.data_root / "cache" / "social"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.meta_dir = self.data_root / "imports_meta"
        self.meta_dir.mkdir(parents=True, exist_ok=True)

    def import_video(
        self,
        url: str,
        quality: str = "best",
        use_cache: bool = True,
    ) -> ImportResult:
        """Importa um vídeo de uma plataforma social."""
        if not url or not url.startswith("http"):
            raise ValueError(f"URL inválida: {url}")

        platform = self._detect_platform(url)
        cache_key = self._url_hash(url)

        # Verifica cache
        if use_cache:
            cached = self._check_cache(cache_key, platform)
            if cached:
                meta = self._load_metadata(cache_key)
                if meta:
                    return ImportResult(
                        local_path=str(cached),
                        metadata=meta,
                        imported_at=datetime.now().isoformat(),
                        cache_key=cache_key,
                        was_cached=True,
                    )

        # Download via yt-dlp
        output_template = str(self.imports_dir / f"{platform}_{cache_key}_%(title).50s.%(ext)s")
        video_path = self._download_ytdlp(url, output_template, quality)

        if not video_path or not video_path.exists():
            raise RuntimeError(f"Falha no download de: {url}")

        # Extrai metadados
        metadata = self._extract_metadata(video_path, url, platform)

        # Salva metadados no cache
        self._save_metadata(cache_key, metadata)

        return ImportResult(
            local_path=str(video_path),
            metadata=metadata,
            imported_at=datetime.now().isoformat(),
            cache_key=cache_key,
            was_cached=False,
        )

    def import_batch(
        self,
        urls: list[str],
        quality: str = "best",
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        """Importa múltiplos vídeos em lote."""
        results = []
        for url in urls:
            try:
                result = self.import_video(url, quality=quality, use_cache=use_cache)
                results.append({
                    "url": url,
                    "status": "success",
                    "local_path": result.local_path,
                    "platform": result.metadata.platform,
                    "duration": result.metadata.duration_sec,
                    "cached": result.was_cached,
                })
            except Exception as e:
                results.append({
                    "url": url,
                    "status": "error",
                    "error": str(e),
                })
        return results

    def list_imports(self) -> list[dict]:
        """Lista todos os vídeos importados."""
        results = []
        for f in sorted(self.imports_dir.glob("*")):
            if f.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov"):
                size_mb = f.stat().st_size / (1024 * 1024)
                dur = self._get_duration(f)
                # Tenta carregar metadados
                meta = self._find_metadata_for_file(f)
                results.append({
                    "file": str(f),
                    "name": f.stem,
                    "size_mb": round(size_mb, 2),
                    "duration_sec": round(dur, 2),
                    "platform": meta.get("platform", "unknown") if meta else "unknown",
                    "author": meta.get("author", "") if meta else "",
                    "title": meta.get("title", "") if meta else "",
                })
        return results

    def get_import_stats(self) -> dict:
        """Estatísticas dos imports."""
        imports = self.list_imports()
        by_platform: dict[str, int] = {}
        total_size = 0.0
        total_duration = 0.0
        for imp in imports:
            plat = imp.get("platform", "unknown")
            by_platform[plat] = by_platform.get(plat, 0) + 1
            total_size += imp.get("size_mb", 0)
            total_duration += imp.get("duration_sec", 0)
        return {
            "total_imports": len(imports),
            "by_platform": by_platform,
            "total_size_mb": round(total_size, 2),
            "total_duration_sec": round(total_duration, 2),
            "cache_entries": len(list(self.cache_dir.glob("*.json"))),
        }

    # --- Métodos internos ---

    def _detect_platform(self, url: str) -> str:
        """Detecta a plataforma a partir da URL."""
        url_lower = url.lower()
        for platform, patterns in self.PLATFORM_PATTERNS.items():
            for pattern in patterns:
                if pattern in url_lower:
                    return platform
        return "unknown"

    def _url_hash(self, url: str) -> str:
        """Gera hash curto da URL para nome de arquivo e cache."""
        return hashlib.sha256(url.encode()).hexdigest()[:16]

    def _check_cache(self, cache_key: str, platform: str) -> Path | None:
        """Verifica se já existe um arquivo em cache para esta URL."""
        # Procura por arquivos com o cache_key no nome
        for f in self.imports_dir.glob(f"{platform}_{cache_key}_*"):
            if f.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov") and f.exists():
                return f
        return None

    def _download_ytdlp(
        self, url: str, output_template: str, quality: str
    ) -> Path | None:
        """Download via yt-dlp."""
        format_spec = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
        if quality == "worst":
            format_spec = "worst"

        cmd = [
            "yt-dlp",
            "--no-playlist",
            "-f", format_spec,
            "--merge-output-format", "mp4",
            "-o", output_template,
            "--no-warnings",
            "--restrict-filenames",
            url,
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300
            )
            if result.returncode != 0:
                # Fallback: tenta formato mais simples
                cmd_fallback = [
                    "yt-dlp", "--no-playlist",
                    "-f", "best",
                    "-o", output_template,
                    "--restrict-filenames",
                    url,
                ]
                result = subprocess.run(
                    cmd_fallback, capture_output=True, text=True, timeout=300
                )
                if result.returncode != 0:
                    return None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

        # Encontra o arquivo baixado
        stem = Path(output_template).parent
        cache_key = output_template.split("_")[1] if "_" in output_template else ""
        for f in sorted(stem.glob(f"*{cache_key}*"), reverse=True):
            if f.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov"):
                return f

        # Busca genérica
        for f in sorted(self.imports_dir.glob("*.mp4"), reverse=True):
            if f.stat().st_mtime > (datetime.now().timestamp() - 60):
                return f

        return None

    def _extract_metadata(
        self, video_path: Path, url: str, platform: str
    ) -> ImportMetadata:
        """Extrai metadados do vídeo baixado."""
        duration = self._get_duration(video_path)
        probe = self._ffprobe(video_path)
        file_size = video_path.stat().st_size / (1024 * 1024)

        # Tenta extrair metadados via yt-dlp --dump-json
        title = video_path.stem
        author = ""
        upload_date = ""
        view_count = None
        like_count = None
        description = ""
        tags: list[str] = []

        try:
            cmd = ["yt-dlp", "--dump-json", "--no-download", url]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                info = json.loads(result.stdout)
                title = info.get("title", title)[:100]
                author = info.get("uploader", info.get("channel", ""))
                upload_date = info.get("upload_date", "")
                if upload_date and len(upload_date) == 8:
                    upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
                view_count = info.get("view_count")
                like_count = info.get("like_count")
                description = info.get("description", "")[:500]
                tags = info.get("tags", [])[:20]
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
            pass

        return ImportMetadata(
            source_url=url,
            platform=platform,
            title=title,
            author=author,
            duration_sec=round(duration, 2),
            width=int(probe.get("width", 0)),
            height=int(probe.get("height", 0)),
            fps=float(probe.get("fps", 30)),
            file_size_mb=round(file_size, 2),
            upload_date=upload_date,
            view_count=view_count,
            like_count=like_count,
            description=description,
            tags=tags,
        )

    def _save_metadata(self, cache_key: str, metadata: ImportMetadata) -> None:
        """Salva metadados no diretório de cache."""
        out = self.meta_dir / f"{cache_key}.json"
        out.write_text(
            json.dumps(asdict(metadata), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_metadata(self, cache_key: str) -> ImportMetadata | None:
        """Carrega metadados do cache."""
        path = self.meta_dir / f"{cache_key}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ImportMetadata(**data)
        except (json.JSONDecodeError, TypeError):
            return None

    def _find_metadata_for_file(self, filepath: Path) -> dict | None:
        """Tenta encontrar metadados associados a um arquivo."""
        name = filepath.stem
        # Procura por cache_key no nome do arquivo
        parts = name.split("_")
        if len(parts) >= 2:
            cache_key = parts[1]
            meta_path = self.meta_dir / f"{cache_key}.json"
            if meta_path.exists():
                try:
                    return json.loads(meta_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pass
        return None

    def _get_duration(self, path: Path) -> float:
        """Duração do vídeo via ffprobe."""
        cmd = [
            "ffprobe", "-v", "quiet", "-show_entries",
            "format=duration", "-of", "csv=p=0", str(path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            return float(result.stdout.strip())
        except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
            return 0.0

    def _ffprobe(self, path: Path) -> dict:
        """Extrai metadados técnicos via ffprobe."""
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", str(path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            data = json.loads(result.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            return {"width": 0, "height": 0, "fps": 30}

        video = next(
            (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
            {},
        )
        fps_str = video.get("r_frame_rate", "30/1")
        fps = 30.0
        try:
            if "/" in fps_str:
                n, d = fps_str.split("/")
                fps = float(n) / float(d)
            else:
                fps = float(fps_str)
        except (ValueError, ZeroDivisionError):
            pass

        return {
            "width": video.get("width", 0),
            "height": video.get("height", 0),
            "fps": round(fps, 2),
        }