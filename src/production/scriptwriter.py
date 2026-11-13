"""Reel scriptwriter for JHC Viral Engine.

Generates original pt-BR scripts optimized for short-form video.
Supports LLM backends (Claude API, Ollama) with deterministic fallback.

Script structure:
- Hook (0-3s): attention-grabbing opening
- Context (5-10s): essential information
- Development (15-40s): details, analysis, curiosities
- CTA (3-5s): follow/comment/share prompt
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

from src.core.profile_config import ProfileConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScriptResult:
    """Generated script with metadata."""
    text: str
    hook: str
    body: str
    cta: str
    caption: str
    hashtags: tuple[str, ...]
    source_topic: str
    llm_used: bool = False
    model: str = "fallback"


# --- Editorial templates per content category ---

TEMPLATES: dict[str, str] = {
    "news": """[HOOK - 3s]
{hook}

[CONTEXTO - 8s]
{context}

[DESENVOLVIMENTO - {dev_duration}s]
{development}

[CTA - 4s]
{cta}""",
    "curiosities": """[HOOK - 3s]
Você sabia que {hook}?

[CONTEXTO - 8s]
{context}

[CURIOSIDADE - {dev_duration}s]
{development}

[CTA - 4s]
{cta}""",
    "theory": """[HOOK - 3s]
E se {hook}?

[TEORIA - 10s]
{context}

[ANÁLISE - {dev_duration}s]
{development}

[CTA - 4s]
{cta}""",
    "countdown": """[HOOK - 2s]
Faltam apenas {hook}!

[CONTEXTO - 8s]
{context}

[DETALHES - {dev_duration}s]
{development}

[CTA - 4s]
{cta}""",
    "announcement": """[HOOK - 3s]
{hook}!

[O QUE FOI ANUNCIADO - 10s]
{context}

[IMPACTO - {dev_duration}s]
{development}

[CTA - 4s]
{cta}""",
}

DEFAULT_TEMPLATE = TEMPLATES["news"]


class ScriptWriter:
    """Generate Reel scripts tailored to a profile's editorial config."""

    def __init__(self, profile: ProfileConfig) -> None:
        self.profile = profile
        self._llm_provider: Optional[str] = None
        self._detect_llm()

    def _detect_llm(self) -> None:
        """Detect available LLM provider without exposing credentials."""
        # Check for Claude API key
        if os.environ.get("ANTHROPIC_API_KEY"):
            self._llm_provider = "claude"
            logger.info("LLM provider detected: Claude API")
            return

        # Check for Ollama (local)
        try:
            req = Request("http://localhost:11434/api/tags", method="GET")
            with urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    self._llm_provider = "ollama"
                    logger.info("LLM provider detected: Ollama (local)")
                    return
        except (URLError, OSError, TimeoutError):
            pass

        # Check for OpenAI-compatible endpoint (e.g., 8token gateway)
        if os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENAI_BASE_URL"):
            self._llm_provider = "openai_compat"
            logger.info("LLM provider detected: OpenAI-compatible endpoint")
            return

        logger.info("No LLM provider detected; using deterministic fallback")

    async def generate(
        self,
        topic: str,
        source_summary: str = "",
        category: str = "news",
    ) -> ScriptResult:
        """Generate a complete Reel script for the given topic.

        Args:
            topic: News headline or subject
            source_summary: Verified information from research phase
            category: Content type (news/curiosities/theory/countdown/announcement)

        Returns:
            ScriptResult with structured script sections
        """
        logger.info(
            "Generating script: profile=%s topic='%s' category=%s llm=%s",
            self.profile.profile_id,
            topic[:50],
            category,
            self._llm_provider or "fallback",
        )

        if self._llm_provider:
            result = await self._generate_with_llm(topic, source_summary, category)
            if result is not None:
                return result
            logger.warning("LLM generation failed; falling back to template")

        return self._generate_fallback(topic, source_summary, category)

    async def _generate_with_llm(
        self,
        topic: str,
        source_summary: str,
        category: str,
    ) -> Optional[ScriptResult]:
        """Attempt LLM-based script generation. Returns None on failure."""
        prompt = self._build_prompt(topic, source_summary, category)

        try:
            if self._llm_provider == "ollama":
                return await self._call_ollama(prompt, topic, category)
            elif self._llm_provider == "claude":
                return await self._call_claude(prompt, topic, category)
            elif self._llm_provider == "openai_compat":
                return await self._call_openai_compat(prompt, topic, category)
        except Exception as exc:
            logger.error("LLM call failed (%s): %s", self._llm_provider, exc)

        return None

    def _build_prompt(self, topic: str, source_summary: str, category: str) -> str:
        """Build LLM prompt for script generation."""
        tone = self.profile.editorial.tone
        audience = self.profile.editorial.target_audience
        max_dur = self.profile.editorial.max_reel_duration_seconds
        hashtags = " ".join(self.profile.publishing.default_hashtags)

        return f"""Crie um roteiro ORIGINAL em português do Brasil para um Reel de Instagram.

PERFIL: {self.profile.name}
PÚBLICO: {audience}
TOM: {tone}
DURAÇÃO MÁXIMA: {max_dur} segundos
CATEGORIA: {category}

TÓPICO: {topic}

INFORMAÇÕES VERIFICADAS DA FONTE:
{source_summary if source_summary else "(Use apenas informações confirmadas sobre este tópico)"}

ESTRUTURA OBRIGATÓRIA:
1. GANCHO (0-3s): Frase impactante que prenda atenção imediatamente
2. CONTEXTO (5-10s): Informação essencial
3. DESENVOLVIMENTO (15-{max_dur - 20}s): Detalhes, análise ou curiosidades
4. CTA (3-5s): Chamada para seguir/comentar/compartilhar

REGRAS:
- NÃO invente informações não confirmadas
- Use linguagem dinâmica e direta
- Inclua sugestões visuais entre parênteses
- Termine com hashtags relevantes: {hashtags}

Responda APENAS com JSON válido:
{{
  "hook": "texto do gancho",
  "context": "texto do contexto",
  "development": "texto do desenvolvimento",
  "cta": "texto da chamada para ação",
  "caption": "descrição completa do post",
  "hashtags": ["#tag1", "#tag2", "..."]
}}"""

    async def _call_ollama(
        self, prompt: str, topic: str, category: str
    ) -> Optional[ScriptResult]:
        """Call local Ollama instance."""
        payload = json.dumps({
            "model": os.environ.get("OLLAMA_MODEL", "llama3"),
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": 1024},
        }).encode()

        req = Request(
            "http://localhost:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())

        response_text = data.get("response", "")
        return self._parse_llm_response(response_text, topic, category, "ollama")

    async def _call_claude(
        self, prompt: str, topic: str, category: str
    ) -> Optional[ScriptResult]:
        """Call Claude API."""
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        payload = json.dumps({
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()

        req = Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        with urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())

        content = data.get("content", [])
        if content and isinstance(content, list):
            response_text = content[0].get("text", "")
            return self._parse_llm_response(response_text, topic, category, "claude")
        return None

    async def _call_openai_compat(
        self, prompt: str, topic: str, category: str
    ) -> Optional[ScriptResult]:
        """Call OpenAI-compatible endpoint (e.g., 8token gateway)."""
        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        api_key = os.environ.get("OPENAI_API_KEY", "")
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1024,
            "temperature": 0.7,
        }).encode()

        req = Request(
            f"{base_url}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())

        choices = data.get("choices", [])
        if choices:
            response_text = choices[0].get("message", {}).get("content", "")
            return self._parse_llm_response(response_text, topic, category, model)
        return None

    def _parse_llm_response(
        self,
        response: str,
        topic: str,
        category: str,
        model: str,
    ) -> Optional[ScriptResult]:
        """Parse JSON response from LLM into ScriptResult."""
        # Try to extract JSON from response (LLMs sometimes add markdown fences)
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM JSON response")
            return None

        required_keys = {"hook", "context", "development", "cta"}
        if not required_keys.issubset(data.keys()):
            logger.warning("LLM response missing required keys: %s", required_keys - set(data.keys()))
            return None

        hook = data["hook"]
        context = data["context"]
        development = data["development"]
        cta = data["cta"]
        caption = data.get("caption", f"{hook}\n\n{context}\n\n{development}")
        hashtags = tuple(data.get("hashtags", list(self.profile.publishing.default_hashtags)))

        template = TEMPLATES.get(category, DEFAULT_TEMPLATE)
        max_dur = self.profile.editorial.max_reel_duration_seconds
        dev_duration = max_dur - 20

        full_text = template.format(
            hook=hook,
            context=context,
            development=development,
            cta=cta,
            dev_duration=dev_duration,
        )

        return ScriptResult(
            text=full_text,
            hook=hook,
            body=f"{context}\n\n{development}",
            cta=cta,
            caption=caption,
            hashtags=hashtags,
            source_topic=topic,
            llm_used=True,
            model=model,
        )

    def _generate_fallback(
        self,
        topic: str,
        source_summary: str,
        category: str,
    ) -> ScriptResult:
        """Deterministic fallback when no LLM is available."""
        max_dur = self.profile.editorial.max_reel_duration_seconds
        dev_duration = max_dur - 20
        tone = self.profile.editorial.tone
        audience = self.profile.editorial.target_audience
        hashtags = self.profile.publishing.default_hashtags

        # Build content based on available information
        summary_clean = source_summary.strip() if source_summary else ""

        if category == "news" and summary_clean:
            hook = f"Novidade sobre {topic}"
            context = summary_clean[:200] if summary_clean else f"Informações recentes sobre {topic}."
            development = (
                f"Essa notícia é relevante para {audience}. "
                f"Com tom {tone}, vamos analisar o impacto disso."
            )
        elif category == "countdown":
            hook = f"Faltam poucos dias para {topic}"
            context = f"A contagem regressiva para {topic} continua!"
            development = (
                f"Tudo indica que {topic} será um marco importante. "
                f"Fique ligado para mais atualizações."
            )
        elif category == "curiosities":
            hook = f"algo surpreendente sobre {topic}"
            context = f"Muitos fãs de {self.profile.name} não sabem disso."
            development = (
                f"Essa curiosidade sobre {topic} mostra detalhes "
                f"que passam despercebidos pela maioria."
            )
        else:
            hook = f"Tudo sobre {topic}"
            context = summary_clean[:200] if summary_clean else f"Vamos falar sobre {topic}."
            development = (
                f"Se você acompanha {self.profile.name}, "
                f"sabe que {topic} é um assunto importante."
            )

        cta = "Segue o perfil para mais conteúdos como esse!"
        caption = f"{hook}\n\n{context}\n\n{development}\n\n{cta}"

        template = TEMPLATES.get(category, DEFAULT_TEMPLATE)
        full_text = template.format(
            hook=hook,
            context=context,
            development=development,
            cta=cta,
            dev_duration=dev_duration,
        )

        return ScriptResult(
            text=full_text,
            hook=hook,
            body=f"{context}\n\n{development}",
            cta=cta,
            caption=caption,
            hashtags=hashtags,
            source_topic=topic,
            llm_used=False,
            model="fallback",
        )