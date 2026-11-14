"""JHC Smart Media Library — Professional audiovisual asset manager.

Indexes video files from local directories into a persistent SQLite catalog.
Supports recursive scanning, SHA-256 deduplication, ffprobe metadata extraction,
thumbnail generation, incremental reindexing, and tag-based search.

Designed for MacBook M2 8GB: sequential processing with configurable batch size,
no parallel ffprobe/thumbnail generation to avoid memory pressure.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = frozenset({
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv",
    ".wmv", ".m4v", ".ts", ".mts", ".m2ts",
})

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS media_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE NOT NULL,
    file_name TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    duration_seconds REAL,
    width INTEGER,
    height INTEGER,
    fps REAL,
    codec TEXT,
    pixel_format TEXT,
    bitrate INTEGER,
    thumbnail_path TEXT,
    tags TEXT DEFAULT '[]',
    category TEXT DEFAULT '',
    rights_status TEXT DEFAULT 'pending_authorization',
    source_directory TEXT NOT NULL,
    indexed_at REAL NOT NULL,
    last_verified_at REAL NOT NULL,
    is_corrupt INTEGER DEFAULT 0,
    notes TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_media_hash ON media_files(content_hash);
CREATE INDEX IF NOT EXISTS idx_media_category ON media_files(category);
CREATE INDEX IF NOT EXISTS idx_media_tags ON media_files(tags);
CREATE INDEX IF NOT EXISTS idx_media_rights ON media_files(rights_status);
CREATE INDEX IF NOT EXISTS idx_media_duration ON media_files(duration_seconds);
"""


@dataclass(frozen=True)
class MediaAsset:
    """Immutable record of a single media file in the library."""
    file_path: str
    file_name: str
    file_size: int
    content_hash: str
    duration_seconds: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    codec: Optional[str] = None
    pixel_format: Optional[str] = None
    bitrate: Optional[int] = None
    thumbnail_path: Optional[str] = None
    tags: tuple[str, ...] = ()
    category: str = ""
    rights_status: str = "pending_authorization"
    source_directory: str = ""
    indexed_at: float = 0.0
    last_verified_at: float = 0.0
    is_corrupt: bool = False
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "file_name": self.file_name,
            "file_size": self.file_size,
            "content_hash": self.content_hash,
            "duration_seconds": self.duration_seconds,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "codec": self.codec,
            "pixel_format": self.pixel_format,
            "bitrate": self.bitrate,
            "thumbnail_path": self.thumbnail_path,
            "tags": list(self.tags),
            "category": self.category,
            "rights_status": self.rights_status,
            "source_directory": self.source_directory,
            "indexed_at": self.indexed_at,
            "last_verified_at": self.last_verified_at,
            "is_corrupt": self.is_corrupt,
            "notes": self.notes,
        }


@dataclass
class IndexProgress:
    """Mutable progress tracker for long-running index operations."""
    total_files: int = 0
    scanned: int = 0
    indexed: int = 0
    skipped_duplicate: int = 0
    skipped_corrupt: int = 0
    errors: int = 0
    started_at: float = field(default_factory=time.time)

    @property
    def elapsed(self) -> float:
        return time.time() - self.started_at

    @property
    def percent(self) -> float:
        if self.total_files == 0:
            return 0.0
        return (self.scanned / self.total_files) * 100

    def summary(self) -> str:
        return (
            f"Indexed {self.indexed}/{self.total_files} "
            f"({self.percent:.1f}%) | "
            f"duplicates={self.skipped_duplicate} "
            f"corrupt={self.skipped_corrupt} "
            f"errors={self.errors} | "
            f"{self.elapsed:.1f}s"
        )


class SmartMediaLibrary:
    """Persistent media library with SQLite backend and ffprobe integration."""

    def __init__(self, db_path: Path, thumbnails_dir: Path) -> None:
        self.db_path = db_path
        self.thumbnails_dir = thumbnails_dir
        self.thumbnails_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize SQLite database with schema."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.executescript(DB_SCHEMA)
            conn.commit()
            logger.info("Media library DB initialized: %s", self.db_path)
        finally:
            conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    async def scan_directory(
        self,
        directory: Path,
        recursive: bool = True,
    ) -> list[Path]:
        """Discover video files in a directory."""
        if not directory.exists():
            logger.warning("Directory does not exist: %s", directory)
            return []

        videos: list[Path] = []
        if recursive:
            for ext in VIDEO_EXTENSIONS:
                videos.extend(directory.rglob(f"*{ext}"))
                videos.extend(directory.rglob(f"*{ext.upper()}"))
        else:
            for ext in VIDEO_EXTENSIONS:
                videos.extend(directory.glob(f"*{ext}"))
                videos.extend(directory.glob(f"*{ext.upper()}"))

        # Deduplicate by resolved path
        seen: set[Path] = set()
        unique: list[Path] = []
        for v in videos:
            resolved = v.resolve()
            if resolved not in seen:
                seen.add(resolved)
                unique.append(resolved)

        logger.info("Found %d video files in %s", len(unique), directory)
        return sorted(unique)

    @staticmethod
    def compute_file_hash(file_path: Path, chunk_size: int = 8192) -> str:
        """Compute SHA-256 hash of file content."""
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    async def probe_metadata(self, file_path: Path) -> dict:
        """Extract video metadata using ffprobe."""
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            logger.warning("ffprobe not found; skipping metadata extraction")
            return {}

        cmd = [
            ffprobe, "-v", "error",
            "-show_entries",
            "stream=codec_name,width,height,r_frame_rate,pix_fmt,duration,bit_rate",
            "-show_entries", "format=duration,size,bit_rate",
            "-of", "json",
            str(file_path),
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.warning("ffprobe failed for %s: %s", file_path.name, stderr.decode()[-200:])
            return {"is_corrupt": True}

        try:
            data = json.loads(stdout.decode())
        except json.JSONDecodeError:
            return {"is_corrupt": True}

        streams = data.get("streams", [])
        fmt = data.get("format", {})
        vs = next((s for s in streams if s.get("codec_name")), None)

        result: dict = {"is_corrupt": False}
        if vs:
            result["codec"] = vs.get("codec_name")
            result["width"] = vs.get("width")
            result["height"] = vs.get("height")
            result["pixel_format"] = vs.get("pix_fmt")

            r_frame_rate = vs.get("r_frame_rate", "0/1")
            if "/" in str(r_frame_rate):
                num, den = str(r_frame_rate).split("/")
                result["fps"] = float(num) / float(den) if float(den) > 0 else None
            else:
                result["fps"] = float(r_frame_rate) if r_frame_rate else None

            stream_dur = vs.get("duration")
            if stream_dur:
                result["duration_seconds"] = float(stream_dur)

        fmt_dur = fmt.get("duration")
        if fmt_dur and "duration_seconds" not in result:
            result["duration_seconds"] = float(fmt_dur)

        fmt_bitrate = fmt.get("bit_rate")
        if fmt_bitrate:
            result["bitrate"] = int(fmt_bitrate)

        return result

    async def generate_thumbnail(self, file_path: Path) -> Optional[Path]:
        """Generate a thumbnail frame from the video."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return None

        thumb_name = hashlib.md5(str(file_path).encode()).hexdigest()[:12] + ".jpg"
        thumb_path = self.thumbnails_dir / thumb_name

        if thumb_path.exists():
            return thumb_path

        cmd = [
            ffmpeg, "-y",
            "-i", str(file_path),
            "-ss", "00:00:02",
            "-vframes", "1",
            "-vf", "scale=320:-1",
            "-q:v", "5",
            str(thumb_path),
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0 or not thumb_path.exists():
            logger.debug("Thumbnail generation failed for %s", file_path.name)
            return None

        return thumb_path

    async def index_file(
        self,
        file_path: Path,
        source_directory: str,
        skip_existing: bool = True,
    ) -> Optional[MediaAsset]:
        """Index a single video file into the library."""
        resolved = str(file_path.resolve())

        if skip_existing:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT id FROM media_files WHERE file_path = ?", (resolved,)
                ).fetchone()
                if row:
                    return None  # Already indexed
            finally:
                conn.close()

        now = time.time()
        file_size = file_path.stat().st_size
        content_hash = self.compute_file_hash(file_path)

        # Check hash duplicate
        conn = self._get_conn()
        try:
            dup = conn.execute(
                "SELECT file_path FROM media_files WHERE content_hash = ?",
                (content_hash,),
            ).fetchone()
            if dup:
                logger.debug("Duplicate hash for %s (same as %s)", file_path.name, dup["file_path"])
                return None
        finally:
            conn.close()

        # Probe metadata
        meta = await self.probe_metadata(file_path)
        is_corrupt = meta.get("is_corrupt", False)

        # Generate thumbnail (skip for corrupt files)
        thumb_path = None
        if not is_corrupt:
            thumb = await self.generate_thumbnail(file_path)
            if thumb:
                thumb_path = str(thumb)

        asset = MediaAsset(
            file_path=resolved,
            file_name=file_path.name,
            file_size=file_size,
            content_hash=content_hash,
            duration_seconds=meta.get("duration_seconds"),
            width=meta.get("width"),
            height=meta.get("height"),
            fps=meta.get("fps"),
            codec=meta.get("codec"),
            pixel_format=meta.get("pixel_format"),
            bitrate=meta.get("bitrate"),
            thumbnail_path=thumb_path,
            source_directory=source_directory,
            indexed_at=now,
            last_verified_at=now,
            is_corrupt=is_corrupt,
        )

        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO media_files
                   (file_path, file_name, file_size, content_hash,
                    duration_seconds, width, height, fps, codec,
                    pixel_format, bitrate, thumbnail_path,
                    source_directory, indexed_at, last_verified_at, is_corrupt)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    asset.file_path, asset.file_name, asset.file_size,
                    asset.content_hash, asset.duration_seconds,
                    asset.width, asset.height, asset.fps, asset.codec,
                    asset.pixel_format, asset.bitrate, asset.thumbnail_path,
                    asset.source_directory, asset.indexed_at,
                    asset.last_verified_at, int(asset.is_corrupt),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        return asset

    async def index_directory(
        self,
        directory: Path,
        recursive: bool = True,
        batch_pause: int = 50,
    ) -> IndexProgress:
        """Index all videos in a directory with progress tracking.

        Args:
            directory: Root directory to scan
            recursive: Whether to scan subdirectories
            batch_pause: Pause briefly every N files to avoid blocking M2 8GB
        """
        progress = IndexProgress()
        videos = await self.scan_directory(directory, recursive)
        progress.total_files = len(videos)
        source_dir = str(directory.resolve())

        logger.info("Starting index of %d files from %s", len(videos), directory)

        for i, video_path in enumerate(videos):
            progress.scanned += 1

            try:
                asset = await self.index_file(video_path, source_dir)
                if asset is None:
                    progress.skipped_duplicate += 1
                elif asset.is_corrupt:
                    progress.skipped_corrupt += 1
                else:
                    progress.indexed += 1
            except Exception as exc:
                logger.error("Failed to index %s: %s", video_path.name, exc)
                progress.errors += 1

            # Periodic pause to prevent memory pressure on M2 8GB
            if batch_pause > 0 and (i + 1) % batch_pause == 0:
                await asyncio.sleep(0.1)

            if (i + 1) % 100 == 0 or (i + 1) == len(videos):
                logger.info(progress.summary())

        logger.info("Index complete: %s", progress.summary())
        return progress

    def search(
        self,
        query: str = "",
        category: str = "",
        min_duration: float = 0.0,
        max_duration: float = float("inf"),
        rights_status: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> list[MediaAsset]:
        """Search the media library with filters."""
        conditions: list[str] = []
        params: list = []

        if query:
            conditions.append("(file_name LIKE ? OR tags LIKE ? OR notes LIKE ?)")
            q = f"%{query}%"
            params.extend([q, q, q])

        if category:
            conditions.append("category = ?")
            params.append(category)

        if min_duration > 0:
            conditions.append("duration_seconds >= ?")
            params.append(min_duration)

        if max_duration < float("inf"):
            conditions.append("duration_seconds <= ?")
            params.append(max_duration)

        if rights_status:
            conditions.append("rights_status = ?")
            params.append(rights_status)

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT * FROM media_files WHERE {where} ORDER BY indexed_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        conn = self._get_conn()
        try:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_asset(row) for row in rows]
        finally:
            conn.close()

    def get_stats(self) -> dict:
        """Get library statistics."""
        conn = self._get_conn()
        try:
            total = conn.execute("SELECT COUNT(*) FROM media_files").fetchone()[0]
            corrupt = conn.execute(
                "SELECT COUNT(*) FROM media_files WHERE is_corrupt = 1"
            ).fetchone()[0]
            total_size = conn.execute(
                "SELECT COALESCE(SUM(file_size), 0) FROM media_files"
            ).fetchone()[0]
            categories = conn.execute(
                "SELECT category, COUNT(*) FROM media_files GROUP BY category"
            ).fetchall()
            rights = conn.execute(
                "SELECT rights_status, COUNT(*) FROM media_files GROUP BY rights_status"
            ).fetchall()

            return {
                "total_files": total,
                "corrupt_files": corrupt,
                "total_size_bytes": total_size,
                "total_size_mb": round(total_size / (1024 * 1024), 1),
                "categories": {r[0] or "(uncategorized)": r[1] for r in categories},
                "rights_statuses": {r[0]: r[1] for r in rights},
            }
        finally:
            conn.close()

    def update_tags(self, file_path: str, tags: list[str]) -> bool:
        """Update tags for a media file."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "UPDATE media_files SET tags = ? WHERE file_path = ?",
                (json.dumps(tags), file_path),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def update_category(self, file_path: str, category: str) -> bool:
        """Update category for a media file."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "UPDATE media_files SET category = ? WHERE file_path = ?",
                (category, file_path),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def update_rights_status(self, file_path: str, status: str) -> bool:
        """Update rights status for a media file."""
        valid = {"pending_authorization", "authorized", "restricted", "public_domain"}
        if status not in valid:
            raise ValueError(f"Invalid rights status: {status}. Must be one of {valid}")
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "UPDATE media_files SET rights_status = ? WHERE file_path = ?",
                (status, file_path),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def verify_files_exist(self) -> dict:
        """Check which indexed files still exist on disk."""
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT file_path FROM media_files").fetchall()
            missing = [r["file_path"] for r in rows if not Path(r["file_path"]).exists()]
            present = len(rows) - len(missing)
            return {
                "total_indexed": len(rows),
                "present": present,
                "missing": len(missing),
                "missing_paths": missing[:20],  # First 20 for reporting
            }
        finally:
            conn.close()

    @staticmethod
    def _row_to_asset(row: sqlite3.Row) -> MediaAsset:
        """Convert a database row to a MediaAsset."""
        tags_raw = row["tags"] or "[]"
        try:
            tags = tuple(json.loads(tags_raw))
        except (json.JSONDecodeError, TypeError):
            tags = ()

        return MediaAsset(
            file_path=row["file_path"],
            file_name=row["file_name"],
            file_size=row["file_size"],
            content_hash=row["content_hash"],
            duration_seconds=row["duration_seconds"],
            width=row["width"],
            height=row["height"],
            fps=row["fps"],
            codec=row["codec"],
            pixel_format=row["pixel_format"],
            bitrate=row["bitrate"],
            thumbnail_path=row["thumbnail_path"],
            tags=tags,
            category=row["category"] or "",
            rights_status=row["rights_status"] or "pending_authorization",
            source_directory=row["source_directory"] or "",
            indexed_at=row["indexed_at"] or 0.0,
            last_verified_at=row["last_verified_at"] or 0.0,
            is_corrupt=bool(row["is_corrupt"]),
            notes=row["notes"] or "",
        )