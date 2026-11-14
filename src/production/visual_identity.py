"""Vice City Radar visual identity system.

Defines the audiovisual brand identity inspired by GTA Vice City aesthetics:
neon gradients, tropical cyberpunk, urban glow. All colors are original —
no copyrighted assets. Creates a distinctive, recognizable brand without
relying on official Rockstar materials.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ColorPalette:
    """Brand color palette for consistent visual identity."""
    # Primary neon accents
    neon_pink: tuple[int, int, int] = (255, 45, 120)       # Hot pink neon
    neon_cyan: tuple[int, int, int] = (0, 220, 255)        # Electric cyan
    neon_orange: tuple[int, int, int] = (255, 140, 50)     # Sunset orange
    neon_purple: tuple[int, int, int] = (180, 60, 255)     # Ultraviolet

    # Background gradients (dark to mid)
    bg_deep: tuple[int, int, int] = (8, 6, 20)             # Near-black purple
    bg_mid: tuple[int, int, int] = (20, 15, 45)            # Dark indigo
    bg_accent: tuple[int, int, int] = (35, 20, 60)         # Purple tint

    # Text colors
    text_primary: tuple[int, int, int] = (255, 255, 255)   # White
    text_secondary: tuple[int, int, int] = (200, 200, 220) # Light gray
    text_accent: tuple[int, int, int] = (255, 220, 100)    # Warm gold

    # Overlay / UI
    overlay_dark: tuple[int, int, int, int] = (0, 0, 0, 180)
    overlay_neon: tuple[int, int, int, int] = (255, 45, 120, 40)
    subtitle_bg: tuple[int, int, int, int] = (0, 0, 0, 200)


@dataclass(frozen=True)
class Typography:
    """Font configuration for Vice City Radar."""
    font_bold: str = "/System/Library/Fonts/Helvetica.ttc"
    font_regular: str = "/System/Library/Fonts/Helvetica.ttc"

    # Size scale (px at 1080x1920)
    size_logo: int = 36
    size_badge: int = 26
    size_hook: int = 78
    size_title: int = 64
    size_body: int = 44
    size_subtitle: int = 38
    size_caption: int = 28
    size_cta: int = 56


@dataclass(frozen=True)
class MotionConfig:
    """Animation and transition parameters."""
    fps: int = 30
    transition_frames: int = 8          # ~0.27s crossfade
    zoom_rate: float = 0.003            # px per frame for slow zoom
    pan_rate: float = 2.0               # px per frame for horizontal pan
    ken_burns_scale: float = 1.15       # max zoom factor for Ken Burns
    text_fade_frames: int = 6           # text entrance fade
    glow_pulse_period: int = 60         # frames per neon pulse cycle


@dataclass(frozen=True)
class VisualIdentity:
    """Complete visual identity for a profile."""
    name: str = "VICE CITY RADAR"
    tagline: str = "GTA 6 • NOVIDADES • TEORIAS"
    palette: ColorPalette = ColorPalette()
    typography: Typography = Typography()
    motion: MotionConfig = MotionConfig()
    logo_text: str = "VICE CITY RADAR"
    width: int = 1080
    height: int = 1920


# Singleton default identity
VICE_CITY_IDENTITY = VisualIdentity()


def get_gradient_colors(
    y: int,
    height: int,
    top: tuple[int, int, int],
    bottom: tuple[int, int, int],
) -> tuple[int, int, int]:
    """Interpolate gradient color at vertical position y."""
    ratio = y / max(height - 1, 1)
    r = int(top[0] + (bottom[0] - top[0]) * ratio)
    g = int(top[1] + (bottom[1] - top[1]) * ratio)
    b = int(top[2] + (bottom[2] - top[2]) * ratio)
    return (r, g, b)


def blend_color(
    base: tuple[int, int, int],
    overlay: tuple[int, int, int],
    alpha: float,
) -> tuple[int, int, int]:
    """Alpha-blend overlay onto base color."""
    a = max(0.0, min(1.0, alpha))
    r = int(base[0] * (1 - a) + overlay[0] * a)
    g = int(base[1] * (1 - a) + overlay[1] * a)
    b = int(base[2] * (1 - a) + overlay[2] * a)
    return (r, g, b)