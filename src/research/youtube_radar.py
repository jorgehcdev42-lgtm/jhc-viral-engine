"""Radar GTA VI — Busca automática de vídeos recentes no YouTube via yt-dlp.

MISSÃO 040 FASE 2.
Busca por termos relevantes, filtra por data, deduplica contra imports existentes.
"""

import json
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DATA_ROOT = Path(__file__).resolve().parent.parent.parent / "data"
RADAR_CACHE_FILE = DATA_ROOT / "radar_cache.json"

SEARCH_TERMS = [
    "GTA 6",
    "GTA VI",
    "Grand Theft Auto VI",
    "Rockstar Games GTA",
    "Vice City GTA VI",
    "GTA VI gameplay",
    "GTA VI trailer",
    "GTA VI novidades",
    "GTA VI vazamentos",
    "GTA VI notícias",
    "GTA VI Brasil",
    "Leonida GTA",
]

OFFICIAL_CHANNELS = {
    "rockstar games",
    "gta",
    "grand theft auto",
    "take-two interactive",
}


@dataclass
class RadarResult:
    url: str
    title: str
    author: str
    duration: float = 0.0
    view_count: int = 0
    upload_date: str = ""
    thumbnail: str = ""
    resolution: str = ""
    is_official: bool = False
    already_imported: bool = False
    relevance_score: float = 0.0
    discovered_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class YouTubeRadar:
    """Pesquisa vídeos recentes sobre GTA VI no YouTube."""

    def __init__(self, data_root: Optional[Path] = None):
        self.data_root = data_root or DATA_ROOT
        self.cache_file = self.data_root / "radar_cache.json"
        self._yt_dlp_bin = self._find_yt_dlp()

    def _find_yt_dlp(self) -> str:
        candidates = [
            shutil.which("yt-dlp"),
            "/opt/homebrew/bin/yt-dlp",
            "/usr/local/bin/yt-dlp",
        ]
        for c in candidates:
            if c and Path(c).exists():
                return c
        raise FileNotFoundError("yt-dlp não encontrado")

    def search(
        self,
        query: str = "",
        max_results: int = 10,
        date_filter: str = "7d",
    ) -> list[dict]:
        """Busca vídeos no YouTube via yt-dlp search.

        date_filter: '24h', '7d', '30d', 'all'
        """
        if not query:
            query = "GTA VI"

        date_map = {
            "24h": "today",
            "7d": "week",
            "30d": "month",
            "all": "",
        }
        when = date_map.get(date_filter, "week")

        date_after = self._date_after(when) if when else ""

        try:
            search_spec = f"ytsearch{max_results}:{query}"
            cmd = [
                self._yt_dlp_bin,
                search_spec,
                "--flat-playlist",
                "--dump-json",
                "--no-download",
                "--quiet",
                "--no-warnings",
            ]
            if date_after:
                cmd.extend(["--dateafter", date_after])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )

            videos = []
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    info = json.loads(line)
                    video = self._parse_flat_info(info, query)
                    if video:
                        videos.append(video)
                except json.JSONDecodeError:
                    continue

            if not videos and result.returncode != 0:
                logger.warning(f"yt-dlp search failed: {result.stderr[:200]}")

            videos.sort(key=lambda v: v.get("relevance_score", 0), reverse=True)
            return videos[:max_results]

        except subprocess.TimeoutExpired:
            logger.error("YouTube search timeout (>60s)")
            return []
        except Exception as e:
            logger.error(f"YouTube search error: {e}")
            return []

    def search_all_terms(
        self,
        max_per_term: int = 5,
        date_filter: str = "7d",
    ) -> list[dict]:
        """Busca usando todos os termos pré-definidos."""
        all_videos = {}
        for term in SEARCH_TERMS:
            results = self.search(term, max_per_term, date_filter)
            for v in results:
                url = v.get("url", "")
                if url and url not in all_videos:
                    all_videos[url] = v

        videos = list(all_videos.values())
        videos.sort(key=lambda v: v.get("relevance_score", 0), reverse=True)
        return videos

    def get_cached_results(self, max_age_hours: int = 24) -> list[dict]:
        """Retorna resultados em cache se ainda válidos."""
        if not self.cache_file.exists():
            return []
        try:
            data = json.loads(self.cache_file.read_text())
            cached_at = data.get("cached_at", "")
            if cached_at:
                age = time.time() - float(cached_at)
                if age > max_age_hours * 3600:
                    return []
            return data.get("results", [])
        except (json.JSONDecodeError, ValueError, OSError):
            return []

    def save_to_cache(self, results: list[dict]) -> None:
        """Salva resultados no cache."""
        data = {
            "cached_at": str(time.time()),
            "count": len(results),
            "results": results,
        }
        self.cache_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def check_already_imported(self, videos: list[dict]) -> list[dict]:
        """Marca vídeos já importados verificando histórico."""
        history_file = self.data_root / "import_history.json"
        imported_urls = set()
        imported_hashes = set()

        if history_file.exists():
            try:
                history = json.loads(history_file.read_text())
                for h in history:
                    if h.get("status") == "completed":
                        imported_urls.add(h.get("url", ""))
                        sha = h.get("sha256", "")
                        if sha:
                            imported_hashes.add(sha)
            except (json.JSONDecodeError, OSError):
                pass

        for v in videos:
            v["already_imported"] = v.get("url", "") in imported_urls

        return videos

    # --- Private ---

    def _parse_flat_info(self, info: dict, query: str) -> Optional[dict]:
        """Parseia metadata leve de --flat-playlist (campos limitados)."""
        video_id = info.get("id", "")
        url = info.get("url") or info.get("webpage_url", "")
        if not url and video_id:
            url = f"https://www.youtube.com/watch?v={video_id}"
        if not url:
            return None

        title = info.get("title", "")
        author = info.get("uploader", info.get("channel", ""))
        duration = info.get("duration") or 0
        view_count = info.get("view_count") or 0
        upload_date = info.get("upload_date", "")
        thumbnail = info.get("thumbnail", "")

        is_official = any(ch in author.lower() for ch in OFFICIAL_CHANNELS) if author else False
        score = self._calculate_relevance(title, author, view_count, duration, is_official, query, upload_date)

        return {
            "url": url,
            "title": title,
            "author": author,
            "duration": duration,
            "view_count": view_count,
            "upload_date": upload_date,
            "thumbnail": thumbnail,
            "resolution": "",
            "is_official": is_official,
            "already_imported": False,
            "relevance_score": round(score, 2),
            "discovered_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }

    def _parse_video_info(self, info: dict, query: str) -> Optional[dict]:
        """Converte info do yt-dlp em formato RadarResult."""
        url = info.get("url") or info.get("webpage_url", "")
        if not url:
            video_id = info.get("id", "")
            if video_id:
                url = f"https://www.youtube.com/watch?v={video_id}"
            else:
                return None

        title = info.get("title", "")
        author = info.get("uploader", info.get("channel", ""))
        duration = info.get("duration", 0) or 0
        view_count = info.get("view_count", 0) or 0
        upload_date = info.get("upload_date", "")
        thumbnail = info.get("thumbnail", "")
        width = info.get("width", 0)
        height = info.get("height", 0)
        resolution = f"{width}x{height}" if width and height else ""

        # Verificar se é canal oficial
        is_official = any(
            ch in author.lower() for ch in OFFICIAL_CHANNELS
        )

        # Calcular score de relevância
        score = self._calculate_relevance(title, author, view_count, duration, is_official, query, upload_date)

        return {
            "url": url,
            "title": title,
            "author": author,
            "duration": duration,
            "view_count": view_count,
            "upload_date": upload_date,
            "thumbnail": thumbnail,
            "resolution": resolution,
            "is_official": is_official,
            "already_imported": False,
            "relevance_score": round(score, 2),
            "discovered_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }

    def _calculate_relevance(
        self,
        title: str,
        author: str,
        views: int,
        duration: float,
        is_official: bool,
        query: str,
        upload_date: str = "",
    ) -> float:
        """Score de relevância 0-100."""
        score = 0.0

        # Match com query no título (peso 30)
        title_lower = title.lower()
        query_lower = query.lower()
        if query_lower in title_lower:
            score += 30
        elif any(w in title_lower for w in query_lower.split()):
            score += 15

        # Canal oficial (peso 20)
        if is_official:
            score += 20

        # Views (peso 15, log scale)
        if views > 0:
            import math
            score += min(15, math.log10(max(1, views)) * 2)

        # Duração ideal para reels: 30-120s (peso 15)
        if 30 <= duration <= 120:
            score += 15
        elif 15 <= duration <= 300:
            score += 8

        # Recência (peso 20) — upload_date YYYYMMDD
        if len(str(upload_date)) == 8:
            try:
                from datetime import datetime as dt
                d = dt.strptime(str(upload_date), "%Y%m%d")
                days_ago = (dt.now() - d).days
                if days_ago <= 1:
                    score += 20
                elif days_ago <= 7:
                    score += 15
                elif days_ago <= 30:
                    score += 8
            except ValueError:
                pass

        return min(100, score)

    def _date_after(self, when: str) -> str:
        """Calcula data mínima para filtro yt-dlp (YYYYMMDD)."""
        now = datetime.now()
        if when == "today":
            target = now - timedelta(days=1)
        elif when == "week":
            target = now - timedelta(days=7)
        elif when == "month":
            target = now - timedelta(days=30)
        else:
            target = now - timedelta(days=7)
        return target.strftime("%Y%m%d")

    def _fallback_search(self, query: str, max_results: int) -> list[dict]:
        """Fallback: busca direta sem flat-playlist."""
        try:
            cmd = [
                self._yt_dlp_bin,
                f"ytsearch{max_results}:{query}",
                "--dump-json",
                "--no-download",
                "--quiet",
                "--no-warnings",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
            videos = []
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    info = json.loads(line)
                    video = self._parse_video_info(info, query)
                    if video:
                        videos.append(video)
                except json.JSONDecodeError:
                    continue
            return videos[:max_results]
        except Exception as e:
            logger.error(f"Fallback search failed: {e}")
            return []