"""Convert structured scripts into visual scene sequences.

Parses script sections (HOOK, CONTEXTO, DESENVOLVIMENTO, CTA) and maps
them to SceneSpec objects for the SceneComposer. This bridges the gap
between text-only scripts and visual Reel production.
"""

from __future__ import annotations

import re
import logging
from pathlib import Path

from src.production.scene_composer import SceneSpec

logger = logging.getLogger(__name__)

# Section markers used in ScriptWriter templates
SECTION_PATTERN = re.compile(
    r"\[(HOOK|CONTEXTO|DESENVOLVIMENTO|CURIOSIDADE|TEORIA|ANÁLISE|DETALHES|"
    r"O QUE FOI ANUNCIADO|IMPACTO|CTA)\s*-\s*(\d+)s\]",
    re.IGNORECASE,
)


def parse_script_to_scenes(script_text: str) -> list[SceneSpec]:
    """Parse a structured script into ordered scene specifications.

    Args:
        script_text: Full script with section markers like [HOOK - 3s]

    Returns:
        List of SceneSpec objects ready for SceneComposer
    """
    scenes: list[SceneSpec] = []
    sections = _split_sections(script_text)

    for marker, duration, content in sections:
        scene_type = _map_marker_to_scene_type(marker)
        style = _infer_style(marker)

        # Split long content into subtitle chunks (~40 chars per line)
        subtitle = _extract_subtitle(content)

        scenes.append(SceneSpec(
            scene_type=scene_type,
            text=content.strip(),
            duration_seconds=float(duration),
            style=style,
            subtitle_text=subtitle,
        ))

    if not scenes:
        logger.warning("No sections found in script; creating single default scene")
        scenes.append(SceneSpec(
            scene_type="default",
            text=script_text.strip()[:200],
            duration_seconds=15.0,
            subtitle_text=script_text.strip()[:80],
        ))

    logger.info("Parsed %d scenes from script (%.1fs total)",
                len(scenes), sum(s.duration_seconds for s in scenes))
    return scenes


def _split_sections(text: str) -> list[tuple[str, str, str]]:
    """Split script text into (marker, duration, content) tuples."""
    matches = list(SECTION_PATTERN.finditer(text))
    if not matches:
        return []

    results: list[tuple[str, str, str]] = []
    for i, match in enumerate(matches):
        marker = match.group(1).upper()
        duration = match.group(2)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        if content:
            results.append((marker, duration, content))

    return results


def _map_marker_to_scene_type(marker: str) -> str:
    """Map script section marker to scene type."""
    mapping = {
        "HOOK": "hook",
        "CONTEXTO": "info_card",
        "DESENVOLVIMENTO": "default",
        "CURIOSIDADE": "info_card",
        "TEORIA": "title_card",
        "ANÁLISE": "default",
        "DETALHES": "info_card",
        "O QUE FOI ANUNCIADO": "title_card",
        "IMPACTO": "default",
        "CTA": "cta",
    }
    return mapping.get(marker, "default")


def _infer_style(marker: str) -> str:
    """Infer visual style from section marker."""
    if marker == "HOOK":
        return "highlight"
    if marker == "CTA":
        return "accent"
    if marker in ("TEORIA", "O QUE FOI ANUNCIADO"):
        return "dark"
    return "default"


def _extract_subtitle(content: str, max_chars: int = 80) -> str:
    """Extract first meaningful line as subtitle text."""
    lines = [l.strip() for l in content.split("\n") if l.strip()]
    if not lines:
        return ""
    # Take first non-empty line, truncate if needed
    subtitle = lines[0]
    if len(subtitle) > max_chars:
        subtitle = subtitle[:max_chars - 3] + "..."
    return subtitle


async def script_file_to_scenes(script_path: Path) -> list[SceneSpec]:
    """Load a script file and convert to scenes."""
    text = script_path.read_text(encoding="utf-8")
    return parse_script_to_scenes(text)