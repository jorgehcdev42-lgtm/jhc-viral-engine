"""Radar Viral Instagram — MISSÃO 040.2 FASES 1-3.

Descobre Reels recentes e populares sobre GTA VI no Instagram.
Usa yt-dlp para scraping de perfis públicos e hashtags (sem API oficial).
Calcula Viral Score baseado em métricas disponíveis.

LIMITAÇÃO REAL: Instagram não oferece API pública de busca de Reels.
Este módulo usa yt-dlp para extrair metadata de URLs públicas conhecidas
(perfis oficiais, hashtags via explore). Métricas como views/likes podem
estar indisponíveis dependendo do endpoint. Quando ausentes, o Viral Score
é calculado com confiança reduzida e a limitação é registrada.
"""

import json
import logging
import math
import shutil
import subprocess
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DATA_ROOT = Path(__file__).resolve().parent.parent.parent / "data"
RADAR_CACHE_DIR = DATA_ROOT / "instagram_radar"

SEARCH_TERMS = [
    "GTA 6", "GTA VI", "Grand Theft Auto VI", "Rockstar Games",
    "Vice City", "Leonida", "GTA 6 Brasil", "GTA VI notícias",
    "GTA VI gameplay", "GTA VI trailer", "GTA VI novidades",
    "GTA VI vazamentos", "GTA VI curiosidades",
]

HASHTAGS = [
    "gta6", "gtavi", "rockstargames", "vicecity", "gta6brasil",
    "gtavitrailer", "gtavigameplay", "gtavinovidades", "leonida",
    "grandtheftauto", "gta6news", "gtavileaks",
]

OFFICIAL_PROFILES = [
    "rockstargames", "gta", "grandtheftauto",
]

MONITORED_PROFILES_FILE = DATA_ROOT / "instagram_radar" / "monitored_profiles.json"


@dataclass
class InstagramReel:
    url: str
    title: str = ""
    author: str = ""
    thumbnail: str = ""
    duration: float = 0.0
    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    upload_date: str = ""
    viral_score: float = 0.0
    confidence: float = 1.0  # 1.0 = todas métricas disponíveis, <1.0 = parcial
    category: str = ""  # 🔥🚀🆕⭐📉
    is_official: bool = False
    already_imported: bool = False
    rights_status: str = "unknown"  # owned, licensed, fair_use, reference_only, unknown
    discovered_at: str = ""
    metrics_available: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class InstagramRadar:
    """Radar de Reels virais do Instagram sobre GTA VI."""

    def __init__(self, data_root: Optional[Path] = None):
        self.data_root = data_root or DATA_ROOT
        self.cache_dir = self.data_root / "instagram_radar"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._yt_dlp_bin = self._find_yt_dlp()
        self._monitored_profiles = self._load_monitored_profiles()

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

    def _load_monitored_profiles(self) -> list[str]:
        if MONITORED_PROFILES_FILE.exists():
            try:
                data = json.loads(MONITORED_PROFILES_FILE.read_text())
                return data.get("profiles", OFFICIAL_PROFILES)
            except (json.JSONDecodeError, OSError):
                pass
        return list(OFFICIAL_PROFILES)

    def add_monitored_profile(self, profile: str) -> list[str]:
        profile = profile.strip().lstrip("@").lower()
        if profile and profile not in self._monitored_profiles:
            self._monitored_profiles.append(profile)
            MONITORED_PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
            MONITORED_PROFILES_FILE.write_text(
                json.dumps({"profiles": self._monitored_profiles}, indent=2)
            )
        return self._monitored_profiles

    def remove_monitored_profile(self, profile: str) -> list[str]:
        profile = profile.strip().lstrip("@").lower()
        if profile in self._monitored_profiles:
            self._monitored_profiles.remove(profile)
            MONITORED_PROFILES_FILE.write_text(
                json.dumps({"profiles": self._monitored_profiles}, indent=2)
            )
        return self._monitored_profiles

    def search_hashtag(self, hashtag: str, max_results: int = 10) -> list[dict]:
        """Busca Reels por hashtag via yt-dlp (explore page)."""
        tag = hashtag.lstrip("#").strip()
        url = f"https://www.instagram.com/explore/tags/{tag}/"
        return self._scrape_url(url, max_results, source_type="hashtag", query=f"#{tag}")

    def search_profile(self, profile: str, max_results: int = 10) -> list[dict]:
        """Busca Reels recentes de um perfil público via yt-dlp."""
        user = profile.strip().lstrip("@").lower()
        url = f"https://www.instagram.com/{user}/reels/"
        return self._scrape_url(url, max_results, source_type="profile", query=f"@{user}")

    def search_all(self, max_per_source: int = 5) -> list[dict]:
        """Busca completa: perfis monitorados + hashtags relevantes."""
        all_reels = {}

        # Perfis monitorados
        for profile in self._monitored_profiles:
            results = self.search_profile(profile, max_per_source)
            for r in results:
                url = r.get("url", "")
                if url and url not in all_reels:
                    all_reels[url] = r

        # Hashtags
        for tag in HASHTAGS[:6]:  # Limitar para não sobrecarregar
            results = self.search_hashtag(tag, max_per_source)
            for r in results:
                url = r.get("url", "")
                if url and url not in all_reels:
                    all_reels[url] = r

        reels = list(all_reels.values())
        reels.sort(key=lambda v: v.get("viral_score", 0), reverse=True)
        return reels

    def calculate_viral_score(self, reel: dict) -> tuple[float, float, str]:
        """Calcula Viral Score (0-100), confiança (0-1) e categoria.

        Retorna: (score, confidence, category)
        """
        score = 0.0
        confidence = 1.0
        metrics_found = 0
        total_metrics = 5  # views, likes, comments, recency, relevance

        # Views (peso 25)
        views = reel.get("view_count", 0) or 0
        if views > 0:
            metrics_found += 1
            score += min(25, math.log10(max(1, views)) * 4)
        else:
            confidence *= 0.8

        # Likes (peso 20)
        likes = reel.get("like_count", 0) or 0
        if likes > 0:
            metrics_found += 1
            score += min(20, math.log10(max(1, likes)) * 3.5)
        else:
            confidence *= 0.85

        # Comentários (peso 15)
        comments = reel.get("comment_count", 0) or 0
        if comments > 0:
            metrics_found += 1
            score += min(15, math.log10(max(1, comments)) * 3)
        else:
            confidence *= 0.9

        # Recência (peso 25)
        upload_date = reel.get("upload_date", "")
        if upload_date and len(str(upload_date)) >= 8:
            metrics_found += 1
            try:
                date_str = str(upload_date)[:8]
                d = datetime.strptime(date_str, "%Y%m%d")
                hours_ago = (datetime.now() - d).total_seconds() / 3600
                if hours_ago <= 1:
                    score += 25
                elif hours_ago <= 6:
                    score += 22
                elif hours_ago <= 12:
                    score += 18
                elif hours_ago <= 24:
                    score += 15
                elif hours_ago <= 72:
                    score += 10
                elif hours_ago <= 168:  # 7 dias
                    score += 5
            except ValueError:
                confidence *= 0.9
        else:
            confidence *= 0.85

        # Relevância GTA VI (peso 15)
        title = (reel.get("title", "") or "").lower()
        author = (reel.get("author", "") or "").lower()
        gta_keywords = ["gta", "vice city", "rockstar", "leonida", "grand theft"]
        relevance_hits = sum(1 for kw in gta_keywords if kw in title or kw in author)
        if relevance_hits > 0:
            metrics_found += 1
            score += min(15, relevance_hits * 5)

        # Canal oficial bonus (+10)
        is_official = any(p in author for p in OFFICIAL_PROFILES)
        if is_official:
            score += 10

        # Engajamento proporcional (likes/views ratio)
        if views > 0 and likes > 0:
            engagement_ratio = likes / views
            if engagement_ratio > 0.05:  # >5% é alto
                score += 5
            elif engagement_ratio > 0.02:
                score += 3

        score = min(100, round(score, 1))
        confidence = round(confidence, 2)

        # Classificar categoria
        category = self._classify_category(score, confidence, hours_ago if 'hours_ago' in dir() else 999)

        return score, confidence, category

    def _classify_category(self, score: float, confidence: float, hours_ago: float) -> str:
        """Classifica resultado em categoria visual."""
        if score >= 75 and hours_ago <= 24:
            return "🔥 Bombando agora"
        elif score >= 60 and hours_ago <= 48:
            return "🚀 Tendência crescente"
        elif hours_ago <= 6:
            return "🆕 Acabou de sair"
        elif score >= 50:
            return "⭐ Alto potencial"
        else:
            return "📉 Baixa prioridade"

    def _scrape_url(self, url: str, max_results: int, source_type: str = "", query: str = "") -> list[dict]:
        """Extrai metadata de URL Instagram via yt-dlp."""
        try:
            cmd = [
                self._yt_dlp_bin,
                url,
                "--flat-playlist",
                "--dump-json",
                "--no-download",
                "--quiet",
                "--no-warnings",
                "--playlist-end", str(max_results),
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=45)

            reels = []
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    info = json.loads(line)
                    reel = self._parse_instagram_info(info, source_type, query)
                    if reel:
                        # Calcular Viral Score
                        score, conf, cat = self.calculate_viral_score(reel)
                        reel["viral_score"] = score
                        reel["confidence"] = conf
                        reel["category"] = cat
                        reel["metrics_available"] = {
                            "views": bool(reel.get("view_count")),
                            "likes": bool(reel.get("like_count")),
                            "comments": bool(reel.get("comment_count")),
                            "date": bool(reel.get("upload_date")),
                        }
                        reels.append(reel)
                except json.JSONDecodeError:
                    continue

            if not reels and result.returncode != 0:
                logger.warning(f"Instagram scrape failed for {url}: {result.stderr[:200]}")

            return reels

        except subprocess.TimeoutExpired:
            logger.error(f"Instagram scrape timeout for {url}")
            return []
        except Exception as e:
            logger.error(f"Instagram scrape error for {url}: {e}")
            return []

    def _parse_instagram_info(self, info: dict, source_type: str = "", query: str = "") -> Optional[dict]:
        """Converte metadata do yt-dlp em formato InstagramReel."""
        url = info.get("url") or info.get("webpage_url", "")
        if not url:
            vid = info.get("id", "")
            if vid:
                url = f"https://www.instagram.com/reel/{vid}/"
            else:
                return None

        title = info.get("title", "") or info.get("description", "") or ""
        author = info.get("uploader", "") or info.get("channel", "") or info.get("uploader_id", "")
        thumbnail = info.get("thumbnail", "")
        duration = info.get("duration") or 0
        view_count = info.get("view_count") or 0
        like_count = info.get("like_count") or 0
        comment_count = info.get("comment_count") or 0
        upload_date = info.get("upload_date", "")
        timestamp = info.get("timestamp")

        # Converter timestamp Unix para YYYYMMDD se disponível
        if not upload_date and timestamp:
            try:
                upload_date = datetime.fromtimestamp(int(timestamp)).strftime("%Y%m%d")
            except (ValueError, OSError):
                pass

        is_official = any(p in (author or "").lower() for p in OFFICIAL_PROFILES)

        # Determinar status de direitos
        rights = "reference_only"  # Default: usar apenas como referência editorial
        if is_official:
            rights = "fair_use"  # Conteúdo oficial pode ser usado para análise/comentário

        return {
            "url": url,
            "title": title[:200],
            "author": author,
            "thumbnail": thumbnail,
            "duration": duration,
            "view_count": view_count,
            "like_count": like_count,
            "comment_count": comment_count,
            "upload_date": upload_date,
            "is_official": is_official,
            "already_imported": False,
            "rights_status": rights,
            "discovered_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "source_type": source_type,
            "query": query,
        }

    def check_already_imported(self, reels: list[dict]) -> list[dict]:
        """Marca reels já importados verificando histórico."""
        history_file = self.data_root / "import_history.json"
        imported_urls = set()
        if history_file.exists():
            try:
                history = json.loads(history_file.read_text())
                for h in history:
                    if h.get("status") == "completed":
                        imported_urls.add(h.get("url", ""))
            except (json.JSONDecodeError, OSError):
                pass

        for r in reels:
            r["already_imported"] = r.get("url", "") in imported_urls
        return reels

    def save_cache(self, reels: list[dict], label: str = "latest") -> None:
        cache_file = self.cache_dir / f"cache_{label}.json"
        data = {
            "cached_at": time.time(),
            "count": len(reels),
            "results": reels,
        }
        cache_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def load_cache(self, label: str = "latest", max_age_hours: int = 24) -> list[dict]:
        cache_file = self.cache_dir / f"cache_{label}.json"
        if not cache_file.exists():
            return []
        try:
            data = json.loads(cache_file.read_text())
            age = time.time() - data.get("cached_at", 0)
            if age > max_age_hours * 3600:
                return []
            return data.get("results", [])
        except (json.JSONDecodeError, ValueError, OSError):
            return []

    def get_filter_options(self) -> dict:
        """Retorna opções de filtro disponíveis baseadas nos dados reais."""
        return {
            "time_filters": [
                {"value": "1h", "label": "Última hora"},
                {"value": "6h", "label": "Últimas 6 horas"},
                {"value": "12h", "label": "Últimas 12 horas"},
                {"value": "24h", "label": "Últimas 24 horas"},
                {"value": "3d", "label": "Últimos 3 dias"},
                {"value": "7d", "label": "Últimos 7 dias"},
            ],
            "sort_options": [
                {"value": "viral_score", "label": "Maior Viral Score"},
                {"value": "view_count", "label": "Mais visualizados"},
                {"value": "like_count", "label": "Maior engajamento"},
                {"value": "upload_date", "label": "Mais recentes"},
            ],
            "limitations": [
                "Instagram não oferece API pública de busca de Reels",
                "Métricas (views/likes) podem estar indisponíveis dependendo do endpoint",
                "Scraping via yt-dlp funciona apenas para perfis públicos",
                "Viral Score com confiança <0.8 indica métricas parciais",
                "Vídeos de terceiros são classificados como 'reference_only' por padrão",
            ],
        }