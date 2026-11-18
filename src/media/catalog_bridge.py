"""Ponte entre vídeos importados (URL/Radar) e SmartCatalog + Pipeline.

MISSÃO 040 FASE 3.
Registra vídeos baixados no catálogo para entrada automática na pipeline.
"""

import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DATA_ROOT = Path(__file__).resolve().parent.parent.parent / "data"


class CatalogBridge:
    """Integra vídeos importados ao SmartCatalog e ProductionPipeline."""

    def __init__(self, data_root: Optional[Path] = None):
        self.data_root = data_root or DATA_ROOT
        self.import_dir = self.data_root / "imported_videos"
        self.catalog_index_path = self.data_root / "bulk_import" / "state" / "catalog_index.json"
        self._ffprobe_bin = self._find_ffprobe()

    def _find_ffprobe(self) -> str:
        import shutil
        candidates = [shutil.which("ffprobe"), "/opt/homebrew/bin/ffprobe", "/usr/local/bin/ffprobe"]
        for c in candidates:
            if c and Path(c).exists():
                return c
        return "ffprobe"

    def get_video_info(self, path: str) -> dict:
        """Extrai metadata de vídeo via ffprobe."""
        try:
            cmd = [
                self._ffprobe_bin, "-v", "quiet", "-print_format", "json",
                "-show_streams", "-show_format", str(path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode != 0:
                return {}
            data = json.loads(result.stdout)
            video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
            fmt = data.get("format", {})
            return {
                "width": int(video_stream.get("width", 0)),
                "height": int(video_stream.get("height", 0)),
                "duration": float(fmt.get("duration", video_stream.get("duration", 0))),
                "codec": video_stream.get("codec_name", "unknown"),
                "fps": eval(video_stream.get("r_frame_rate", "0/1")) if "/" in video_stream.get("r_frame_rate", "") else float(video_stream.get("r_frame_rate", 0)),
                "size_bytes": int(fmt.get("size", Path(path).stat().st_size)),
            }
        except Exception as e:
            logger.warning(f"ffprobe failed for {path}: {e}")
            return {}

    def register_imported_video(
        self,
        file_path: str,
        source_url: str = "",
        title: str = "",
        author: str = "",
        platform: str = "youtube",
    ) -> bool:
        """Registra vídeo importado no catálogo do SmartCatalog."""
        p = Path(file_path)
        if not p.exists():
            logger.error(f"Arquivo não existe: {file_path}")
            return False

        info = self.get_video_info(file_path)
        if not info:
            logger.error(f"Não foi possível extrair metadata de {file_path}")
            return False

        # Construir entrada compatível com CatalogEntry
        entry = {
            "filename": p.name,
            "path": str(p.resolve()),
            "type": "video",
            "category": "imported",
            "source_pack": f"url_import_{platform}",
            "hd": info.get("height", 0) >= 720,
            "size_bytes": info.get("size_bytes", p.stat().st_size),
            "width": info.get("width", 0),
            "height": info.get("height", 0),
            "duration": info.get("duration", 0),
            "codec": info.get("codec", "h264"),
            "fps": round(info.get("fps", 30)),
            "autoreels_compatible": True,
            "metadata": {
                "source_url": source_url,
                "author": author,
                "title": title,
                "platform": platform,
                "imported_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            },
        }

        # Carregar catálogo existente
        entries = []
        if self.catalog_index_path.exists():
            try:
                entries = json.loads(self.catalog_index_path.read_text())
            except (json.JSONDecodeError, OSError):
                entries = []

        # Verificar duplicata por filename
        existing_filenames = {e.get("filename") for e in entries}
        if p.name in existing_filenames:
            logger.info(f"Vídeo já registrado no catálogo: {p.name}")
            return True

        entries.append(entry)
        self.catalog_index_path.parent.mkdir(parents=True, exist_ok=True)
        self.catalog_index_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False))
        logger.info(f"Registrado no catálogo: {p.name} ({info.get('width')}x{info.get('height')}, {info.get('duration'):.1f}s)")
        return True

    def create_production_job_from_import(
        self,
        file_path: str,
        title: str = "",
        platform: str = "tiktok",
        market: str = "br",
    ) -> Optional[str]:
        """Cria job de produção a partir de vídeo importado."""
        from src.production.pipeline import ProductionPipeline

        p = Path(file_path)
        if not p.exists():
            logger.error(f"Arquivo não existe: {file_path}")
            return None

        pipeline = ProductionPipeline(data_root=str(self.data_root))
        job = pipeline.create_job(
            video_path=str(p.resolve()),
            platform=platform,
            market=market,
            title=title or f"Imported Reel {int(time.time()) % 10000}",
        )

        if job.status != "failed":
            logger.info(f"Job criado: {job.job_id} para {p.name}")
            return job.job_id
        else:
            logger.error(f"Falha ao criar job: {job.error}")
            return None

    def auto_process_import(
        self,
        file_path: str,
        source_url: str = "",
        title: str = "",
        author: str = "",
        platform: str = "youtube",
        auto_produce: bool = True,
    ) -> dict:
        """Fluxo completo: registrar no catálogo + criar job de produção."""
        result = {"registered": False, "job_id": None, "error": ""}

        # 1. Registrar no catálogo
        registered = self.register_imported_video(
            file_path=file_path,
            source_url=source_url,
            title=title,
            author=author,
            platform=platform,
        )
        result["registered"] = registered

        if not registered:
            result["error"] = "Falha ao registrar no catálogo"
            return result

        # 2. Criar job de produção (se solicitado)
        if auto_produce:
            job_id = self.create_production_job_from_import(
                file_path=file_path,
                title=title,
                platform="tiktok",
                market="br",
            )
            result["job_id"] = job_id
            if not job_id:
                result["error"] = "Registrado mas falha ao criar job de produção"

        return result

    def get_pending_imports(self) -> list[dict]:
        """Lista vídeos importados ainda não registrados no catálogo."""
        if not self.import_dir.exists():
            return []

        # Carregar filenames já catalogados
        cataloged = set()
        if self.catalog_index_path.exists():
            try:
                entries = json.loads(self.catalog_index_path.read_text())
                cataloged = {e.get("filename") for e in entries}
            except (json.JSONDecodeError, OSError):
                pass

        pending = []
        for f in sorted(self.import_dir.glob("*.mp4")):
            if f.name not in cataloged:
                info = self.get_video_info(str(f))
                pending.append({
                    "filename": f.name,
                    "path": str(f),
                    "size_mb": round(f.stat().st_size / 1_048_576, 1),
                    "duration": info.get("duration", 0),
                    "resolution": f"{info.get('width', '?')}x{info.get('height', '?')}",
                })
        return pending