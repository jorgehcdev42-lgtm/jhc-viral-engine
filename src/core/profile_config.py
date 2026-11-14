"""Multi-profile configuration system for JHC Viral Engine.

Each profile has independent identity, sources, editorial config,
media assets, credentials, scheduling, and analytics — all sharing
the same core engine infrastructure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class VisualIdentity:
    """Visual branding for a profile."""
    primary_color: str = "#0066FF"
    secondary_color: str = "#FF3333"
    accent_color: str = "#FFFFFF"
    font_family: str = "Inter"
    logo_path: Optional[str] = None
    watermark_path: Optional[str] = None
    subtitle_style: str = "bold_white_outline"


@dataclass(frozen=True)
class ResearchSources:
    """Content research sources for a profile."""
    keywords: tuple[str, ...] = ()
    rss_feeds: tuple[str, ...] = ()
    youtube_channels: tuple[str, ...] = ()
    subreddits: tuple[str, ...] = ()
    twitter_accounts: tuple[str, ...] = ()
    custom_urls: tuple[str, ...] = ()
    language: str = "pt-BR"


@dataclass(frozen=True)
class EditorialConfig:
    """Editorial guidelines for content production."""
    tone: str = "informative_enthusiastic"
    target_audience: str = "gamers_18_35"
    max_reel_duration_seconds: int = 90
    min_reel_duration_seconds: int = 30
    hook_duration_seconds: int = 3
    posting_schedule: str = "daily_3_to_5"
    content_types: tuple[str, ...] = ("news", "curiosities", "theories", "gameplay")
    banned_topics: tuple[str, ...] = ()
    fact_check_required: bool = True


@dataclass(frozen=True)
class PublishingConfig:
    """Instagram publishing configuration."""
    instagram_account_id: Optional[str] = None
    access_token: Optional[str] = None
    auto_publish: bool = False
    default_hashtags: tuple[str, ...] = ()
    timezone: str = "America/Sao_Paulo"


@dataclass(frozen=True)
class ProfileConfig:
    """Complete configuration for one content profile."""
    profile_id: str
    name: str
    description: str
    niche: str
    visual_identity: VisualIdentity = field(default_factory=VisualIdentity)
    research_sources: ResearchSources = field(default_factory=ResearchSources)
    editorial: EditorialConfig = field(default_factory=EditorialConfig)
    publishing: PublishingConfig = field(default_factory=PublishingConfig)
    enabled: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ProfileConfig:
        return cls(
            profile_id=data["profile_id"],
            name=data["name"],
            description=data.get("description", ""),
            niche=data.get("niche", ""),
            visual_identity=VisualIdentity(**data.get("visual_identity", {})),
            research_sources=ResearchSources(**data.get("research_sources", {})),
            editorial=EditorialConfig(**data.get("editorial", {})),
            publishing=PublishingConfig(**data.get("publishing", {})),
            enabled=data.get("enabled", True),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))

    @classmethod
    def load(cls, path: Path) -> ProfileConfig:
        return cls.from_dict(json.loads(path.read_text()))


# --- Pre-configured profiles ---

GTA6_PROFILE = ProfileConfig(
    profile_id="gta6",
    name="Leonida GTA VI Flash",
    description="Perfil especializado em Grand Theft Auto VI",
    niche="gaming",
    visual_identity=VisualIdentity(
        primary_color="#0066FF",
        secondary_color="#FF3333",
        accent_color="#FFD700",
        font_family="Bebas Neue",
        subtitle_style="bold_white_outline",
    ),
    research_sources=ResearchSources(
        keywords=(
            "GTA 6", "Grand Theft Auto VI", "GTA VI", "Vice City",
            "Rockstar Games", "GTA 6 trailer", "GTA 6 gameplay",
            "GTA 6 lançamento", "GTA 6 novidades", "GTA 6 leak",
        ),
        rss_feeds=(
            "https://www.eurogamer.net/?format=rss",
            "https://www.videogameschronicle.com/feed",
        ),
        youtube_channels=(
            "UCdFoQjLgY9nOwCJNOE9vSJw",  # Rockstar Games
        ),
        subreddits=("GTAVI", "GrandTheftAuto", "GTA"),
        language="pt-BR",
    ),
    editorial=EditorialConfig(
        tone="informative_enthusiastic",
        target_audience="gamers_18_35",
        content_types=("news", "curiosities", "theories", "gameplay", "leaks_analysis"),
        banned_topics=("spoilers_confirmados_sem_aviso",),
        fact_check_required=True,
    ),
    publishing=PublishingConfig(
        default_hashtags=(
            "#GTA6", "#GTAVI", "#ViceCity", "#RockstarGames",
            "#GTA", "#GrandTheftAuto", "#Gaming", "#Games",
        ),
    ),
)

MARVEL_DC_PROFILE = ProfileConfig(
    profile_id="marvel-dc",
    name="Multiverso Radar",
    description="Marvel, DC e universo de super-heróis",
    niche="entertainment",
    visual_identity=VisualIdentity(
        primary_color="#EC1D24",  # Marvel red
        secondary_color="#0077BE",  # DC blue
        accent_color="#FFD700",
        font_family="Anton",
        subtitle_style="bold_white_outline",
    ),
    research_sources=ResearchSources(
        keywords=(
            "Avengers Doomsday", "Avengers Secret Wars", "MCU",
            "Marvel Studios", "DC Universe", "Doutor Destino",
            "Multiverso Marvel", "Marvel Comics", "DC Comics",
        ),
        youtube_channels=(
            "UCvMdeaJz7h0NMlTZjFIFxNw",  # Marvel Entertainment
        ),
        subreddits=("marvelstudios", "DCcomics", "MCU"),
        language="pt-BR",
    ),
    editorial=EditorialConfig(
        tone="epic_analytical",
        target_audience="comic_fans_16_40",
        content_types=("news", "theories", "characters", "timeline", "comics", "trailers"),
        fact_check_required=True,
    ),
    publishing=PublishingConfig(
        default_hashtags=(
            "#Marvel", "#DC", "#MCU", "#Avengers",
            "#SecretWars", "#Doomsday", "#Comics", "#SuperHerois",
        ),
    ),
    enabled=False,  # Prepared but not active yet
)

ANIME_PROFILE = ProfileConfig(
    profile_id="anime",
    name="Anime Radar",
    description="Animes, mangás e cultura otaku",
    niche="entertainment",
    visual_identity=VisualIdentity(
        primary_color="#FF6432",
        secondary_color="#1A1A2E",
        accent_color="#FFD700",
        font_family="Noto Sans JP",
        subtitle_style="bold_white_outline",
    ),
    research_sources=ResearchSources(
        keywords=(
            "anime", "mangá", "One Piece", "Naruto", "Demon Slayer",
            "Jujutsu Kaisen", "Attack on Titan", "Dragon Ball",
        ),
        rss_feeds=("https://www.animenewsnetwork.com/news/rss.xml",),
        subreddits=("anime", "manga"),
        language="pt-BR",
    ),
    editorial=EditorialConfig(
        tone="enthusiastic_curious",
        target_audience="otakus_16_35",
        content_types=("news", "reviews", "theories", "rankings", "curiosities"),
        banned_topics=("spoilers_mangá_não_publicado",),
        fact_check_required=True,
    ),
    publishing=PublishingConfig(
        default_hashtags=(
            "#Anime", "#Mangá", "#Otaku", "#OnePiece",
            "#Naruto", "#DemonSlayer", "#JujutsuKaisen",
        ),
    ),
    enabled=False,
)

FUTURO_PROFILE = ProfileConfig(
    profile_id="futuro",
    name="Futuro Radar",
    description="Inteligência artificial, tecnologia e inovação",
    niche="technology",
    visual_identity=VisualIdentity(
        primary_color="#00B4DC",
        secondary_color="#0A0A1A",
        accent_color="#00FF88",
        font_family="Space Mono",
        subtitle_style="bold_white_outline",
    ),
    research_sources=ResearchSources(
        keywords=(
            "inteligência artificial", "IA", "tecnologia", "inovação",
            "machine learning", "robótica", "futuro", "startups",
        ),
        rss_feeds=(
            "https://techcrunch.com/feed/",
            "https://www.theverge.com/rss/index.xml",
        ),
        subreddits=("technology", "artificial"),
        language="pt-BR",
    ),
    editorial=EditorialConfig(
        tone="visionary_accessible",
        target_audience="tech_enthusiasts_20_45",
        content_types=("news", "analysis", "tutorials", "predictions", "reviews"),
        banned_topics=("fake_news_tech",),
        fact_check_required=True,
    ),
    publishing=PublishingConfig(
        default_hashtags=(
            "#IA", "#Tecnologia", "#Inovação", "#Futuro",
            "#MachineLearning", "#Tech", "#AI",
        ),
    ),
    enabled=False,
)

GAME_PROFILE = ProfileConfig(
    profile_id="game",
    name="Game Radar",
    description="Games em geral, todas as plataformas",
    niche="gaming",
    visual_identity=VisualIdentity(
        primary_color="#64DC32",
        secondary_color="#1A1A2E",
        accent_color="#FFD700",
        font_family="Inter",
        subtitle_style="bold_white_outline",
    ),
    research_sources=ResearchSources(
        keywords=(
            "games", "jogos", "PlayStation", "Xbox", "Nintendo",
            "PC gaming", "Steam", "indie games", "eSports",
        ),
        rss_feeds=(
            "https://www.eurogamer.net/?format=rss",
            "https://www.videogameschronicle.com/feed",
        ),
        subreddits=("gaming", "pcgaming", "consoles"),
        language="pt-BR",
    ),
    editorial=EditorialConfig(
        tone="fun_informative",
        target_audience="gamers_all_platforms_16_40",
        content_types=("news", "reviews", "guides", "rankings", "curiosities"),
        banned_topics=("reviews_sem_jogo_completo",),
        fact_check_required=True,
    ),
    publishing=PublishingConfig(
        default_hashtags=(
            "#Games", "#Gaming", "#PlayStation", "#Xbox",
            "#Nintendo", "#PCGaming", "#IndieGames",
        ),
    ),
    enabled=False,
)

CINE_PROFILE = ProfileConfig(
    profile_id="cine",
    name="Cine Radar",
    description="Filmes, séries e streaming",
    niche="entertainment",
    visual_identity=VisualIdentity(
        primary_color="#C832B4",
        secondary_color="#1A1A2E",
        accent_color="#FFD700",
        font_family="Playfair Display",
        subtitle_style="bold_white_outline",
    ),
    research_sources=ResearchSources(
        keywords=(
            "filmes", "séries", "Netflix", "cinema", "streaming",
            "estreias", "HBO", "Disney+", "Amazon Prime",
        ),
        rss_feeds=(
            "https://www.indiewire.com/feed/",
            "https://variety.com/feed/",
        ),
        subreddits=("movies", "television"),
        language="pt-BR",
    ),
    editorial=EditorialConfig(
        tone="cinephile_engaging",
        target_audience="movie_lovers_18_50",
        content_types=("news", "reviews", "recommendations", "analysis", "trailers"),
        banned_topics=("spoilers_filmes_em_cartaz",),
        fact_check_required=True,
    ),
    publishing=PublishingConfig(
        default_hashtags=(
            "#Cinema", "#Filmes", "#Séries", "#Netflix",
            "#Streaming", "#Estreias", "#CineRadar",
        ),
    ),
    enabled=False,
)

BEAT_PROFILE = ProfileConfig(
    profile_id="beat",
    name="Beat Radar",
    description="Música eletrônica, DJs e produção musical",
    niche="music",
    visual_identity=VisualIdentity(
        primary_color="#B43CFF",
        secondary_color="#0A0A1A",
        accent_color="#00FFCC",
        font_family="Montserrat",
        subtitle_style="bold_white_outline",
    ),
    research_sources=ResearchSources(
        keywords=(
            "DJ", "música eletrônica", "EDM", "festivais",
            "produção musical", "house", "techno", "trance",
        ),
        rss_feeds=(
            "https://djmag.com/feed",
            "https://mixmag.net/feed",
        ),
        subreddits=("edmproduction", "electronicmusic"),
        language="pt-BR",
    ),
    editorial=EditorialConfig(
        tone="vibrant_connected",
        target_audience="djs_producers_music_lovers_18_40",
        content_types=("news", "releases", "festival_coverage", "tutorials", "interviews"),
        banned_topics=("pirataria_musical",),
        fact_check_required=True,
    ),
    publishing=PublishingConfig(
        default_hashtags=(
            "#DJ", "#EDM", "#MúsicaEletrônica", "#Festivais",
            "#ProduçãoMusical", "#House", "#Techno", "#BeatRadar",
        ),
    ),
    enabled=False,
)

# --- Dual Market GTA 6 Profiles ---

GTA6_BR_PROFILE = ProfileConfig(
    profile_id="gta6-br",
    name="Leonida GTA VI Flash BR",
    description="Canal brasileiro especializado em GTA 6 — conteúdo em português",
    niche="gaming",
    visual_identity=VisualIdentity(
        primary_color="#FF2D78",   # Neon rosa
        secondary_color="#B43CFF", # Roxo
        accent_color="#FF8C32",    # Laranja tropical
        font_family="Bebas Neue",
        subtitle_style="bold_white_outline",
    ),
    research_sources=ResearchSources(
        keywords=(
            "GTA 6", "Grand Theft Auto VI", "GTA VI", "Vice City",
            "Rockstar Games", "GTA 6 trailer", "GTA 6 gameplay",
            "GTA 6 lançamento", "GTA 6 novidades", "GTA 6 leak",
            "Jason", "Lucia", "mapa GTA 6",
        ),
        rss_feeds=(
            "https://www.eurogamer.net/?format=rss",
            "https://www.videogameschronicle.com/feed",
        ),
        youtube_channels=(
            "UCdFoQjLgY9nOwCJNOE9vSJw",  # Rockstar Games
        ),
        subreddits=("GTAVI", "GrandTheftAuto", "GTA"),
        language="pt-BR",
    ),
    editorial=EditorialConfig(
        tone="informative_enthusiastic",
        target_audience="gamers_brasil_18_35",
        content_types=("news", "curiosities", "theories", "gameplay", "leaks_analysis"),
        banned_topics=("spoilers_confirmados_sem_aviso",),
        fact_check_required=True,
    ),
    publishing=PublishingConfig(
        default_hashtags=(
            "#GTA6", "#GTAVI", "#ViceCity", "#RockstarGames",
            "#GTA6BR", "#ViceCityRadarBR", "#GamesBrasil",
        ),
        timezone="America/Sao_Paulo",
    ),
    enabled=True,
)

GTA6_GLOBAL_PROFILE = ProfileConfig(
    profile_id="gta6-global",
    name="Leonida GTA VI Flash Global",
    description="International GTA 6 channel — English content for global audience",
    niche="gaming",
    visual_identity=VisualIdentity(
        primary_color="#B43CFF",   # Neon roxo
        secondary_color="#00DCFF", # Cyan cinematográfico
        accent_color="#FF2D78",    # Rosa neon
        font_family="Bebas Neue",
        subtitle_style="bold_white_outline",
    ),
    research_sources=ResearchSources(
        keywords=(
            "GTA 6", "Grand Theft Auto VI", "GTA VI", "Vice City",
            "Rockstar Games", "GTA 6 trailer", "GTA 6 gameplay",
            "GTA 6 release date", "GTA 6 news", "GTA 6 leak",
            "Jason", "Lucia", "GTA 6 map",
        ),
        rss_feeds=(
            "https://www.eurogamer.net/?format=rss",
            "https://www.videogameschronicle.com/feed",
        ),
        youtube_channels=(
            "UCdFoQjLgY9nOwCJNOE9vSJw",  # Rockstar Games
        ),
        subreddits=("GTAVI", "GrandTheftAuto", "GTA"),
        language="en-US",
    ),
    editorial=EditorialConfig(
        tone="informative_enthusiastic",
        target_audience="global_gamers_18_35",
        content_types=("news", "curiosities", "theories", "gameplay", "leaks_analysis"),
        banned_topics=("unverified_spoilers",),
        fact_check_required=True,
    ),
    publishing=PublishingConfig(
        default_hashtags=(
            "#GTA6", "#GTAVI", "#ViceCity", "#RockstarGames",
            "#ViceCityRadarGlobal", "#Gaming", "#GTA6News",
        ),
        timezone="America/New_York",
    ),
    enabled=True,
)

ALL_PROFILES: dict[str, ProfileConfig] = {
    "gta6": GTA6_PROFILE,
    "gta6-br": GTA6_BR_PROFILE,
    "gta6-global": GTA6_GLOBAL_PROFILE,
    "marvel-dc": MARVEL_DC_PROFILE,
    "anime": ANIME_PROFILE,
    "futuro": FUTURO_PROFILE,
    "game": GAME_PROFILE,
    "cine": CINE_PROFILE,
    "beat": BEAT_PROFILE,
}


def get_profile(profile_id: str) -> ProfileConfig:
    if profile_id not in ALL_PROFILES:
        raise ValueError(f"Unknown profile: {profile_id}. Available: {list(ALL_PROFILES.keys())}")
    return ALL_PROFILES[profile_id]


def list_profiles() -> list[ProfileConfig]:
    return list(ALL_PROFILES.values())