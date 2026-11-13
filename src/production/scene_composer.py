"""Scene composer for JHC Viral Engine.

Generates visual frames using Pillow when FFmpeg drawtext is unavailable.
Creates scene cards with identity, typography, and transitions for Reels.
Replaces static placeholder backgrounds with dynamic visual sequences.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

WIDTH = 1080
HEIGHT = 1920
FPS = 30


@dataclass(frozen=True)
class SceneSpec:
    """Specification for a single visual scene."""
    scene_type: str  # hook, context, development, cta, title_card, info_card
    text: str
    duration_seconds: float
    style: str = "default"  # default, highlight, dark, accent
    subtitle_text: str = ""


@dataclass(frozen=True)
class VisualIdentity:
    """Profile visual identity for consistent branding."""
    primary_color: tuple[int, int, int] = (255, 107, 53)      # GTA orange
    secondary_color: tuple[int, int, int] = (18, 18, 42)      # Dark navy
    accent_color: tuple[int, int, int] = (0, 200, 150)        # Teal accent
    text_color: tuple[int, int, int] = (255, 255, 255)
    bg_gradient_top: tuple[int, int, int] = (10, 10, 26)
    bg_gradient_bottom: tuple[int, int, int] = (26, 26, 58)
    font_bold: str = "/System/Library/Fonts/Helvetica.ttc"
    font_regular: str = "/System/Library/Fonts/Helvetica.ttc"
    logo_text: str = "VICE CITY RADAR"


# Default GTA 6 identity
GTA6_IDENTITY = VisualIdentity()


class SceneComposer:
    """Compose visual scenes for Reels using Pillow."""

    def __init__(self, identity: Optional[VisualIdentity] = None) -> None:
        self.identity = identity or GTA6_IDENTITY
        self._font_cache: dict[str, ImageFont.FreeTypeFont] = {}

    def _get_font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        """Load and cache fonts."""
        key = f"{'bold' if bold else 'regular'}_{size}"
        if key not in self._font_cache:
            path = self.identity.font_bold if bold else self.identity.font_regular
            try:
                self._font_cache[key] = ImageFont.truetype(path, size)
            except (OSError, IOError):
                logger.warning("Font %s not found, using default", path)
                self._font_cache[key] = ImageFont.load_default()
        return self._font_cache[key]

    def _create_gradient_bg(self) -> Image.Image:
        """Create vertical gradient background."""
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
        """Draw text with word wrapping. Returns total height used."""
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

    def _draw_logo_bar(self, draw: ImageDraw.ImageDraw) -> None:
        """Draw profile logo bar at top."""
        # Accent bar
        draw.rectangle([(0, 0), (WIDTH, 6)], fill=self.identity.primary_color)
        # Logo text
        font = self._get_font(28, bold=True)
        draw.text(
            (WIDTH // 2, 30),
            self.identity.logo_text,
            font=font,
            fill=self.identity.primary_color,
            anchor="mt",
        )

    def _draw_subtitle_bar(
        self, draw: ImageDraw.ImageDraw, text: str
    ) -> None:
        """Draw subtitle text at bottom safe area."""
        if not text:
            return
        font = self._get_font(36, bold=True)
        # Background bar for readability
        draw.rectangle(
            [(40, HEIGHT - 200), (WIDTH - 40, HEIGHT - 80)],
            fill=(0, 0, 0, 180),
        )
        self._draw_text_wrapped(
            draw, text, font, 60, HEIGHT - 190, WIDTH - 120,
            fill=self.identity.text_color,
        )

    def compose_scene(self, spec: SceneSpec) -> Image.Image:
        """Generate a single scene frame."""
        img = self._create_gradient_bg()
        draw = ImageDraw.Draw(img)

        self._draw_logo_bar(draw)

        if spec.scene_type == "hook":
            self._compose_hook(draw, spec)
        elif spec.scene_type == "title_card":
            self._compose_title_card(draw, spec)
        elif spec.scene_type == "info_card":
            self._compose_info_card(draw, spec)
        elif spec.scene_type == "cta":
            self._compose_cta(draw, spec)
        else:
            self._compose_default(draw, spec)

        if spec.subtitle_text:
            self._draw_subtitle_bar(draw, spec.subtitle_text)

        return img

    def _compose_hook(self, draw: ImageDraw.ImageDraw, spec: SceneSpec) -> None:
        """Hook scene: large bold text, high contrast."""
        font = self._get_font(72, bold=True)
        # Accent stripe
        draw.rectangle(
            [(80, HEIGHT // 2 - 120), (88, HEIGHT // 2 + 120)],
            fill=self.identity.primary_color,
        )
        self._draw_text_wrapped(
            draw, spec.text, font, 120, HEIGHT // 2 - 100,
            WIDTH - 200, fill=self.identity.text_color,
        )

    def _compose_title_card(
        self, draw: ImageDraw.ImageDraw, spec: SceneSpec
    ) -> None:
        """Title card: centered, large text with accent."""
        font = self._get_font(64, bold=True)
        # Centered box
        box_y = HEIGHT // 2 - 150
        draw.rectangle(
            [(60, box_y), (WIDTH - 60, box_y + 300)],
            outline=self.identity.primary_color,
            width=3,
        )
        self._draw_text_wrapped(
            draw, spec.text, font, 100, box_y + 40,
            WIDTH - 200, fill=self.identity.text_color,
        )

    def _compose_info_card(
        self, draw: ImageDraw.ImageDraw, spec: SceneSpec
    ) -> None:
        """Info card: structured content with bullet points."""
        font = self._get_font(40, bold=False)
        y_start = 200
        # Section indicator
        draw.rectangle(
            [(60, y_start), (WIDTH - 60, y_start + 4)],
            fill=self.identity.accent_color,
        )
        self._draw_text_wrapped(
            draw, spec.text, font, 80, y_start + 30,
            WIDTH - 160, fill=self.identity.text_color,
            line_spacing=16,
        )

    def _compose_cta(self, draw: ImageDraw.ImageDraw, spec: SceneSpec) -> None:
        """CTA scene: call to action with accent color."""
        font = self._get_font(52, bold=True)
        # CTA box
        box_h = 200
        box_y = HEIGHT // 2 - box_h // 2
        draw.rounded_rectangle(
            [(100, box_y), (WIDTH - 100, box_y + box_h)],
            radius=20,
            fill=self.identity.primary_color,
        )
        # Text centered in box
        self._draw_text_wrapped(
            draw, spec.text, font, 140, box_y + 40,
            WIDTH - 280, fill=(0, 0, 0),
        )

    def _compose_default(
        self, draw: ImageDraw.ImageDraw, spec: SceneSpec
    ) -> None:
        """Default scene: clean text on gradient."""
        font = self._get_font(44, bold=False)
        self._draw_text_wrapped(
            draw, spec.text, font, 80, HEIGHT // 3,
            WIDTH - 160, fill=self.identity.text_color,
            line_spacing=14,
        )

    async def compose_sequence(
        self, specs: list[SceneSpec], output_dir: Path
    ) -> list[Path]:
        """Generate all scene frames for a sequence.

        Returns list of paths to generated PNG frames.
        Each scene generates duration_seconds * FPS frames.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        frame_paths: list[Path] = []
        frame_idx = 0

        for i, spec in enumerate(specs):
            scene_img = self.compose_scene(spec)
            num_frames = max(1, int(spec.duration_seconds * FPS))

            for _ in range(num_frames):
                frame_path = output_dir / f"frame_{frame_idx:05d}.png"
                scene_img.save(frame_path, "PNG")
                frame_paths.append(frame_path)
                frame_idx += 1

            logger.debug(
                "Scene %d/%d (%s): %d frames",
                i + 1, len(specs), spec.scene_type, num_frames,
            )

        logger.info(
            "Composed %d frames (%.1fs) in %s",
            len(frame_paths), len(frame_paths) / FPS, output_dir,
        )
        return frame_paths

    @staticmethod
    async def frames_to_video(
        frame_paths: list[Path],
        output_path: Path,
        audio_path: Optional[Path] = None,
    ) -> Path:
        """Concatenate frames into MP4 using FFmpeg."""
        import asyncio
        import shutil

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("FFmpeg not found")

        # Create concat file with duration per frame for proper timing
        frame_duration = 1.0 / FPS
        concat_file = output_path.parent / "concat.txt"
        with open(concat_file, "w") as f:
            for fp in frame_paths:
                f.write(f"file '{fp.resolve()}'\n")
                f.write(f"duration {frame_duration:.6f}\n")
            # Last frame needs to be repeated for concat demuxer
            if frame_paths:
                f.write(f"file '{frame_paths[-1].resolve()}'\n")

        cmd = [
            ffmpeg, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
        ]

        if audio_path and audio_path.exists():
            cmd.extend(["-i", str(audio_path)])
            cmd.extend([
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "128k",
                "-ar", "48000",
                "-shortest",
                "-movflags", "+faststart",
            ])
        else:
            cmd.extend([
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "28",
                "-pix_fmt", "yuv420p",
                "-t", str(len(frame_paths) / FPS),
                "-movflags", "+faststart",
            ])

        cmd.append(str(output_path))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg concat failed: {stderr.decode()[-500:]}")

        # Cleanup
        concat_file.unlink(missing_ok=True)
        for fp in frame_paths:
            fp.unlink(missing_ok=True)

        logger.info("Rendered video: %s", output_path)
        return output_path