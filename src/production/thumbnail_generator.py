"""Thumbnail/cover generator for JHC Viral Engine Reels.

Generates Instagram-compatible cover images using Pillow.
Creates visually compelling thumbnails with profile identity,
hook text, and branding elements.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from src.production.scene_composer import VisualIdentity, GTA6_IDENTITY, WIDTH, HEIGHT

logger = logging.getLogger(__name__)


class ThumbnailGenerator:
    """Generate cover/thumbnail images for Reels."""

    def __init__(self, identity: Optional[VisualIdentity] = None) -> None:
        self.identity = identity or GTA6_IDENTITY
        self._font_cache: dict[str, ImageFont.FreeTypeFont] = {}

    def _get_font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        key = f"{'bold' if bold else 'regular'}_{size}"
        if key not in self._font_cache:
            path = self.identity.font_bold if bold else self.identity.font_regular
            try:
                self._font_cache[key] = ImageFont.truetype(path, size)
            except (OSError, IOError):
                self._font_cache[key] = ImageFont.load_default()
        return self._font_cache[key]

    def _create_gradient_bg(self) -> Image.Image:
        img = Image.new("RGB", (WIDTH, HEIGHT))
        draw = ImageDraw.Draw(img)
        top = self.identity.bg_gradient_top
        bot = self.identity.bg_gradient_bottom
        for y in range(HEIGHT):
            ratio = y / HEIGHT
            r = int(top[0] + (bot[0] - top[0]) * ratio)
            g = int(top[1] + (bot[1] - top[1]) * ratio)
            b = int(top[2] + (bot[2] - top[2]) * ratio)
            draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))
        return img

    def _draw_text_wrapped(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.FreeTypeFont,
        x: int,
        y: int,
        max_width: int,
        fill: tuple[int, int, int],
        line_spacing: int = 12,
    ) -> int:
        words = text.split()
        lines: list[str] = []
        current_line = ""
        for word in words:
            test_line = f"{current_line} {word}".strip()
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)

        total_height = 0
        for line in lines:
            draw.text((x, y + total_height), line, font=font, fill=fill)
            bbox = draw.textbbox((0, 0), line, font=font)
            line_height = bbox[3] - bbox[1]
            total_height += line_height + line_spacing
        return total_height

    def generate(
        self,
        hook_text: str,
        output_path: Path,
        category: str = "news",
    ) -> Path:
        """Generate a thumbnail image for the Reel.

        Args:
            hook_text: The hook/headline text for the cover
            output_path: Where to save the PNG
            category: Content category for style variation

        Returns:
            Path to generated thumbnail
        """
        img = self._create_gradient_bg()
        draw = ImageDraw.Draw(img)

        # Top accent bar
        draw.rectangle([(0, 0), (WIDTH, 8)], fill=self.identity.primary_color)

        # Logo
        logo_font = self._get_font(32, bold=True)
        draw.text(
            (WIDTH // 2, 40),
            self.identity.logo_text,
            font=logo_font,
            fill=self.identity.primary_color,
            anchor="mt",
        )

        # Category badge
        badge_font = self._get_font(24, bold=True)
        badge_text = category.upper()
        badge_bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
        badge_w = badge_bbox[2] - badge_bbox[0] + 30
        badge_h = badge_bbox[3] - badge_bbox[1] + 16
        badge_x = (WIDTH - badge_w) // 2
        badge_y = 100
        draw.rounded_rectangle(
            [(badge_x, badge_y), (badge_x + badge_w, badge_y + badge_h)],
            radius=8,
            fill=self.identity.accent_color,
        )
        draw.text(
            (WIDTH // 2, badge_y + badge_h // 2),
            badge_text,
            font=badge_font,
            fill=(0, 0, 0),
            anchor="mm",
        )

        # Main hook text — large and centered
        hook_font = self._get_font(68, bold=True)
        self._draw_text_wrapped(
            draw,
            hook_text.upper(),
            hook_font,
            80,
            HEIGHT // 2 - 150,
            WIDTH - 160,
            fill=self.identity.text_color,
            line_spacing=16,
        )

        # Bottom decorative line
        draw.rectangle(
            [(WIDTH // 4, HEIGHT - 120), (3 * WIDTH // 4, HEIGHT - 116)],
            fill=self.identity.primary_color,
        )

        # Play icon hint (triangle)
        cx, cy = WIDTH // 2, HEIGHT - 60
        triangle = [(cx - 15, cy - 10), (cx - 15, cy + 10), (cx + 15, cy)]
        draw.polygon(triangle, fill=self.identity.text_color)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path, "PNG")
        logger.info("Thumbnail generated: %s", output_path)
        return output_path