"""SSD Library Worker — Indexação segura de vídeos no SSD externo.

Worker local para MacBook M2 (8GB RAM). Processamento sequencial.
Indexação incremental com hash-based dedup. Thumbnails via ffmpeg.
Busca por tags, categorias e metadados. Controle de direitos.

NÃO acessa SSD diretamente do Render — apenas via API local ou upload.
"""

import os
import json
import time
import hashlib
import subprocess
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class VideoEntry:
    path: str
    filename: str
    size_mb: float
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    codec: str = ""
    has_audio: bool = False
    sha256_prefix: str = ""
    tags: list[str] = field(default_factory=list)
    category: str = "uncategorized"
    rights: str = "authorized"
    thumbnail: str = ""
    indexed_at: float = 0.0
    used_count: int = 0
    last_used: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class SSDLibraryWorker:
    """Worker seguro para indexação de vídeos no SSD."""

    SUPPORTED_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}

    def __init__(self, ssd_root: str, data_root: str = "data"):
        self.ssd_root = Path(ssd_root)
        self.data_root = Path(data_root)
        self.index_dir = self.data_root / "ssd_index"
        self.thumbs_dir = self.data_root / "ssd_thumbnails"
        self.index_file = self.index_dir / "library.json"
        self.hash_cache = self.index_dir / "hash_cache.json"

        for d in [self.index_dir, self.thumbs_dir]:
            d.mkdir(parents=True, exist_ok=True)

        self._entries: dict[str, VideoEntry] = {}
        self._hashes: dict[str, str] = {}
        self._load()

    def _load(self):
        if self.index_file.exists():
            try:
                data = json.loads(self.index_file.read_text())
                for item in data.get("entries", []):
                    entry = VideoEntry(**item)
                    self._entries[entry.path] = entry
            except Exception:
                pass

        if self.hash_cache.exists():
            try:
                self._hashes = json.loads(self.hash_cache.read_text())
            except Exception:
                pass

    def _save(self):
        data = {"entries": [e.to_dict() for e in self._entries.values()], "updated": time.time()}
        self.index_file.write_text(json.dumps(data, indent=2))
        self.hash_cache.write_text(json.dumps(self._hashes, indent=2))

    def _file_hash_prefix(self, path: Path) -> str:
        """Hash parcial (primeiros 1MB + últimos 1MB) para dedup rápida."""
        try:
            h = hashlib.sha256()
            size = path.stat().st_size
            with open(path, "rb") as f:
                h.update(f.read(1024 * 1024))
                if size > 2 * 1024 * 1024:
                    f.seek(-1024 * 1024, 2)
                    h.update(f.read(1024 * 1024))
            return h.hexdigest()[:16]
        except Exception:
            return ""

    def _probe_video(self, path: Path) -> dict:
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", str(path)
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                return json.loads(r.stdout)
        except Exception:
            pass
        return {}

    def _generate_thumbnail(self, video_path: Path) -> str:
        thumb_name = f"{video_path.stem}_thumb.jpg"
        thumb_path = self.thumbs_dir / thumb_name
        if thumb_path.exists():
            return str(thumb_path)

        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video_path), "-ss", "3", "-vframes", "1",
            "-q:v", "3", str(thumb_path)
        ]
        try:
            subprocess.run(cmd, timeout=15)
            if thumb_path.exists():
                return str(thumb_path)
        except Exception:
            pass
        return ""

    def validate_ssd_path(self) -> dict:
        """Valida se o caminho SSD existe e é acessível."""
        exists = self.ssd_root.exists()
        is_dir = self.ssd_root.is_dir() if exists else False
        video_count = 0
        if is_dir:
            for ext in self.SUPPORTED_EXTS:
                video_count += sum(1 for _ in self.ssd_root.rglob(f"*{ext}"))

        return {
            "valid": exists and is_dir,
            "path": str(self.ssd_root),
            "exists": exists,
            "is_directory": is_dir,
            "video_files_found": video_count,
        }

    def scan(self, max_files: int = 50, sequential_delay: float = 0.1) -> dict:
        """Indexação incremental com processamento sequencial."""
        if not self.ssd_root.exists():
            return {"error": f"Caminho não encontrado: {self.ssd_root}", "indexed": 0}

        new_count = 0
        skipped_dup = 0
        skipped_existing = 0
        errors = []

        files = []
        for ext in self.SUPPORTED_EXTS:
            files.extend(self.ssd_root.rglob(f"*{ext}"))

        files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0)

        for fpath in files[:max_files]:
            try:
                key = str(fpath)

                # Skip se já indexado e arquivo não mudou
                if key in self._entries:
                    mtime = fpath.stat().st_mtime
                    if mtime <= self._entries[key].indexed_at:
                        skipped_existing += 1
                        continue

                # Dedup por hash parcial
                h = self._file_hash_prefix(fpath)
                if h and h in self._hashes:
                    existing_path = self._hashes[h]
                    if existing_path != key and existing_path in self._entries:
                        skipped_dup += 1
                        continue

                # Probe vídeo
                probe = self._probe_video(fpath)
                vstream = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), {})
                astream = next((s for s in probe.get("streams", []) if s.get("codec_type") == "audio"), {})
                fmt = probe.get("format", {})

                dur = float(fmt.get("duration", 0))
                w = int(vstream.get("width", 0))
                ht = int(vstream.get("height", 0))
                fps_str = vstream.get("r_frame_rate", "30/1")
                try:
                    fps = eval(fps_str) if "/" in fps_str else float(fps_str)
                except Exception:
                    fps = 30.0

                # Thumbnail
                thumb = self._generate_thumbnail(fpath)

                entry = VideoEntry(
                    path=key,
                    filename=fpath.name,
                    size_mb=round(fpath.stat().st_size / (1024 * 1024), 2),
                    duration=dur,
                    width=w,
                    height=ht,
                    fps=fps,
                    codec=vstream.get("codec_name", ""),
                    has_audio=bool(astream),
                    sha256_prefix=h,
                    thumbnail=thumb,
                    indexed_at=time.time(),
                )

                self._entries[key] = entry
                if h:
                    self._hashes[h] = key
                new_count += 1

                # Delay sequencial para não sobrecarregar Mac
                time.sleep(sequential_delay)

            except Exception as e:
                errors.append({"file": str(fpath), "error": str(e)})

        self._save()

        return {
            "indexed": new_count,
            "skipped_existing": skipped_existing,
            "skipped_duplicate": skipped_dup,
            "errors": len(errors),
            "total_in_library": len(self._entries),
            "error_details": errors[:5],
        }

    def search(self, query: str = "", tags: list[str] | None = None,
               category: str = "", min_duration: float = 0,
               max_duration: float = 0, limit: int = 50) -> list[dict]:
        """Busca com filtros editoriais."""
        results = []
        q = query.lower()

        for entry in self._entries.values():
            if q and q not in entry.filename.lower() and q not in " ".join(entry.tags).lower():
                continue
            if tags and not any(t in entry.tags for t in tags):
                continue
            if category and entry.category != category:
                continue
            if min_duration and entry.duration < min_duration:
                continue
            if max_duration and entry.duration > max_duration:
                continue
            results.append(entry.to_dict())

        results.sort(key=lambda x: x["indexed_at"], reverse=True)
        return results[:limit]

    def get_stats(self) -> dict:
        total = len(self._entries)
        total_size = sum(e.size_mb for e in self._entries.values())
        total_dur = sum(e.duration for e in self._entries.values())
        cats = {}
        for e in self._entries.values():
            cats[e.category] = cats.get(e.category, 0) + 1

        return {
            "total_videos": total,
            "total_size_mb": round(total_size, 2),
            "total_duration_sec": round(total_dur, 2),
            "categories": cats,
            "unique_hashes": len(self._hashes),
            "duplicates_detected": total - len(self._hashes),
        }

    def update_tags(self, path: str, tags: list[str]) -> bool:
        if path in self._entries:
            self._entries[path].tags = tags
            self._save()
            return True
        return False

    def update_category(self, path: str, category: str) -> bool:
        if path in self._entries:
            self._entries[path].category = category
            self._save()
            return True
        return False

    def update_rights(self, path: str, rights: str) -> bool:
        if path in self._entries:
            self._entries[path].rights = rights
            self._save()
            return True
        return False

    def mark_used(self, path: str) -> bool:
        if path in self._entries:
            self._entries[path].used_count += 1
            self._entries[path].last_used = time.time()
            self._save()
            return True
        return False