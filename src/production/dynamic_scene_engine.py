"""Dynamic Scene Engine for Vice City Radar.

Generates animated frames with neon aesthetics, Ken Burns effects,
text animations, glow pulses, and smooth transitions. Replaces the
static SceneComposer with a motion-capable renderer that produces
visually dynamic Reels without external video assets.

Visual direction: synthwave/tropical cyberpunk inspired by Vice City
atmosphere — neon gradients, urban glow, sunset palettes. All original.
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from src.production.visual_identity import (
    VICE_CITY_IDENTITY,
    VisualIdentity,
    ColorPalette,
    get_gradient_colors,
    blend_color,
)

logger = logging.getLogger(__name__)

WIDTH = 1080
HEIGHT = 1920


@dataclass(frozen=True)
class DynamicSceneSpec:
    """Specification for an animated scene with motion parameters."""
    scene_type: str  # hook, context, development, cta, title_card, info_card, transition
    text: str
    duration_seconds: float
    subtitle_text: str = ""
    category: str = "news"
    # Motion parameters
    zoom_start: float = 1.0
    zoom_end: float = 1.0
    pan_x_start: int = 0
    pan_x_end: int = 0
    pan_y_start: int = 0
    pan_y_end: int = 0
    # Visual style
    accent_color: tuple[int, int, int] = (255, 45, 120)
    bg_style: str = "gradient"  # gradient, radial, split, neon_grid
    text_animation: str = "fade_in"  # fade_in, slide_up, typewriter, scale_in
    glow_intensity: float = 0.6


class DynamicSceneEngine:
    """Render animated frames with Vice City neon aesthetics."""

    def __init__(self, identity: Optional[VisualIdentity] = None) -> None:
        self.identity = identity or VICE_CITY_IDENTITY
        self._font_cache: dict[str, ImageFont.FreeTypeFont] = {}

    def _get_font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        key = f"{'bold' if bold else 'regular'}_{size}"
        if key not in self._font_cache:
            path = self.identity.typography.font_bold if bold else self.identity.typography.font_regular
            try:
                self._font_cache[key] = ImageFont.truetype(path, size)
            except (OSError, IOError):
                self._font_cache[key] = ImageFont.load_default()
        return self._font_cache[key]

    def _create_neon_gradient_bg(self, frame_idx: int, total_frames: int) -> Image.Image:
        """Create animated gradient background with subtle color shift."""
        img = Image.new("RGB", (WIDTH, HEIGHT))
        draw = ImageDraw.Draw(img)
        p = self.identity.palette

        # Animate gradient colors over time
        progress = frame_idx / max(total_frames - 1, 1)
        pulse = math.sin(progress * math.pi * 2) * 0.15

        top_r = int(p.bg_deep[0] + (p.neon_purple[0] - p.bg_deep[0]) * pulse * 0.3)
        top_g = int(p.bg_deep[1] + (p.neon_purple[1] - p.bg_deep[1]) * pulse * 0.3)
        top_b = int(p.bg_deep[2] + (p.neon_purple[2] - p.bg_deep[2]) * pulse * 0.3)

        bot_r = int(p.bg_mid[0] + (p.neon_cyan[0] - p.bg_mid[0]) * pulse * 0.2)
        bot_g = int(p.bg_mid[1] + (p.neon_cyan[1] - p.bg_mid[1]) * pulse * 0.2)
        bot_b = int(p.bg_mid[2] + (p.neon_cyan[2] - p.bg_mid[2]) * pulse * 0.2)

        top = (max(0, min(255, top_r)), max(0, min(255, top_g)), max(0, min(255, top_b)))
        bot = (max(0, min(255, bot_r)), max(0, min(255, bot_g)), max(0, min(255, bot_b)))

        for y in range(HEIGHT):
            color = get_gradient_colors(y, HEIGHT, top, bot)
            draw.line([(0, y), (WIDTH, y)], fill=color)

        return img

    def _draw_neon_grid_overlay(self, img: Image.Image, frame_idx: int, total_frames: int) -> None:
        """Draw subtle perspective grid lines for depth effect."""
        draw = ImageDraw.Draw(img, "RGBA")
        p = self.identity.palette
        progress = frame_idx / max(total_frames - 1, 1)

        # Horizontal scan line moving down
        scan_y = int((progress * HEIGHT * 1.5) % HEIGHT)
        for dy in range(-2, 3):
            alpha = max(0, 30 - abs(dy) * 10)
            draw.line([(0, scan_y + dy), (WIDTH, scan_y + dy)],
                      fill=(*p.neon_cyan, alpha), width=1)

        # Vertical perspective lines converging at vanishing point
        vx, vy = WIDTH // 2, HEIGHT // 3
        grid_alpha = 15
        for i in range(-8, 9):
            x_bottom = vx + i * 120
            draw.line([(vx, vy), (x_bottom, HEIGHT)],
                      fill=(*p.neon_purple, grid_alpha), width=1)

        # Horizontal depth lines
        for i in range(6):
            y = vy + int((HEIGHT - vy) * (i / 6) ** 1.5)
            alpha = max(5, 20 - i * 3)
            draw.line([(0, y), (WIDTH, y)],
                      fill=(*p.neon_pink, alpha), width=1)

    def _draw_logo_bar(self, draw: ImageDraw.ImageDraw, frame_idx: int, total_frames: int) -> None:
        """Draw animated logo bar with neon glow pulse."""
        p = self.identity.palette
        progress = frame_idx / max(total_frames - 1, 1)
        pulse = (math.sin(progress * math.pi * 4) + 1) / 2  # 0..1

        # Top accent bar with glow
        bar_color = blend_color(p.neon_pink, p.neon_orange, pulse)
        draw.rectangle([(0, 0), (WIDTH, 6)], fill=bar_color)

        # Glow line below
        glow_alpha = int(40 + pulse * 40)
        draw.rectangle([(0, 6), (WIDTH, 10)], fill=(*bar_color, glow_alpha))

        # Logo text
        font = self._get_font(self.identity.typography.size_logo, bold=True)
        draw.text(
            (WIDTH // 2, 32),
            self.identity.logo_text,
            font=font,
            fill=bar_color,
            anchor="mt",
        )

        # Tagline
        tag_font = self._get_font(18, bold=False)
        draw.text(
            (WIDTH // 2, 68),
            self.identity.tagline,
            font=tag_font,
            fill=p.text_secondary,
            anchor="mt",
        )

    def _draw_text_with_glow(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.FreeTypeFont,
        x: int,
        y: int,
        max_width: int,
        fill: tuple[int, int, int],
        glow_color: tuple[int, int, int],
        glow_alpha: int = 60,
        line_spacing: int = 14,
    ) -> int:
        """Draw text with neon glow effect behind it."""
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
            # Glow layer (offset slightly)
            draw.text((x + 2, y + total_height + 2), line, font=font,
                      fill=(*glow_color, glow_alpha))
            draw.text((x - 1, y + total_height - 1), line, font=font,
                      fill=(*glow_color, glow_alpha // 2))
            # Main text
            draw.text((x, y + total_height), line, font=font, fill=fill)
            bbox = draw.textbbox((0, 0), line, font=font)
            line_height = bbox[3] - bbox[1]
            total_height += line_height + line_spacing

        return total_height

    def _apply_ken_burns(
        self, img: Image.Image, frame_idx: int, total_frames: int, spec: DynamicSceneSpec
    ) -> Image.Image:
        """Apply Ken Burns zoom/pan effect to the frame."""
        if spec.zoom_start == spec.zoom_end and spec.pan_x_start == spec.pan_x_end:
            return img

        progress = frame_idx / max(total_frames - 1, 1)
        zoom = spec.zoom_start + (spec.zoom_end - spec.zoom_start) * progress
        pan_x = int(spec.pan_x_start + (spec.pan_x_end - spec.pan_x_start) * progress)
        pan_y = int(spec.pan_y_start + (spec.pan_y_end - spec.pan_y_start) * progress)

        if abs(zoom - 1.0) < 0.001 and pan_x == 0 and pan_y == 0:
            return img

        w, h = img.size
        new_w = int(w * zoom)
        new_h = int(h * zoom)

        resized = img.resize((new_w, new_h), Image.LANCZOS)

        # Calculate crop region centered with pan offset
        cx = new_w // 2 + pan_x
        cy = new_h // 2 + pan_y
        left = max(0, cx - w // 2)
        top = max(0, cy - h // 2)
        right = min(new_w, left + w)
        bottom = min(new_h, top + h)

        # Adjust if crop goes out of bounds
        if right - left < w:
            left = max(0, new_w - w)
            right = left + w
        if bottom - top < h:
            top = max(0, new_h - h)
            bottom = top + h

        cropped = resized.crop((left, top, right, bottom))
        return cropped.resize((w, h), Image.LANCZOS)

    def _animate_text_opacity(
        self, frame_idx: int, total_frames: int, animation: str
    ) -> float:
        """Calculate text opacity based on animation type and frame position."""
        progress = frame_idx / max(total_frames - 1, 1)
        fade_frames = self.identity.motion.text_fade_frames
        fade_progress = min(1.0, frame_idx / max(fade_frames, 1))

        if animation == "fade_in":
            return fade_progress
        elif animation == "slide_up":
            return fade_progress
        elif animation == "scale_in":
            return fade_progress
        elif animation == "typewriter":
            return 1.0  # handled differently
        return 1.0

    def _get_text_offset_y(
        self, frame_idx: int, animation: str
    ) -> int:
        """Get vertical offset for slide animations."""
        if animation == "slide_up":
            fade_frames = self.identity.motion.text_fade_frames
            progress = min(1.0, frame_idx / max(fade_frames, 1))
            # Ease out cubic
            eased = 1 - (1 - progress) ** 3
            return int(40 * (1 - eased))
        return 0

    def render_frame(
        self, spec: DynamicSceneSpec, frame_idx: int, total_frames: int
    ) -> Image.Image:
        """Render a single animated frame for the given scene."""
        img = self._create_neon_gradient_bg(frame_idx, total_frames)
        self._draw_neon_grid_overlay(img, frame_idx, total_frames)

        draw = ImageDraw.Draw(img, "RGBA")
        self._draw_logo_bar(draw, frame_idx, total_frames)

        # Text animation
        opacity = self._animate_text_opacity(frame_idx, total_frames, spec.text_animation)
        offset_y = self._get_text_offset_y(frame_idx, spec.text_animation)
        glow_pulse = (math.sin(frame_idx / max(total_frames, 1) * math.pi * 3) + 1) / 2
        glow_alpha = int(30 + glow_pulse * spec.glow_intensity * 50)

        p = self.identity.palette
        accent = spec.accent_color

        if spec.scene_type == "hook":
            self._render_hook(draw, spec, opacity, offset_y, glow_alpha, accent, p)
        elif spec.scene_type == "title_card":
            self._render_title_card(draw, spec, opacity, offset_y, glow_alpha, accent, p)
        elif spec.scene_type == "info_card":
            self._render_info_card(draw, spec, opacity, offset_y, glow_alpha, accent, p)
        elif spec.scene_type == "cta":
            self._render_cta(draw, spec, opacity, offset_y, glow_alpha, accent, p)
        elif spec.scene_type == "transition":
            self._render_transition(img, draw, frame_idx, total_frames, spec, p)
        else:
            self._render_default(draw, spec, opacity, offset_y, glow_alpha, accent, p)

        # Subtitle bar
        if spec.subtitle_text:
            self._draw_subtitle_bar(draw, spec.subtitle_text, p)

        # Apply Ken Burns
        img = self._apply_ken_burns(img, frame_idx, total_frames, spec)

        return img

    def _render_hook(
        self, draw: ImageDraw.ImageDraw, spec: DynamicSceneSpec,
        opacity: float, offset_y: int, glow_alpha: int,
        accent: tuple[int, int, int], p: ColorPalette,
    ) -> None:
        """Hook scene: large neon text with accent stripe and glow."""
        font = self._get_font(self.identity.typography.size_hook, bold=True)

        # Animated accent stripe
        stripe_x = 80
        stripe_h = 200
        stripe_y = HEIGHT // 2 - stripe_h // 2 + offset_y
        draw.rectangle(
            [(stripe_x, stripe_y), (stripe_x + 8, stripe_y + stripe_h)],
            fill=accent,
        )
        # Stripe glow
        draw.rectangle(
            [(stripe_x - 4, stripe_y - 4), (stripe_x + 12, stripe_y + stripe_h + 4)],
            fill=(*accent, glow_alpha),
        )

        # Main text with glow
        text_color = tuple(int(c * opacity) for c in p.text_primary)
        self._draw_text_with_glow(
            draw, spec.text.upper(), font,
            120, HEIGHT // 2 - 120 + offset_y,
            WIDTH - 200, text_color, accent, glow_alpha,
            line_spacing=18,
        )

    def _render_title_card(
        self, draw: ImageDraw.ImageDraw, spec: DynamicSceneSpec,
        opacity: float, offset_y: int, glow_alpha: int,
        accent: tuple[int, int, int], p: ColorPalette,
    ) -> None:
        """Title card: bordered box with neon outline."""
        font = self._get_font(self.identity.typography.size_title, bold=True)
        box_y = HEIGHT // 2 - 180 + offset_y
        box_h = 360

        # Neon border
        draw.rounded_rectangle(
            [(60, box_y), (WIDTH - 60, box_y + box_h)],
            radius=16,
            outline=accent,
            width=3,
        )
        # Border glow
        draw.rounded_rectangle(
            [(56, box_y - 4), (WIDTH - 56, box_y + box_h + 4)],
            radius=18,
            outline=(*accent, glow_alpha),
            width=2,
        )

        # Category badge
        badge_font = self._get_font(self.identity.typography.size_badge, bold=True)
        badge_text = spec.category.upper()
        bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
        bw = bbox[2] - bbox[0] + 30
        bh = bbox[3] - bbox[1] + 14
        bx = (WIDTH - bw) // 2
        by = box_y - bh // 2
        draw.rounded_rectangle(
            [(bx, by), (bx + bw, by + bh)],
            radius=8,
            fill=accent,
        )
        draw.text((WIDTH // 2, by + bh // 2), badge_text, font=badge_font,
                  fill=(0, 0, 0), anchor="mm")

        # Text
        text_color = tuple(int(c * opacity) for c in p.text_primary)
        self._draw_text_with_glow(
            draw, spec.text, font,
            100, box_y + 50 + offset_y,
            WIDTH - 200, text_color, accent, glow_alpha,
        )

    def _render_info_card(
        self, draw: ImageDraw.ImageDraw, spec: DynamicSceneSpec,
        opacity: float, offset_y: int, glow_alpha: int,
        accent: tuple[int, int, int], p: ColorPalette,
    ) -> None:
        """Info card: structured content with accent line and body text."""
        font = self._get_font(self.identity.typography.size_body, bold=False)
        y_start = 220 + offset_y

        # Accent line
        draw.rectangle(
            [(60, y_start), (WIDTH - 60, y_start + 4)],
            fill=accent,
        )
        draw.rectangle(
            [(60, y_start - 2), (WIDTH - 60, y_start + 6)],
            fill=(*accent, glow_alpha),
        )

        # Body text
        text_color = tuple(int(c * opacity) for c in p.text_primary)
        self._draw_text_with_glow(
            draw, spec.text, font,
            80, y_start + 30,
            WIDTH - 160, text_color, accent, glow_alpha // 2,
            line_spacing=18,
        )

    def _render_cta(
        self, draw: ImageDraw.ImageDraw, spec: DynamicSceneSpec,
        opacity: float, offset_y: int, glow_alpha: int,
        accent: tuple[int, int, int], p: ColorPalette,
    ) -> None:
        """CTA scene: neon button with pulsing glow."""
        font = self._get_font(self.identity.typography.size_cta, bold=True)
        box_h = 160
        box_y = HEIGHT // 2 - box_h // 2 + offset_y

        # Pulsing button background
        pulse = (math.sin(opacity * math.pi * 2) + 1) / 2 if opacity > 0 else 0
        btn_color = blend_color(accent, p.neon_orange, pulse * 0.3)

        draw.rounded_rectangle(
            [(100, box_y), (WIDTH - 100, box_y + box_h)],
            radius=24,
            fill=btn_color,
        )
        # Button glow
        draw.rounded_rectangle(
            [(94, box_y - 6), (WIDTH - 94, box_y + box_h + 6)],
            radius=28,
            outline=(*btn_color, glow_alpha),
            width=3,
        )

        # CTA text (dark on bright button)
        self._draw_text_with_glow(
            draw, spec.text, font,
            140, box_y + 35,
            WIDTH - 280, (0, 0, 0), btn_color, glow_alpha // 3,
        )

    def _render_transition(
        self, img: Image.Image, draw: ImageDraw.ImageDraw,
        frame_idx: int, total_frames: int,
        spec: DynamicSceneSpec, p: ColorPalette,
    ) -> None:
        """Transition scene: neon wipe/fade effect."""
        progress = frame_idx / max(total_frames - 1, 1)

        # Diagonal neon wipe
        wipe_x = int(WIDTH * progress * 1.5 - WIDTH * 0.25)
        wipe_width = 60

        for dx in range(-wipe_width, wipe_width + 1):
            alpha = int(80 * (1 - abs(dx) / wipe_width))
            x = wipe_x + dx
            if 0 <= x < WIDTH:
                draw.line([(x, 0), (x, HEIGHT)],
                          fill=(*spec.accent_color, max(0, alpha)), width=1)

    def _render_default(
        self, draw: ImageDraw.ImageDraw, spec: DynamicSceneSpec,
        opacity: float, offset_y: int, glow_alpha: int,
        accent: tuple[int, int, int], p: ColorPalette,
    ) -> None:
        """Default scene: clean text on neon gradient."""
        font = self._get_font(self.identity.typography.size_body, bold=False)
        text_color = tuple(int(c * opacity) for c in p.text_primary)
        self._draw_text_with_glow(
            draw, spec.text, font,
            80, HEIGHT // 3 + offset_y,
            WIDTH - 160, text_color, accent, glow_alpha // 2,
            line_spacing=16,
        )

    def _draw_subtitle_bar(
        self, draw: ImageDraw.ImageDraw, text: str, p: ColorPalette,
    ) -> None:
        """Draw subtitle with semi-transparent background at safe area."""
        font = self._get_font(self.identity.typography.size_subtitle, bold=True)

        # Background bar
        draw.rounded_rectangle(
            [(40, HEIGHT - 220), (WIDTH - 40, HEIGHT - 80)],
            radius=12,
            fill=p.subtitle_bg,
        )

        # Subtitle text
        self._draw_text_with_glow(
            draw, text, font,
            70, HEIGHT - 200,
            WIDTH - 140, p.text_primary, p.neon_cyan, 30,
            line_spacing=10,
        )

    async def render_sequence(
        self, specs: list[DynamicSceneSpec], output_dir: Path
    ) -> list[Path]:
        """Generate all animated frames for a scene sequence."""
        output_dir.mkdir(parents=True, exist_ok=True)
        fps = self.identity.motion.fps
        frame_paths: list[Path] = []
        frame_idx = 0

        for i, spec in enumerate(specs):
            num_frames = max(1, int(spec.duration_seconds * fps))
            logger.debug(
                "Rendering scene %d/%d (%s): %d frames (%.1fs)",
                i + 1, len(specs), spec.scene_type, num_frames, spec.duration_seconds,
            )

            for f in range(num_frames):
                img = self.render_frame(spec, f, num_frames)
                frame_path = output_dir / f"frame_{frame_idx:05d}.png"
                img.save(frame_path, "PNG")
                frame_paths.append(frame_path)
                frame_idx += 1

        logger.info(
            "Rendered %d frames (%.1fs) in %s",
            len(frame_paths), len(frame_paths) / fps, output_dir,
        )
        return frame_paths