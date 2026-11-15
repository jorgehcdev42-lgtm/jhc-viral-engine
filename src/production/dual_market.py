"""Dual Market Engine — Geração simultânea BR + Global com identidade própria.

Adapta roteiro, narração, legendas, logo, thumbnail, título, descrição,
hashtags e CTA para cada mercado. Não faz tradução literal — adapta
linguagem editorial ao público-alvo.

Canais:
- BR: Leonida GTA VI Flash BR (pt-BR)
- Global: Leonida GTA VI Flash Global (en)
"""

import json
import time
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

@dataclass
class MarketIdentity:
    market: str
    language: str
    channel_name: str
    title_template: str
    description_template: str
    hashtags: list[str]
    cta_text: str
    subtitle_style: dict = field(default_factory=dict)
    watermark_config: dict = field(default_factory=dict)
    thumbnail_style: dict = field(default_factory=dict)

BR_IDENTITY = MarketIdentity(
    market="br",
    language="pt-BR",
    channel_name="Leonida GTA VI Flash BR",
    title_template="{topic} | GTA VI Leonida 🔥 #{tag}",
    description_template="🎮 {topic}\n\n📍 Leonida, GTA VI\n🔔 Inscreva-se no {channel}\n👍 Deixe o like se curtiu!\n\n#gta6 #leonida #gta6br #rockstargames",
    hashtags=["gta6", "leonida", "gta6br", "rockstargames", "gta6news", "gta6update"],
    cta_text="🔔 Se inscreve e ativa o sininho!",
    subtitle_style={"font_size": 28, "color": "white", "border_color": "black", "border_width": 2},
    watermark_config={"position": "top_right", "opacity": 0.7},
    thumbnail_style={"title_color": "#FFD700", "bg_gradient": "#1a0a2e→#2d1b69"},
)

GLOBAL_IDENTITY = MarketIdentity(
    market="global",
    language="en",
    channel_name="Leonida GTA VI Flash Global",
    title_template="{topic} | GTA VI Leonida 🔥 #{tag}",
    description_template="🎮 {topic}\n\n📍 Leonida, GTA VI\n🔔 Subscribe to {channel}\n👍 Like if you enjoyed!\n\n#gta6 #leonida #gta6global #rockstargames",
    hashtags=["gta6", "leonida", "gta6global", "rockstargames", "gta6news", "gta6leaks"],
    cta_text="🔔 Subscribe and hit the bell!",
    subtitle_style={"font_size": 26, "color": "white", "border_color": "black", "border_width": 2},
    watermark_config={"position": "top_right", "opacity": 0.7},
    thumbnail_style={"title_color": "#00BFFF", "bg_gradient": "#0a1628→#1b3a5c"},
)

MARKET_IDENTITIES = {"br": BR_IDENTITY, "global": GLOBAL_IDENTITY}

@dataclass
class DualMarketOutput:
    market: str
    title: str
    description: str
    hashtags: list[str]
    cta: str
    subtitle_text: str
    language: str
    channel: str
    reel_request: dict = field(default_factory=dict)
    status: str = "pending"
    output_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


class DualMarketEngine:
    """Gera versões BR e Global do mesmo conteúdo com identidade própria."""

    def __init__(self, data_root: str = "data"):
        self.data_root = Path(data_root)
        self.output_dir = self.data_root / "dual_market"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def adapt_content(self, topic: str, base_subtitle: str = "",
                      custom_title: str = "") -> dict[str, DualMarketOutput]:
        """Adapta conteúdo para ambos os mercados."""
        results = {}

        for market_key, identity in MARKET_IDENTITIES.items():
            tag = topic.replace(" ", "").lower()[:20]
            title = custom_title or identity.title_template.format(topic=topic, tag=tag)
            description = identity.description_template.format(
                topic=topic, channel=identity.channel_name
            )

            # Adaptação de legenda: não é tradução literal
            if market_key == "br":
                subtitle = base_subtitle or f"GTA VI em Leonida — tudo sobre {topic}"
            else:
                subtitle = self._adapt_to_english(base_subtitle, topic)

            output = DualMarketOutput(
                market=market_key,
                title=title,
                description=description,
                hashtags=identity.hashtags,
                cta=identity.cta_text,
                subtitle_text=subtitle,
                language=identity.language,
                channel=identity.channel_name,
                reel_request={
                    "market": market_key,
                    "subtitle_text": subtitle,
                    "custom_title": title,
                    "logo_path": str(self.data_root / "branding" / f"logo_{market_key}.png"),
                },
            )
            results[market_key] = output

        return results

    def _adapt_to_english(self, pt_text: str, topic: str) -> str:
        """Adaptação editorial para inglês — não tradução literal."""
        if not pt_text:
            return f"GTA VI in Leonida — everything about {topic}"

        # Mapeamento de padrões comuns PT→EN editoriais
        adaptations = {
            "tudo sobre": "everything about",
            "novidades": "latest news",
            "atualização": "update",
            "vazou": "leaked",
            "confirmado": "confirmed",
            "gameplay": "gameplay",
            "trailer": "trailer",
            "mapa": "map",
            "personagens": "characters",
            "missões": "missions",
            "detalhes": "details",
            "exclusivo": "exclusive",
            "análise": "breakdown",
            "review": "review",
        }

        result = pt_text.lower()
        for pt, en in adaptations.items():
            result = result.replace(pt, en)

        # Capitaliza primeira letra
        return result.capitalize() if result else f"GTA VI Leonida — {topic}"

    def produce_dual(self, video_path: str, topic: str,
                     platform: str = "reels",
                     base_subtitle: str = "") -> dict:
        """Produz versões BR e Global a partir do mesmo vídeo fonte."""
        from src.production.auto_reel import AutoReelStudio, ReelRequest

        adapted = self.adapt_content(topic, base_subtitle)
        studio = AutoReelStudio(data_root=str(self.data_root))
        results = {}

        for market_key, output in adapted.items():
            try:
                request = ReelRequest(
                    video_path=video_path,
                    market=market_key,
                    platform=platform,
                    subtitle_text=output.subtitle_text,
                    custom_title=output.title,
                    logo_path=output.reel_request.get("logo_path", ""),
                    include_music=True,
                )

                progress = studio.produce(request)

                output.status = progress.status
                output.output_path = progress.output_path
                output.thumbnail_path = progress.thumbnail_path
                output.error = progress.error

            except Exception as e:
                output.status = "failed"
                output.error = str(e)

            results[market_key] = output.to_dict()

        # Salva metadata do job dual
        job_id = f"dual_{int(time.time())}"
        meta_path = self.output_dir / f"{job_id}.json"
        meta_path.write_text(json.dumps({
            "job_id": job_id,
            "topic": topic,
            "platform": platform,
            "source_video": video_path,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "markets": results,
        }, indent=2))

        return {
            "job_id": job_id,
            "topic": topic,
            "markets": results,
            "metadata_path": str(meta_path),
        }

    def list_jobs(self) -> list[dict]:
        """Lista jobs dual market anteriores."""
        results = []
        for f in sorted(self.output_dir.glob("dual_*.json"), reverse=True):
            try:
                data = json.loads(f.read_text())
                results.append({
                    "job_id": data["job_id"],
                    "topic": data["topic"],
                    "platform": data.get("platform", "unknown"),
                    "created_at": data["created_at"],
                    "br_status": data["markets"].get("br", {}).get("status", "unknown"),
                    "global_status": data["markets"].get("global", {}).get("status", "unknown"),
                })
            except Exception:
                continue
        return results

    def get_identity(self, market: str) -> dict:
        """Retorna configuração de identidade de um mercado."""
        identity = MARKET_IDENTITIES.get(market)
        if not identity:
            return {"error": f"Mercado '{market}' não encontrado"}
        return asdict(identity)