"""JHC Viral Engine — Analytics module.

Módulo de inteligência de crescimento que consolida métricas de publicação,
desempenho por plataforma e sugestões de otimização. Integra-se ao
PublishStateMachine e BrowserPublisher existentes.
"""

from src.analytics.metrics import (
    PlatformMetrics,
    VideoPerformance,
    AnalyticsReport,
    collect_platform_stats,
    generate_report,
    suggest_optimizations,
)

__all__ = [
    "PlatformMetrics",
    "VideoPerformance",
    "AnalyticsReport",
    "collect_platform_stats",
    "generate_report",
    "suggest_optimizations",
]