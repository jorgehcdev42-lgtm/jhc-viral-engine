"""Analytics metrics engine for JHC Viral Engine.

Coleta, consolida e analisa métricas de publicação multiplataforma.
Integra-se ao PublishStateMachine e BrowserPublisher existentes.
Métricas reais quando disponíveis via API; placeholders claros quando não.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class PlatformMetrics:
    """Métricas agregadas por plataforma."""
    platform: str
    total_posts: int = 0
    total_views: int = 0
    total_likes: int = 0
    total_comments: int = 0
    total_shares: int = 0
    followers: int = 0
    avg_retention_pct: float = 0.0
    last_updated: float = 0.0
    data_source: str = "unavailable"  # api, manual, unavailable

    def engagement_rate(self) -> float:
        """Taxa de engajamento: (likes + comments + shares) / views * 100."""
        if self.total_views == 0:
            return 0.0
        interactions = self.total_likes + self.total_comments + self.total_shares
        return round((interactions / self.total_views) * 100, 2)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["engagement_rate"] = self.engagement_rate()
        return d


@dataclass(frozen=True)
class VideoPerformance:
    """Desempenho individual de um vídeo publicado."""
    video_id: str
    title: str
    platform: str
    published_at: float = 0.0
    permalink: str = ""
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    retention_pct: float = 0.0
    duration_seconds: float = 0.0
    hashtags: list[str] = field(default_factory=list)
    data_source: str = "unavailable"

    def engagement_rate(self) -> float:
        if self.views == 0:
            return 0.0
        interactions = self.likes + self.comments + self.shares
        return round((interactions / self.views) * 100, 2)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["engagement_rate"] = self.engagement_rate()
        return d


@dataclass
class AnalyticsReport:
    """Relatório consolidado de analytics multiplataforma."""
    generated_at: float = field(default_factory=time.time)
    platforms: dict[str, PlatformMetrics] = field(default_factory=dict)
    top_videos: list[VideoPerformance] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    total_videos_published: int = 0
    total_views_all_platforms: int = 0
    best_performing_platform: str = ""
    worst_performing_platform: str = ""

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "total_videos_published": self.total_videos_published,
            "total_views_all_platforms": self.total_views_all_platforms,
            "best_performing_platform": self.best_performing_platform,
            "worst_performing_platform": self.worst_performing_platform,
            "platforms": {k: v.to_dict() for k, v in self.platforms.items()},
            "top_videos": [v.to_dict() for v in self.top_videos],
            "suggestions": self.suggestions,
        }


def collect_platform_stats(
    data_root: str | Path = "data",
) -> dict[str, PlatformMetrics]:
    """Coleta estatísticas por plataforma do histórico de publicações.

    Usa dados locais do publish_state_machine como fonte primária.
    Métricas de visualização/engajamento marcadas como 'unavailable'
    quando não há integração API ativa.
    """
    data_path = Path(data_root)
    history_file = data_path / "publish_history.json"
    stats: dict[str, PlatformMetrics] = {}

    if not history_file.exists():
        # Retornar plataformas vazias mas estruturadas
        for platform in ("tiktok", "instagram", "youtube"):
            stats[platform] = PlatformMetrics(
                platform=platform,
                data_source="unavailable",
            )
        return stats

    try:
        history = json.loads(history_file.read_text())
    except (json.JSONDecodeError, OSError):
        history = []

    # Agregar por plataforma
    platform_data: dict[str, dict] = {}
    for entry in history:
        plat = entry.get("platform", "unknown")
        if plat not in platform_data:
            platform_data[plat] = {
                "posts": 0, "views": 0, "likes": 0,
                "comments": 0, "shares": 0,
            }
        pd = platform_data[plat]
        state = entry.get("state", "")
        if state == "published":
            pd["posts"] += 1
            pd["views"] += entry.get("views", 0)
            pd["likes"] += entry.get("likes", 0)
            pd["comments"] += entry.get("comments", 0)
            pd["shares"] += entry.get("shares", 0)

    for plat, pd in platform_data.items():
        source = "local_history" if pd["posts"] > 0 else "unavailable"
        stats[plat] = PlatformMetrics(
            platform=plat,
            total_posts=pd["posts"],
            total_views=pd["views"],
            total_likes=pd["likes"],
            total_comments=pd["comments"],
            total_shares=pd["shares"],
            last_updated=time.time(),
            data_source=source,
        )

    # Garantir que todas as plataformas principais existam
    for plat in ("tiktok", "instagram", "youtube"):
        if plat not in stats:
            stats[plat] = PlatformMetrics(
                platform=plat,
                data_source="unavailable",
            )

    return stats


def generate_report(
    data_root: str | Path = "data",
    top_n: int = 10,
) -> AnalyticsReport:
    """Gera relatório consolidado de analytics."""
    platform_stats = collect_platform_stats(data_root)

    report = AnalyticsReport(
        platforms=platform_stats,
    )

    # Totais agregados
    total_posts = sum(p.total_posts for p in platform_stats.values())
    total_views = sum(p.total_views for p in platform_stats.values())
    report.total_videos_published = total_posts
    report.total_views_all_platforms = total_views

    # Melhor/pior plataforma por engagement rate
    active = {k: v for k, v in platform_stats.items() if v.total_posts > 0}
    if active:
        best = max(active.values(), key=lambda p: p.engagement_rate())
        worst = min(active.values(), key=lambda p: p.engagement_rate())
        report.best_performing_platform = best.platform
        report.worst_performing_platform = worst.platform

    # Top vídeos do histórico
    data_path = Path(data_root)
    history_file = data_path / "publish_history.json"
    if history_file.exists():
        try:
            history = json.loads(history_file.read_text())
            published = [
                e for e in history
                if e.get("state") == "published"
            ]
            # Ordenar por views (desc)
            published.sort(key=lambda e: e.get("views", 0), reverse=True)
            for entry in published[:top_n]:
                report.top_videos.append(VideoPerformance(
                    video_id=entry.get("video_id", entry.get("job_id", "?")),
                    title=entry.get("title", ""),
                    platform=entry.get("platform", "unknown"),
                    published_at=entry.get("published_at", 0.0),
                    permalink=entry.get("permalink", ""),
                    views=entry.get("views", 0),
                    likes=entry.get("likes", 0),
                    comments=entry.get("comments", 0),
                    shares=entry.get("shares", 0),
                    retention_pct=entry.get("retention_pct", 0.0),
                    duration_seconds=entry.get("duration_seconds", 0.0),
                    hashtags=entry.get("hashtags", []),
                    data_source="local_history",
                ))
        except (json.JSONDecodeError, OSError):
            pass

    # Gerar sugestões
    report.suggestions = suggest_optimizations(report)

    return report


def suggest_optimizations(report: AnalyticsReport) -> list[str]:
    """Gera sugestões fundamentadas baseadas nas métricas disponíveis."""
    suggestions: list[str] = []

    # Verificar plataformas sem dados
    no_data = [
        p.platform for p in report.platforms.values()
        if p.data_source == "unavailable" and p.total_posts == 0
    ]
    if no_data:
        suggestions.append(
            f"⚠️ Plataformas sem dados de analytics: {', '.join(no_data)}. "
            f"Conecte APIs oficiais ou registre métricas manualmente."
        )

    # Verificar engagement baixo
    for plat, metrics in report.platforms.items():
        if metrics.total_posts > 0 and metrics.engagement_rate() < 1.0:
            suggestions.append(
                f"📉 {plat}: engagement rate {metrics.engagement_rate()}% "
                f"(abaixo de 1%). Revise hooks nos primeiros 3 segundos, "
                f"hashtags e horários de publicação."
            )

    # Verificar retenção
    low_retention = [
        v for v in report.top_videos
        if v.retention_pct > 0 and v.retention_pct < 30
    ]
    if low_retention:
        suggestions.append(
            f"⏱️ {len(low_retention)} vídeo(s) com retenção <30%. "
            f"Considere cortes mais dinâmicos nos primeiros 5 segundos."
        )

    # Verificar volume de publicação
    if report.total_videos_published < 5:
        suggestions.append(
            "📊 Volume baixo de publicações. Algoritmos favorecem "
            "consistência. Publique pelo menos 1x/dia em cada plataforma."
        )

    # Sugestão geral se tudo estiver unavailable
    all_unavailable = all(
        p.data_source == "unavailable"
        for p in report.platforms.values()
    )
    if all_unavailable and report.total_videos_published == 0:
        suggestions.append(
            "🔧 Módulo de analytics inicializado. Publique vídeos e "
            "conecte APIs de plataforma para ver métricas reais."
        )

    if not suggestions:
        suggestions.append("✅ Métricas dentro do esperado. Continue monitorando.")

    return suggestions