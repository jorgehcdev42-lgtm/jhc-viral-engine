"""Watermark / Branding overlay engine for JHC Viral Engine.

Applies per-profile logo overlays to rendered videos using FFmpeg's
overlay filter. Supports configurable position, size, opacity, margins,
and platform-specific safe-area presets. Never modifies original source
files — always produces a new branded export.

Designed for MacBook M2 8GB: sequential processing, no parallel renders.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WatermarkConfig:
    """Immutable watermark configuration for a profile."""
    profile_id: str
    logo_path: str = ""
    position: str = "bottom_right"  # top_left, top_right, bottom_left, bottom_right, center, custom
    custom_x: int = 0
    custom_y: int = 0
    scale_percent: float = 15.0  # Logo width as % of video width
    opacity: float = 0.85
    margin_px: int = 20
    enabled: bool = True
    platform_preset: str = "universal"  # universal, instagram, youtube, tiktok

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> WatermarkConfig:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# Platform-specific safe areas (pixels from edge where UI elements appear)
SAFE_AREAS: dict[str, dict[str, int]] = {
    "universal": {"top": 40, "bottom": 40, "left": 20, "right": 20},
    "instagram": {"top": 60, "bottom": 80, "left": 20, "right": 20},  # Bottom nav + top bar
    "youtube": {"top": 40, "bottom": 60, "left": 20, "right": 20},   # Bottom controls
    "tiktok": {"top": 60, "bottom": 100, "left": 20, "right": 60},  # Right sidebar icons + bottom nav
}

DEFAULT_CONFIGS: dict[str, WatermarkConfig] = {
    "gta6-br": WatermarkConfig(
        profile_id="gta6-br",
        position="bottom_right",
        scale_percent=12.0,
        opacity=0.9,
        margin_px=25,
        platform_preset="universal",
    ),
    "gta6-global": WatermarkConfig(
        profile_id="gta6-global",
        position="bottom_right",
        scale_percent=12.0,
        opacity=0.9,
        margin_px=25,
        platform_preset="universal",
    ),
}


class WatermarkEngine:
    """Apply logo watermarks to videos using FFmpeg overlay filter."""

    CONFIG_FILE = "watermark_configs.json"

    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.branding_dir = data_root / "branding"
        self.logos_dir = self.branding_dir / "logos"
        self.exports_dir = self.branding_dir / "exports"
        self.configs_path = self.branding_dir / self.CONFIG_FILE
        self.branding_dir.mkdir(parents=True, exist_ok=True)
        self.logos_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        self._configs: dict[str, WatermarkConfig] = {}
        self._load_configs()

    def _load_configs(self) -> None:
        if self.configs_path.exists():
            try:
                data = json.loads(self.configs_path.read_text(encoding="utf-8"))
                self._configs = {k: WatermarkConfig.from_dict(v) for k, v in data.items()}
            except (json.JSONDecodeError, KeyError, TypeError):
                logger.warning("Could not load watermark configs; using defaults")
                self._configs = dict(DEFAULT_CONFIGS)
        else:
            self._configs = dict(DEFAULT_CONFIGS)
            self._save_configs()

    def _save_configs(self) -> None:
        data = {k: v.to_dict() for k, v in self._configs.items()}
        self.configs_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def get_config(self, profile_id: str) -> WatermarkConfig:
        if profile_id not in self._configs:
            self._configs[profile_id] = WatermarkConfig(profile_id=profile_id)
            self._save_configs()
        return self._configs[profile_id]

    def update_config(self, config: WatermarkConfig) -> None:
        self._configs[config.profile_id] = config
        self._save_configs()

    def save_logo(self, profile_id: str, source_path: Path) -> Path:
        """Copy a logo file into the branding/logos directory for a profile."""
        ext = source_path.suffix.lower()
        if ext not in (".png", ".svg", ".jpg", ".jpeg", ".webp"):
            raise ValueError(f"Unsupported logo format: {ext}. Use PNG, SVG, JPG, or WebP.")
        dest = self.logos_dir / f"{profile_id}_logo{ext}"
        shutil.copy2(str(source_path), str(dest))
        # Update config with new logo path
        current = self.get_config(profile_id)
        updated = WatermarkConfig(
            profile_id=profile_id,
            logo_path=str(dest),
            position=current.position,
            custom_x=current.custom_x,
            custom_y=current.custom_y,
            scale_percent=current.scale_percent,
            opacity=current.opacity,
            margin_px=current.margin_px,
            enabled=True,
            platform_preset=current.platform_preset,
        )
        self.update_config(updated)
        logger.info("Logo saved for %s: %s", profile_id, dest)
        return dest

    def _build_overlay_expr(self, config: WatermarkConfig, video_width: int, video_height: int) -> str:
        """Build the FFmpeg overlay filter expression with safe-area awareness."""
        safe = SAFE_AREAS.get(config.platform_preset, SAFE_AREAS["universal"])
        logo_w = int(video_width * config.scale_percent / 100.0)
        margin = config.margin_px

        if config.position == "top_left":
            x = max(margin, safe["left"])
            y = max(margin, safe["top"])
        elif config.position == "top_right":
            x = f"W-w-{max(margin, safe['right'])}"
            y = max(margin, safe["top"])
        elif config.position == "bottom_left":
            x = max(margin, safe["left"])
            y = f"H-h-{max(margin, safe['bottom'])}"
        elif config.position == "bottom_right":
            x = f"W-w-{max(margin, safe['right'])}"
            y = f"H-h-{max(margin, safe['bottom'])}"
        elif config.position == "center":
            x = "(W-w)/2"
            y = "(H-h)/2"
        elif config.position == "custom":
            x = str(config.custom_x)
            y = str(config.custom_y)
        else:
            x = f"W-w-{margin}"
            y = f"H-h-{margin}"

        return f"overlay={x}:{y}:format=auto"

    async def apply_watermark(
        self,
        input_path: Path,
        output_path: Path,
        profile_id: str,
        force: bool = False,
    ) -> dict:
        """Apply watermark to a video file. Returns result metadata.

        Args:
            input_path: Source video (never modified)
            output_path: Destination for branded video
            profile_id: Profile whose watermark config to use
            force: Re-render even if output already exists
        """
        config = self.get_config(profile_id)
        result = {
            "input": str(input_path),
            "output": str(output_path),
            "profile_id": profile_id,
            "success": False,
            "error": None,
            "duration_seconds": 0.0,
        }

        if not config.enabled:
            result["error"] = "Watermark disabled for this profile"
            return result

        if not config.logo_path or not Path(config.logo_path).exists():
            result["error"] = f"No logo configured for {profile_id}"
            return result

        if not input_path.exists():
            result["error"] = f"Input file not found: {input_path}"
            return result

        if output_path.exists() and not force:
            result["success"] = True
            result["skipped"] = True
            return result

        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            result["error"] = "FFmpeg/ffprobe not found in PATH"
            return result

        # Get video dimensions via ffprobe
        probe_cmd = [
            ffprobe, "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,duration",
            "-of", "json", str(input_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *probe_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        try:
            probe_data = json.loads(stdout.decode())
            stream = probe_data.get("streams", [{}])[0]
            vw = int(stream.get("width", 1080))
            vh = int(stream.get("height", 1920))
            dur = float(stream.get("duration", 0) or probe_data.get("format", {}).get("duration", 0))
        except (json.JSONDecodeError, KeyError, IndexError, ValueError):
            vw, vh, dur = 1080, 1920, 0.0

        result["duration_seconds"] = dur

        # Build FFmpeg command
        overlay_expr = self._build_overlay_expr(config, vw, vh)
        scale_filter = f"scale={int(vw * config.scale_percent / 100)}:-1"
        opacity_filter = f"format=rgba,colorchannelmixer=aa={config.opacity}"

        cmd = [
            ffmpeg, "-y",
            "-i", str(input_path),
            "-i", config.logo_path,
            "-filter_complex",
            f"[1:v]{scale_filter},{opacity_filter}[logo];[0:v][logo]{overlay_expr}[out]",
            "-map", "[out]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(output_path),
        ]

        output_path.parent.mkdir(parents=True, exist_ok=True)
        start = time.time()
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        elapsed = time.time() - start

        if proc.returncode != 0:
            err_msg = stderr.decode()[-500:] if stderr else "Unknown FFmpeg error"
            result["error"] = f"FFmpeg failed (exit {proc.returncode}): {err_msg}"
            logger.error("Watermark failed for %s: %s", input_path.name, result["error"])
            return result

        result["success"] = True
        result["render_time_seconds"] = round(elapsed, 2)
        logger.info(
            "Watermark applied: %s → %s (%.1fs)",
            input_path.name, output_path.name, elapsed,
        )
        return result

    async def apply_batch(
        self,
        input_paths: list[Path],
        profile_id: str,
        output_dir: Optional[Path] = None,
    ) -> list[dict]:
        """Apply watermark to multiple videos sequentially."""
        out_dir = output_dir or (self.exports_dir / profile_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        results = []
        for i, inp in enumerate(input_paths):
            out_path = out_dir / f"{inp.stem}_branded{inp.suffix}"
            logger.info("Batch watermark %d/%d: %s", i + 1, len(input_paths), inp.name)
            r = await self.apply_watermark(inp, out_path, profile_id)
            results.append(r)
        ok = sum(1 for r in results if r["success"])
        logger.info("Batch complete: %d/%d successful", ok, len(results))
        return results

    def get_all_configs(self) -> dict[str, dict]:
        return {k: v.to_dict() for k, v in self._configs.items()}

    def preview_position(self, profile_id: str, video_width: int = 1080, video_height: int = 1920) -> dict:
        """Return computed overlay coordinates for preview without rendering."""
        config = self.get_config(profile_id)
        safe = SAFE_AREAS.get(config.platform_preset, SAFE_AREAS["universal"])
        logo_w = int(video_width * config.scale_percent / 100.0)
        margin = config.margin_px

        positions = {
            "top_left": (max(margin, safe["left"]), max(margin, safe["top"])),
            "top_right": (video_width - logo_w - max(margin, safe["right"]), max(margin, safe["top"])),
            "bottom_left": (max(margin, safe["left"]), video_height - int(logo_w * 1.5) - max(margin, safe["bottom"])),
            "bottom_right": (video_width - logo_w - max(margin, safe["right"]), video_height - int(logo_w * 1.5) - max(margin, safe["bottom"])),
            "center": ((video_width - logo_w) // 2, (video_height - int(logo_w * 1.5)) // 2),
        }
        pos = positions.get(config.position, positions["bottom_right"])
        return {
            "profile_id": profile_id,
            "position": config.position,
            "logo_width_px": logo_w,
            "x": pos[0],
            "y": pos[1],
            "opacity": config.opacity,
            "safe_area": safe,
            "platform_preset": config.platform_preset,
        }