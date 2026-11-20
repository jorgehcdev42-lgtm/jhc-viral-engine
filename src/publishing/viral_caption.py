"""Viral Caption Generator for JHC Viral Engine.

Generates engaging, platform-optimized captions with hooks, CTAs,
and strategic hashtags for TikTok, Instagram Reels, and YouTube Shorts.
No external API required — uses template-based generation with
randomization to avoid repetition.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

# --- Hook templates (first line — stops the scroll) ---
HOOKS_PT = [
    "🔥 VOCÊ NÃO VAI ACREDITAR NO QUE VAZOU DE GTA VI!",
    "⚡ GTA VI: A informação que muda TUDO!",
    "🚨 ATENÇÃO FÃS DE GTA: Isso é REAL!",
    "💣 Rockstar acabou de confirmar e ninguém percebeu!",
    "🎮 GTA VI: O detalhe que TODO MUNDO ignorou!",
    "😱 LEONIDA: A verdade sobre a nova protagonista!",
    "🔍 Analisamos frame por frame e encontramos ISSO!",
    "⏰ GTA VI está mais perto do que você pensa!",
    "🗺️ Vice City nunca esteve tão real assim!",
    "🤯 O que a Rockstar ESCONDEU no último trailer!",
    "📢 URGENTE: Nova informação sobre GTA VI!",
    "🎯 GTA VI: Tudo que sabemos ATÉ AGORA!",
    "💀 A cena que vai chocar todo mundo em GTA VI!",
    "🌴 Leonida + Vice City = COMBINAÇÃO PERFEITA!",
    "🏎️ Os carros de GTA VI são INSANOS!",
]

HOOKS_EN = [
    "🔥 You WON'T BELIEVE what just leaked about GTA VI!",
    "⚡ GTA VI: The info that changes EVERYTHING!",
    "🚨 GTA FANS: This is REAL!",
    "💣 Rockstar just confirmed and nobody noticed!",
    "🎮 GTA VI: The detail EVERYONE missed!",
    "😱 LEONIDA: The truth about the new protagonist!",
    "🔍 We analyzed frame by frame and found THIS!",
    "⏰ GTA VI is closer than you think!",
    "🗺️ Vice City has never looked this real!",
    "🤯 What Rockstar HID in the latest trailer!",
]

# --- Body templates (middle — delivers value) ---
BODIES_PT = [
    "Neste vídeo revelamos {topic}. Fique até o final porque a informação mais importante vem depois! 👇",
    "Analisamos cada detalhe de {topic} e o resultado vai te surpreender. Confira! 🔥",
    "{topic} — separamos tudo que importa em menos de 1 minuto. Salva pra não perder! 📌",
    "A comunidade está falando sobre {topic} e nós trouxemos a análise completa. Assista! 🎬",
    "Descobrimos {topic} e você PRECISA ver isso antes de todo mundo! ⚡",
    "{topic}: compilamos as melhores informações num só lugar. Compartilha com quem ama GTA! 🎮",
    "Tudo sobre {topic} resumido pra você. Comenta aí o que achou! 💬",
    "Se você curte GTA VI, {topic} vai explodir sua mente! 🧠💥",
]

BODIES_EN = [
    "In this video we reveal {topic}. Stay until the end because the most important info comes last! 👇",
    "We analyzed every detail of {topic} and the result will surprise you. Check it out! 🔥",
    "{topic} — we packed everything that matters in under 1 minute. Save so you don't miss it! 📌",
    "The community is talking about {topic} and we brought the full breakdown. Watch now! 🎬",
]

# --- CTA templates (last line — drives engagement) ---
CTAS_PT = [
    "👉 Segue @leonidagta6flashbr para mais conteúdo exclusivo de GTA VI!",
    "💬 Comenta: qual sua teoria sobre GTA VI?",
    "🔔 Ativa o sininho pra não perder nenhuma novidade!",
    "❤️ Curte se você também tá ansioso pro GTA VI!",
    "📲 Compartilha com seu amigo que AMA GTA!",
    "🎮 Qual feature você MAIS quer ver em GTA VI? Comenta aí!",
    "⭐ Salva esse vídeo pra rever depois!",
    "🔄 Reposta se concorda!",
]

CTAS_EN = [
    "👉 Follow @leonidagta6flashbr for exclusive GTA VI content!",
    "💬 Comment: what's your GTA VI theory?",
    "🔔 Turn on notifications so you never miss an update!",
    "❤️ Like if you're also hyped for GTA VI!",
    "📲 Share with your friend who LOVES GTA!",
]

# --- Hashtag sets by platform ---
HASHTAGS_TIKTOK = [
    "#gta6", "#gtavi", "#leonida", "#rockstargames", "#vicecity",
    "#gta6brasil", "#gtavinovidades", "#gaming", "#shorts",
    "#fyp", "#viral", "#gta6trailer", "#gta6gameplay",
    "#grandtheftauto", "#gtaVIleaks", "#gta6news",
]

HASHTAGS_INSTAGRAM = [
    "#gta6", "#gtavi", "#leonida", "#rockstargames", "#vicecity",
    "#gta6brasil", "#gtavinovidades", "#gaming", "#reels",
    "#grandtheftauto", "#gta6trailer", "#gta6gameplay",
    "#gtacommunity", "#gamers", "#gtaVI",
]

HASHTAGS_YOUTUBE = [
    "#GTA6", "#GTAVI", "#Leonida", "#RockstarGames", "#ViceCity",
    "#GTA6Brasil", "#Shorts", "#Gaming", "#GTA6Trailer",
    "#GrandTheftAuto", "#GTA6News",
]

TOPIC_KEYWORDS = [
    "trailer", "gameplay", "vazamento", "leak", "novidade", "notícia",
    "personagem", "mapa", "carro", "missão", "data", "lançamento",
    "curiosidade", "detalhe", "análise", "review", "comparação",
    "protagonista", "Leonida", "Vice City", "Rockstar",
]


@dataclass(frozen=True)
class ViralCaption:
    """Generated viral caption with metadata."""
    hook: str
    body: str
    cta: str
    hashtags: list[str]
    full_text: str
    platform: str
    language: str
    char_count: int


def generate_viral_caption(
    platform: str = "tiktok",
    language: str = "pt",
    topic_hint: str = "",
    max_hashtags: int = 8,
    max_chars: int = 2200,
) -> ViralCaption:
    """Generate a viral caption optimized for the target platform.

    Args:
        platform: "tiktok", "instagram", or "youtube"
        language: "pt" (Portuguese) or "en" (English)
        topic_hint: optional keyword to personalize the body text
        max_hashtags: maximum number of hashtags to include
        max_chars: maximum character count for the full caption

    Returns:
        ViralCaption with all components assembled
    """
    # Select hook
    hooks = HOOKS_PT if language == "pt" else HOOKS_EN
    hook = random.choice(hooks)

    # Select and customize body
    bodies = BODIES_PT if language == "pt" else BODIES_EN
    body_template = random.choice(bodies)
    topic = topic_hint if topic_hint else random.choice(TOPIC_KEYWORDS)
    body = body_template.format(topic=topic)

    # Select CTA
    ctas = CTAS_PT if language == "pt" else CTAS_EN
    cta = random.choice(ctas)

    # Select hashtags by platform
    if platform == "tiktok":
        hashtag_pool = HASHTAGS_TIKTOK
    elif platform == "instagram":
        hashtag_pool = HASHTAGS_INSTAGRAM
    elif platform == "youtube":
        hashtag_pool = HASHTAGS_YOUTUBE
    else:
        hashtag_pool = HASHTAGS_TIKTOK

    selected_hashtags = random.sample(hashtag_pool, min(max_hashtags, len(hashtag_pool)))

    # Assemble full caption
    full_text = f"{hook}\n\n{body}\n\n{cta}\n\n{' '.join(selected_hashtags)}"

    # Trim if over max chars
    if len(full_text) > max_chars:
        while len(full_text) > max_chars and selected_hashtags:
            selected_hashtags.pop()
            full_text = f"{hook}\n\n{body}\n\n{cta}\n\n{' '.join(selected_hashtags)}"

    return ViralCaption(
        hook=hook,
        body=body,
        cta=cta,
        hashtags=selected_hashtags,
        full_text=full_text,
        platform=platform,
        language=language,
        char_count=len(full_text),
    )


def generate_batch(
    count: int = 5,
    platform: str = "tiktok",
    language: str = "pt",
) -> list[ViralCaption]:
    """Generate multiple unique captions."""
    results = []
    seen_hooks: set[str] = set()
    attempts = 0
    while len(results) < count and attempts < count * 3:
        cap = generate_viral_caption(platform=platform, language=language)
        if cap.hook not in seen_hooks:
            seen_hooks.add(cap.hook)
            results.append(cap)
        attempts += 1
    return results