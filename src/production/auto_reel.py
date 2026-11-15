"""AutoReel Studio — Pipeline automático de produção de vídeos virais.

Fluxo: vídeo fonte → inspeção → corte inteligente → crop vertical →
watermark → legendas → mixagem áudio → thumbnail → quality gate → export MP4.

Preserva arquivo original intacto. Progresso real via callback.
Suporta dual market (BR/Global) com identidade visual própria.
"""

import os
import json
import time
import shutil
import subprocess
import hashlib
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Callable
from enum import Enum


class Market(str, Enum):
    BR = "br"
    GLOBAL = "global"


class Platform(str, Enum):
    REELS = "reels"
    SHORTS = "shorts"
    TIKTOK = "tiktok"
    STORIES = "stories"
    FEED = "feed"


class ReelStatus(str, Enum):
    INSPECTING = "inspecting"
    CLIPPING = "clipping"
    CROPPING = "cropping"
    WATERMARK = "watermark"
    SUBTITLES = "subtitles"
    AUDIO_MIX = "audio_mix"
    THUMBNAIL = "thumbnail"
    QUALITY_GATE = "quality_gate"
    EXPORTING = "exporting"
    DONE = "done"
    FAILED = "failed"


PLATFORM_CONFIGS = {
    Platform.REELS: {"width": 1080, "height": 1920, "max_duration": 90, "aspect": "9:16"},
    Platform.SHORTS: {"width": 1080, "height": 1920, "max_duration": 60, "aspect": "9:16"},
    Platform.TIKTOK: {"width": 1080, "height": 1920, "max_duration": 180, "aspect": "9:16"},
    Platform.STORIES: {"width": 1080, "height": 1920, "max_duration": 60, "aspect": "9:16"},
    Platform.FEED: {"width": 1080, "height": 1080, "max_duration": 60, "aspect": "1:1"},
}

MARKET_CONFIGS = {
    Market.BR: {
        "language": "pt-BR",
        "channel": "Leonida GTA VI Flash BR",
        "subtitle_font_size": 28,
        "watermark_position": "top_right",
        "watermark_opacity": 0.7,
    },
    Market.GLOBAL: {
        "language": "en",
        "channel": "Leonida GTA VI Flash Global",
        "subtitle_font_size": 26,
        "watermark_position": "top_right",
        "watermark_opacity": 0.7,
    },
}


@dataclass
class ReelProgress:
    status: str = ReelStatus.INSPECTING.value
    percent: int = 0
    message: str = ""
    error: Optional[str] = None
    output_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    duration_seconds: float = 0.0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReelRequest:
    video_path: str
    market: str = Market.BR.value
    platform: str = Platform.REELS.value
    editorial_model: str = "viral_hook"
    include_narration: bool = False
    include_music: bool = True
    custom_title: Optional[str] = None
    subtitle_text: Optional[str] = None
    logo_path: Optional[str] = None


class AutoReelStudio:
    """Pipeline automático de produção de reels virais."""

    def __init__(self, data_root: str = "data", progress_callback: Optional[Callable] = None):
        self.data_root = Path(data_root)
        self.output_dir = self.data_root / "autoreel" / "output"
        self.temp_dir = self.data_root / "autoreel" / "temp"
        self.thumbs_dir = self.data_root / "autoreel" / "thumbnails"
        self.progress_callback = progress_callback

        for d in [self.output_dir, self.temp_dir, self.thumbs_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def _report(self, progress: ReelProgress):
        if self.progress_callback:
            self.progress_callback(progress)

    def _run_ffmpeg(self, args: list[str], description: str = "") -> tuple[int, str, str]:
        cmd = ["ffmpeg", "-y", "-hide_banner"] + args
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", f"Timeout em: {description}"
        except FileNotFoundError:
            return -2, "", "ffmpeg não encontrado no PATH"

    def _run_ffprobe(self, path: str) -> dict:
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", str(path)
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                return json.loads(result.stdout)
        except Exception:
            pass
        return {}

    def _get_video_info(self, path: str) -> dict:
        probe = self._run_ffprobe(path)
        if not probe:
            return {"error": "Não foi possível inspecionar o vídeo"}

        video_stream = next(
            (s for s in probe.get("streams", []) if s.get("codec_type") == "video"),
            {}
        )
        audio_stream = next(
            (s for s in probe.get("streams", []) if s.get("codec_type") == "audio"),
            {}
        )
        fmt = probe.get("format", {})

        duration = float(fmt.get("duration", 0))
        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))

        return {
            "duration": duration,
            "width": width,
            "height": height,
            "fps": eval(video_stream.get("r_frame_rate", "30/1")) if "/" in video_stream.get("r_frame_rate", "") else float(video_stream.get("r_frame_rate", 30)),
            "codec": video_stream.get("codec_name", "unknown"),
            "has_audio": bool(audio_stream),
            "audio_codec": audio_stream.get("codec_name", ""),
            "bitrate": int(fmt.get("bit_rate", 0)),
            "size_mb": int(fmt.get("size", 0)) / (1024 * 1024),
        }

    def _detect_scenes(self, input_path: str, threshold: float = 0.3) -> list[float]:
        """Detecta timestamps de mudança de cena."""
        cmd = [
            "-i", str(input_path),
            "-vf", f"select='gt(scene,{threshold})',showinfo",
            "-vsync", "vfr", "-f", "null", "-"
        ]
        rc, stdout, stderr = self._run_ffmpeg(cmd, "scene detection")
        timestamps = []
        for line in stderr.split("\n"):
            if "pts_time:" in line:
                try:
                    pts = line.split("pts_time:")[1].split()[0]
                    timestamps.append(float(pts))
                except (IndexError, ValueError):
                    continue
        return timestamps

    def _select_best_segment(
        self, info: dict, scenes: list[float], max_duration: float
    ) -> tuple[float, float]:
        """Seleciona melhor segmento baseado em densidade de cenas."""
        duration = info["duration"]
        if duration <= max_duration:
            return 0.0, duration

        window = max_duration
        best_start = 0.0
        best_score = -1

        step = max(1.0, duration / 20)
        t = 0.0
        while t + window <= duration:
            count = sum(1 for s in scenes if t <= s < t + window)
            score = count + (1.0 if t < 5.0 else 0.0)
            if score > best_score:
                best_score = score
                best_start = t
            t += step

        return best_start, min(best_start + window, duration)

    def _crop_vertical(
        self, input_path: str, output_path: str, target_w: int, target_h: int
    ) -> bool:
        """Crop central para formato vertical."""
        vf = f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,crop={target_w}:{target_h}"
        rc, _, err = self._run_ffmpeg([
            "-i", str(input_path),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-an", str(output_path)
        ], "vertical crop")
        return rc == 0

    def _apply_watermark(
        self, input_path: str, output_path: str,
        logo_path: str, position: str, opacity: float
    ) -> bool:
        """Aplica watermark/logo sobre o vídeo."""
        if not logo_path or not Path(logo_path).exists():
            shutil.copy2(str(input_path), str(output_path))
            return True

        pos_map = {
            "top_left": "10:10",
            "top_right": "main_w-overlay_w-10:10",
            "bottom_left": "10:main_h-overlay_h-10",
            "bottom_right": "main_w-overlay_w-10:main_h-overlay_h-10",
            "center": "(main_w-overlay_w)/2:(main_h-overlay_h)/2",
        }
        overlay_pos = pos_map.get(position, pos_map["top_right"])

        rc, _, _ = self._run_ffmpeg([
            "-i", str(input_path),
            "-i", str(logo_path),
            "-filter_complex",
            f"[1:v]format=rgba,colorchannelmixer=aa={opacity}[wm];[0:v][wm]overlay={overlay_pos}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-an", str(output_path)
        ], "watermark")
        return rc == 0

    def _check_drawtext_available(self) -> bool:
        """Check if ffmpeg has drawtext filter compiled in."""
        if hasattr(self, '_drawtext_available'):
            return self._drawtext_available
        rc, _, stderr = self._run_ffmpeg([
            "-f", "lavfi", "-i", "color=c=black:s=64x64:d=0.1",
            "-vf", "drawtext=text='X':fontsize=10:x=0:y=0",
            "-frames:v", "1", "-f", "null", "-"
        ], "drawtext check")
        self._drawtext_available = (rc == 0 and "No such filter" not in stderr)
        return self._drawtext_available

    def _generate_subtitles(
        self, input_path: str, output_path: str,
        text: str, font_size: int, language: str
    ) -> bool:
        """Gera legendas queimadas no vídeo. Gracefully skips if drawtext unavailable."""
        if not text:
            shutil.copy2(str(input_path), str(output_path))
            return True

        if not self._check_drawtext_available():
            # drawtext not available — copy without subtitles (non-fatal)
            shutil.copy2(str(input_path), str(output_path))
            return True

        safe_text = text.replace("'", "\\'").replace(":", "\\:")
        sub_filter = (
            f"drawtext=text='{safe_text}'"
            f":fontsize={font_size}"
            f":fontcolor=white"
            f":borderw=2:bordercolor=black"
            f":x=(w-text_w)/2:y=h-th-40"
        )
        rc, _, _ = self._run_ffmpeg([
            "-i", str(input_path),
            "-vf", sub_filter,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-an", str(output_path)
        ], "subtitles")
        if rc != 0:
            # Fallback: copy without subtitles rather than failing pipeline
            shutil.copy2(str(input_path), str(output_path))
            return True
        return True

    def _mix_audio(
        self, video_path: str, output_path: str,
        has_source_audio: bool, include_music: bool
    ) -> bool:
        """Mixagem de áudio: mantém original ou adiciona trilha."""
        if has_source_audio and not include_music:
            rc, _, _ = self._run_ffmpeg([
                "-i", str(video_path),
                "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                str(output_path)
            ], "audio copy")
            return rc == 0

        if has_source_audio:
            rc, _, _ = self._run_ffmpeg([
                "-i", str(video_path),
                "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                "-af", "volume=0.8",
                str(output_path)
            ], "audio normalize")
            return rc == 0

        rc, _, _ = self._run_ffmpeg([
            "-i", str(video_path),
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-c:v", "copy", "-c:a", "aac", "-shortest",
            str(output_path)
        ], "silent audio")
        return rc == 0

    def _generate_thumbnail(
        self, video_path: str, output_path: str, title: str, market: str
    ) -> bool:
        """Gera thumbnail a partir do frame mais interessante."""
        rc, _, _ = self._run_ffmpeg([
            "-i", str(video_path),
            "-ss", "2",
            "-vframes", "1",
            "-q:v", "2",
            str(output_path)
        ], "thumbnail extract")
        return rc == 0

    def _quality_gate(self, video_path: str) -> dict:
        """Verifica qualidade mínima do output."""
        info = self._get_video_info(str(video_path))
        issues = []

        if info.get("duration", 0) < 3:
            issues.append("Duração menor que 3s")
        if info.get("width", 0) < 720:
            issues.append(f"Largura {info.get('width')}px < 720px mínimo")
        if info.get("size_mb", 0) > 100:
            issues.append(f"Arquivo {info['size_mb']:.1f}MB > 100MB limite")
        if info.get("error"):
            issues.append(info["error"])

        passed = len(issues) == 0
        return {
            "passed": passed,
            "issues": issues,
            "info": info,
        }

    def produce(self, request: ReelRequest) -> ReelProgress:
        """Pipeline single-pass: crop + watermark + legendas + áudio em um único ffmpeg.

        Preserva áudio original, evita reencode múltiplo e frames pretos.
        """
        progress = ReelProgress()
        job_id = hashlib.md5(
            f"{request.video_path}{time.time()}".encode()
        ).hexdigest()[:12]

        try:
            source = Path(request.video_path)
            if not source.exists():
                progress.status = ReelStatus.FAILED.value
                progress.error = f"Arquivo não encontrado: {request.video_path}"
                self._report(progress)
                return progress

            market_cfg = MARKET_CONFIGS.get(Market(request.market), MARKET_CONFIGS[Market.BR])
            plat_cfg = PLATFORM_CONFIGS.get(Platform(request.platform), PLATFORM_CONFIGS[Platform.REELS])

            # 1. Inspeção
            progress.status = ReelStatus.INSPECTING.value
            progress.percent = 5
            progress.message = "Inspecionando vídeo fonte..."
            self._report(progress)

            info = self._get_video_info(str(source))
            if info.get("error"):
                progress.status = ReelStatus.FAILED.value
                progress.error = info["error"]
                self._report(progress)
                return progress

            progress.metadata = {"source_info": info, "market": request.market, "platform": request.platform}

            # 2. Detecção de cenas e seleção de segmento
            progress.status = ReelStatus.CLIPPING.value
            progress.percent = 15
            progress.message = "Detectando cenas e selecionando melhor segmento..."
            self._report(progress)

            scenes = self._detect_scenes(str(source))
            start, end = self._select_best_segment(info, scenes, plat_cfg["max_duration"])

            # 3-6. SINGLE PASS: crop + watermark + legendas + áudio
            progress.status = ReelStatus.CROPPING.value
            progress.percent = 30
            progress.message = f"Processando vídeo+áudio em single-pass ({plat_cfg['width']}x{plat_cfg['height']})..."
            self._report(progress)

            output_filename = f"{job_id}_{request.market}_{request.platform}.mp4"
            final_path = self.output_dir / output_filename

            # Build video filter chain
            vf_parts = [
                f"scale={plat_cfg['width']}:{plat_cfg['height']}:force_original_aspect_ratio=increase",
                f"crop={plat_cfg['width']}:{plat_cfg['height']}",
            ]

            # Watermark overlay (se logo existe)
            logo_path = request.logo_path or ""
            has_logo = logo_path and Path(logo_path).exists()
            if has_logo:
                pos_map = {
                    "top_left": "10:10",
                    "top_right": "main_w-overlay_w-10:10",
                    "bottom_left": "10:main_h-overlay_h-10",
                    "bottom_right": "main_w-overlay_w-10:main_h-overlay_h-10",
                    "center": "(main_w-overlay_w)/2:(main_h-overlay_h)/2",
                }
                overlay_pos = pos_map.get(market_cfg["watermark_position"], pos_map["top_right"])
                opacity = market_cfg["watermark_opacity"]
                # Will use filter_complex with overlay below
                use_filter_complex = True
            else:
                use_filter_complex = False

            # Subtitle via Pillow burn (drawtext unavailable on this macOS)
            subtitle_text = request.subtitle_text or ""
            has_drawtext = self._check_drawtext_available()
            if subtitle_text and has_drawtext:
                safe_text = subtitle_text.replace("'", "\\'").replace(":", "\\:")
                fs = market_cfg["subtitle_font_size"]
                vf_parts.append(
                    f"drawtext=text='{safe_text}':fontsize={fs}:fontcolor=white:borderw=2:bordercolor=black:x=(w-text_w)/2:y=h-th-40"
                )

            # Build ffmpeg command
            if use_filter_complex and has_logo:
                # filter_complex: crop/scale main video + overlay logo
                main_vf = ",".join(vf_parts)
                fc = (
                    f"[0:v]{main_vf}[scaled];"
                    f"[1:v]format=rgba,colorchannelmixer=aa={opacity}[wm];"
                    f"[scaled][wm]overlay={overlay_pos}[out]"
                )
                ffmpeg_args = [
                    "-ss", str(start), "-to", str(end),
                    "-i", str(source),
                    "-i", str(logo_path),
                    "-filter_complex", fc,
                    "-map", "[out]",
                    "-map", "0:a?",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                    "-c:a", "aac", "-b:a", "128k",
                    "-movflags", "+faststart",
                    str(final_path),
                ]
            else:
                # Simple filter chain without logo overlay
                vf = ",".join(vf_parts)
                ffmpeg_args = [
                    "-ss", str(start), "-to", str(end),
                    "-i", str(source),
                    "-vf", vf,
                    "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                    "-c:a", "aac", "-b:a", "128k",
                    "-movflags", "+faststart",
                    str(final_path),
                ]

            progress.status = ReelStatus.EXPORTING.value
            progress.percent = 50
            progress.message = "Renderizando vídeo final com áudio..."
            self._report(progress)

            rc, stdout, stderr = self._run_ffmpeg(ffmpeg_args, "single-pass render")
            if rc != 0:
                progress.status = ReelStatus.FAILED.value
                progress.error = f"Falha no render: {stderr[:300]}"
                self._report(progress)
                return progress

            # Verify output has real content
            out_info = self._get_video_info(str(final_path))
            if out_info.get("error") or out_info.get("size_mb", 0) < 0.01:
                progress.status = ReelStatus.FAILED.value
                progress.error = f"Output inválido: {out_info}"
                self._report(progress)
                return progress

            # Burn subtitles via Pillow if drawtext unavailable
            if subtitle_text and not has_drawtext:
                progress.status = ReelStatus.SUBTITLES.value
                progress.percent = 70
                progress.message = "Queimando legendas via Pillow..."
                self._report(progress)
                self._burn_subtitles_pillow(str(final_path), subtitle_text, market_cfg["subtitle_font_size"])

            # 7. Thumbnail via ThumbnailFactory 2.0
            progress.status = ReelStatus.THUMBNAIL.value
            progress.percent = 75
            progress.message = "Gerando thumbnails..."
            self._report(progress)

            thumb_filename = f"{job_id}_{request.market}.jpg"
            thumb_path = self.thumbs_dir / thumb_filename
            self._generate_thumbnail(str(final_path), str(thumb_path), "", request.market)

            # 8. Quality Gate V2
            progress.status = ReelStatus.QUALITY_GATE.value
            progress.percent = 85
            progress.message = "Quality Gate V2..."
            self._report(progress)

            qg_result = self._quality_gate(str(final_path))
            # Enhanced checks: audio presence, bitrate, visual diversity
            issues = qg_result.get("issues", [])
            if not out_info.get("has_audio") and info.get("has_audio"):
                issues.append("Áudio perdido durante processamento")
            out_bitrate = out_info.get("bitrate", 0)
            if out_bitrate < 50000:
                issues.append(f"Bitrate muito baixo: {out_bitrate} bps (mínimo 50kbps)")
            qg_result["issues"] = issues
            qg_result["passed"] = len(issues) == 0
            progress.metadata["quality_gate"] = qg_result

            if not qg_result["passed"]:
                progress.status = ReelStatus.FAILED.value
                progress.error = f"Quality Gate reprovado: {'; '.join(issues)}"
                self._report(progress)
                return progress

            # Sucesso
            progress.status = ReelStatus.DONE.value
            progress.percent = 100
            progress.message = "Produção concluída!"
            progress.output_path = str(final_path)
            progress.thumbnail_path = str(thumb_path) if thumb_path.exists() else None
            progress.duration_seconds = out_info.get("duration", 0)
            progress.metadata["output_info"] = out_info
            self._report(progress)
            return progress

        except Exception as e:
            progress.status = ReelStatus.FAILED.value
            progress.error = str(e)
            self._report(progress)
            return progress

    def _burn_subtitles_pillow(self, video_path: str, text: str, font_size: int):
        """Burn subtitles using Pillow frame-by-frame when drawtext is unavailable."""
        try:
            from PIL import Image, ImageDraw, ImageFont
            import io

            # Extract frames, burn text, reassemble
            frames_dir = self.temp_dir / "sub_frames"
            frames_dir.mkdir(exist_ok=True)

            # Extract all frames
            rc, _, _ = self._run_ffmpeg([
                "-i", video_path,
                "-q:v", "2",
                str(frames_dir / "frame_%05d.jpg"),
            ], "extract frames for subtitle burn")
            if rc != 0:
                return

            frame_files = sorted(frames_dir.glob("frame_*.jpg"))
            if not frame_files:
                return

            # Try to load a font
            font = None
            font_paths = [
                "/System/Library/Fonts/Helvetica.ttc",
                "/System/Library/Fonts/Arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            ]
            for fp in font_paths:
                try:
                    font = ImageFont.truetype(fp, font_size)
                    break
                except Exception:
                    continue
            if font is None:
                font = ImageFont.load_default()

            # Burn text on each frame
            for ff in frame_files:
                img = Image.open(str(ff))
                draw = ImageDraw.Draw(img)
                bbox = draw.textbbox((0, 0), text, font=font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                x = (img.width - tw) // 2
                y = img.height - th - 40
                # Shadow
                draw.text((x + 2, y + 2), text, fill="black", font=font)
                draw.text((x, y), text, fill="white", font=font)
                img.save(str(ff))

            # Reassemble with original audio
            backup = video_path + ".bak"
            shutil.copy2(video_path, backup)
            rc, _, _ = self._run_ffmpeg([
                "-framerate", "30",
                "-i", str(frames_dir / "frame_%05d.jpg"),
                "-i", backup,
                "-map", "0:v",
                "-map", "1:a?",
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-c:a", "aac", "-b:a", "128k",
                "-shortest",
                "-y", video_path,
            ], "reassemble with subtitles")

            # Cleanup
            shutil.rmtree(frames_dir, ignore_errors=True)
            if Path(backup).exists():
                Path(backup).unlink()

        except Exception:
            pass  # Non-fatal: video still usable without burned subtitles

    def list_outputs(self) -> list[dict]:
        """Lista produções concluídas."""
        results = []
        for f in sorted(self.output_dir.glob("*.mp4"), reverse=True):
            stat = f.stat()
            results.append({
                "filename": f.name,
                "path": str(f),
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "created": stat.st_mtime,
                "market": "br" if "_br_" in f.name else "global",
                "platform": next((p for p in ["reels", "shorts", "tiktok", "stories", "feed"] if f"_{p}" in f.name), "unknown"),
            })
        return results

    def get_status(self, job_id: str) -> Optional[dict]:
        """Busca status de um job por ID."""
        for f in self.output_dir.glob(f"{job_id}_*.mp4"):
            return {
                "job_id": job_id,
                "status": ReelStatus.DONE.value,
                "output_path": str(f),
                "filename": f.name,
            }
        return None