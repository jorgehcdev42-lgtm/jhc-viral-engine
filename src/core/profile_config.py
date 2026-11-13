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
    name="Vice City Radar",
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

ALL_PROFILES: dict[str, ProfileConfig] = {
    "gta6": GTA6_PROFILE,
    "marvel-dc": MARVEL_DC_PROFILE,
}


def get_profile(profile_id: str) -> ProfileConfig:
    if profile_id not in ALL_PROFILES:
        raise ValueError(f"Unknown profile: {profile_id}. Available: {list(ALL_PROFILES.keys())}")
    return ALL_PROFILES[profile_id]


def list_profiles() -> list[ProfileConfig]:
    return list(ALL_PROFILES.values())