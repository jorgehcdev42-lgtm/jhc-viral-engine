"""Temporary video hosting for Instagram Content Publishing API.

Instagram's Content Publishing API requires a publicly accessible HTTPS URL
for video uploads — it does NOT support direct file upload or resumable upload.

This module provides temporary hosting via the project's existing Netlify
static site (https://jhc-viral-engine.netlify.app). Videos are copied to
frontend/tmp_media/ with non-predictable filenames, served briefly while
Meta processes the container, then cleaned up automatically.

Security:
- Filenames use UUID4 (non-predictable)
- Files auto-expire after configurable TTL (default 2 hours)
- Cleanup runs on every host_video() call
- No credentials or private data exposed
- Original files are NEVER modified or deleted
"""

from __future__ import annotations

import logging
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

NETLIFY_BASE_URL = "https://jhc-viral-engine.netlify.app"
TMP_MEDIA_DIR = "frontend/tmp_media"
DEFAULT_TTL_SECONDS = 7200  # 2 hours
MAX_FILE_SIZE_MB = 100  # Instagram Reels limit


class VideoHost:
    """Temporary video hosting via Netlify static site."""

    def __init__(
        self,
        project_root: Path | str,
        base_url: str = NETLIFY_BASE_URL,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self.project_root = Path(project_root)
        self.base_url = base_url.rstrip("/")
        self.ttl_seconds = ttl_seconds
        self.tmp_dir = self.project_root / TMP_MEDIA_DIR
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

    def host_video(self, local_path: str | Path) -> dict:
        """Copy a local video to tmp_media/ and return its public HTTPS URL.

        Returns dict with:
        - success: bool
        - url: str (public HTTPS URL) or empty
        - filename: str (generated UUID-based name) or empty
        - error: str or empty
        - size_mb: float
        - expires_at: float (unix timestamp)
        """
        src = Path(local_path)
        if not src.exists():
            return {"success": False, "error": f"File not found: {local_path}", "url": "", "filename": ""}

        size_bytes = src.stat().st_size
        size_mb = size_bytes / (1024 * 1024)

        if size_mb > MAX_FILE_SIZE_MB:
            return {
                "success": False,
                "error": f"File too large ({size_mb:.1f}MB > {MAX_FILE_SIZE_MB}MB Instagram limit)",
                "url": "",
                "filename": "",
            }

        if size_bytes < 1000:
            return {
                "success": False,
                "error": f"File too small ({size_bytes} bytes) — likely not a valid video",
                "url": "",
                "filename": "",
            }

        # Clean up expired files first
        self.cleanup_expired()

        # Generate non-predictable filename
        ext = src.suffix.lower() or ".mp4"
        unique_name = f"{uuid.uuid4().hex[:16]}{ext}"
        dest = self.tmp_dir / unique_name

        try:
            shutil.copy2(str(src), str(dest))
        except OSError as e:
            return {"success": False, "error": f"Copy failed: {e}", "url": "", "filename": ""}

        public_url = f"{self.base_url}/tmp_media/{unique_name}"
        expires_at = time.time() + self.ttl_seconds

        logger.info(
            "Video hosted temporarily: %s → %s (%.1fMB, expires in %ds)",
            src.name, unique_name, size_mb, self.ttl_seconds,
        )

        return {
            "success": True,
            "url": public_url,
            "filename": unique_name,
            "size_mb": round(size_mb, 2),
            "expires_at": expires_at,
            "error": "",
        }

    def cleanup_expired(self) -> int:
        """Remove files older than TTL. Returns count of removed files."""
        now = time.time()
        removed = 0
        for f in self.tmp_dir.iterdir():
            if f.is_file():
                age = now - f.stat().st_mtime
                if age > self.ttl_seconds:
                    try:
                        f.unlink()
                        removed += 1
                        logger.debug("Cleaned up expired temp video: %s (age=%ds)", f.name, int(age))
                    except OSError as e:
                        logger.warning("Failed to clean up %s: %s", f.name, e)
        if removed:
            logger.info("Cleaned up %d expired temp video(s)", removed)
        return removed

    def remove_file(self, filename: str) -> bool:
        """Remove a specific hosted file by filename."""
        target = self.tmp_dir / filename
        if target.exists():
            try:
                target.unlink()
                logger.info("Removed temp video: %s", filename)
                return True
            except OSError as e:
                logger.warning("Failed to remove %s: %s", filename, e)
                return False
        return False

    def get_hosted_url(self, filename: str) -> Optional[str]:
        """Get the public URL for an already-hosted file, if it still exists."""
        target = self.tmp_dir / filename
        if target.exists():
            return f"{self.base_url}/tmp_media/{filename}"
        return None

    def list_hosted(self) -> list[dict]:
        """List all currently hosted temporary videos."""
        now = time.time()
        result = []
        for f in sorted(self.tmp_dir.iterdir()):
            if f.is_file():
                stat = f.stat()
                age = now - stat.st_mtime
                remaining = max(0, self.ttl_seconds - age)
                result.append({
                    "filename": f.name,
                    "size_mb": round(stat.st_size / (1024 * 1024), 2),
                    "age_seconds": int(age),
                    "remaining_seconds": int(remaining),
                    "url": f"{self.base_url}/tmp_media/{f.name}",
                })
        return result