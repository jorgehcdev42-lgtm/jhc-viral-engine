"""Tests for ScriptWriter with LLM support and deterministic fallback."""

from __future__ import annotations

import json
import pytest

from src.core.profile_config import GTA6_PROFILE
from src.production.scriptwriter import ScriptWriter, ScriptResult, TEMPLATES


@pytest.fixture
def writer() -> ScriptWriter:
    return ScriptWriter(GTA6_PROFILE)


class TestScriptWriterFallback:
    """Test deterministic fallback (no LLM required)."""

    @pytest.mark.asyncio
    async def test_generate_returns_script_result(self, writer: ScriptWriter) -> None:
        result = await writer.generate("GTA 6 trailer novo", category="news")
        assert isinstance(result, ScriptResult)
        assert result.text
        assert result.hook
        assert result.body
        assert result.cta
        assert result.source_topic == "GTA 6 trailer novo"

    @pytest.mark.asyncio
    async def test_fallback_when_no_llm(self, writer: ScriptWriter) -> None:
        # Force no LLM provider
        writer._llm_provider = None
        result = await writer.generate("GTA 6 novidades", category="news")
        assert result.llm_used is False
        assert result.model == "fallback"
        assert "GTA 6 novidades" in result.text

    @pytest.mark.asyncio
    async def test_countdown_category(self, writer: ScriptWriter) -> None:
        writer._llm_provider = None
        result = await writer.generate(
            "lançamento GTA VI", category="countdown"
        )
        assert "Faltam" in result.hook or "contagem" in result.text.lower()

    @pytest.mark.asyncio
    async def test_curiosities_category(self, writer: ScriptWriter) -> None:
        writer._llm_provider = None
        result = await writer.generate(
            "segredos de Vice City", category="curiosities"
        )
        assert "sabia" in result.text.lower() or "curiosidade" in result.text.lower()

    @pytest.mark.asyncio
    async def test_theory_category(self, writer: ScriptWriter) -> None:
        writer._llm_provider = None
        result = await writer.generate(
            "Jason é o protagonista", category="theory"
        )
        assert "E se" in result.hook or "teoria" in result.text.lower()

    @pytest.mark.asyncio
    async def test_hashtags_from_profile(self, writer: ScriptWriter) -> None:
        writer._llm_provider = None
        result = await writer.generate("GTA 6 leak", category="news")
        assert len(result.hashtags) > 0
        assert "#GTA6" in result.hashtags

    @pytest.mark.asyncio
    async def test_caption_not_empty(self, writer: ScriptWriter) -> None:
        writer._llm_provider = None
        result = await writer.generate("GTA 6 mapa", category="news")
        assert len(result.caption) > 10

    @pytest.mark.asyncio
    async def test_source_summary_used_in_fallback(self, writer: ScriptWriter) -> None:
        writer._llm_provider = None
        summary = "Rockstar confirmou que GTA 6 terá dois protagonistas jogáveis."
        result = await writer.generate(
            "GTA 6 protagonistas", source_summary=summary, category="news"
        )
        assert "protagonistas" in result.text.lower() or summary[:50] in result.text


class TestScriptWriterLLMParsing:
    """Test LLM response parsing logic."""

    def test_parse_valid_json_response(self, writer: ScriptWriter) -> None:
        response = json.dumps({
            "hook": "GTA 6 finalmente chegou!",
            "context": "Depois de anos de espera, Rockstar revelou...",
            "development": "O jogo traz Vice City reimaginada com...",
            "cta": "Segue pra mais novidades!",
            "caption": "GTA 6 tá chegando! 🎮",
            "hashtags": ["#GTA6", "#ViceCity"],
        })
        result = writer._parse_llm_response(response, "GTA 6", "news", "test-model")
        assert result is not None
        assert result.llm_used is True
        assert result.model == "test-model"
        assert result.hook == "GTA 6 finalmente chegou!"

    def test_parse_json_in_markdown_fence(self, writer: ScriptWriter) -> None:
        response = '```json\n{"hook": "Novidade!", "context": "Info", "development": "Detalhes", "cta": "Segue!"}\n```'
        result = writer._parse_llm_response(response, "test", "news", "ollama")
        assert result is not None
        assert result.hook == "Novidade!"

    def test_parse_invalid_json_returns_none(self, writer: ScriptWriter) -> None:
        result = writer._parse_llm_response("not valid json at all", "test", "news", "x")
        assert result is None

    def test_parse_missing_keys_returns_none(self, writer: ScriptWriter) -> None:
        response = json.dumps({"hook": "only hook"})
        result = writer._parse_llm_response(response, "test", "news", "x")
        assert result is None

    def test_templates_exist_for_all_categories(self) -> None:
        expected = {"news", "curiosities", "theory", "countdown", "announcement"}
        assert expected.issubset(TEMPLATES.keys())

    def test_template_formatting(self) -> None:
        template = TEMPLATES["news"]
        rendered = template.format(
            hook="Teste", context="Contexto", development="Dev", cta="CTA", dev_duration=30
        )
        assert "[HOOK - 3s]" in rendered
        assert "Teste" in rendered
        assert "30" in rendered


class TestLLMDetection:
    """Test LLM provider detection without exposing credentials."""

    def test_detect_without_env_vars(self) -> None:
        """Without API keys, should fall back gracefully."""
        import os
        # Save and clear relevant env vars
        saved = {}
        for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL"):
            if key in os.environ:
                saved[key] = os.environ.pop(key)
        try:
            w = ScriptWriter(GTA6_PROFILE)
            # Should be None or ollama (if running locally)
            assert w._llm_provider in (None, "ollama")
        finally:
            os.environ.update(saved)