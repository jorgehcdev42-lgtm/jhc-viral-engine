"""Integração Audiovisual — MISSÃO 017.

Sincroniza áudio, legendas e narração com vídeo:
- Mixagem de trilha sonora com volume adaptativo
- Geração de legendas SRT/VTT a partir de texto segmentado
- Overlay de narração TTS sobre vídeo existente
- Ducking automático (reduz música quando há fala)
- Exportação com áudio multiplexado
- Suporte a múltiplos formatos de legenda

Uso:
    sync = AudioVisualSync(data_root)
    result = sync.mix_audio(video_path, music_path, narration_path)
    srt_path = sync.generate_subtitles(segments, output_path)
"""

import json
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SubtitleSegment:
    """Um segmento de legenda/narração."""
    start_sec: float
    end_sec: float
    text: str
    speaker: str = ""  # opcional, para multi-speaker


@dataclass
class AudioMixResult:
    """Resultado da mixagem de áudio."""
    output_path: str
    duration_sec: float
    has_music: bool
    has_narration: bool
    ducking_applied: bool
    file_size_mb: float


@dataclass
class SubtitleFile:
    """Arquivo de legenda gerado."""
    path: str
    format: str  # "srt", "vtt", "ass"
    segment_count: int
    language: str


class AudioVisualSync:
    """Sincronização audiovisual para vídeos virais."""

    def __init__(self, data_root: Path | str):
        self.data_root = Path(data_root)
        self.audio_dir = self.data_root / "audio"
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.subtitles_dir = self.data_root / "subtitles"
        self.subtitles_dir.mkdir(parents=True, exist_ok=True)

    def mix_audio(
        self,
        video_path: str | Path,
        music_path: str | Path | None = None,
        narration_path: str | Path | None = None,
        music_volume: float = 0.3,
        narration_volume: float = 1.0,
        ducking: bool = True,
        output_name: str | None = None,
    ) -> AudioMixResult:
        """Mixa música e/ou narração com o áudio original do vídeo."""
        video_path = Path(video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Vídeo não encontrado: {video_path}")

        stem = output_name or video_path.stem
        output_path = self.audio_dir / f"{stem}_mixed.mp4"

        inputs = ["-i", str(video_path)]
        filter_parts = []
        input_idx = 0
        has_music = False
        has_narration = False

        if music_path and Path(music_path).exists():
            inputs.extend(["-i", str(music_path)])
            input_idx += 1
            has_music = True
            if ducking and narration_path and Path(narration_path).exists():
                # Ducking: reduz música quando narração está ativa
                filter_parts.append(
                    f"[{input_idx}:a]volume={music_volume}[music]"
                )
            else:
                filter_parts.append(
                    f"[{input_idx}:a]volume={music_volume}[music]"
                )

        if narration_path and Path(narration_path).exists():
            inputs.extend(["-i", str(narration_path)])
            input_idx += 1
            has_narration = True
            filter_parts.append(
                f"[{input_idx}:a]volume={narration_volume}[narr]"
            )

        # Constrói filtro de mixagem
        if has_music and has_narration:
            if ducking:
                # Sidechain ducking: música baixa quando narração fala
                filter_parts.append(
                    "[music][narr]sidechaincompress=threshold=0.02:"
                    "ratio=4:attack=50:release=300[ducked]"
                )
                filter_parts.append("[0:a][ducked][narr]amix=inputs=3[aout]")
            else:
                filter_parts.append("[0:a][music][narr]amix=inputs=3[aout]")
        elif has_music:
            filter_parts.append("[0:a][music]amix=inputs=2[aout]")
        elif has_narration:
            filter_parts.append("[0:a][narr]amix=inputs=2[aout]")
        else:
            filter_parts.append("[0:a]acopy[aout]")

        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", ";".join(filter_parts),
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(output_path),
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, timeout=120)
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg mix failed: {result.stderr[-300:]}")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Audio mix timeout (>120s)")
        except FileNotFoundError:
            raise RuntimeError("ffmpeg not found")

        duration = self._get_duration(output_path)
        file_size = output_path.stat().st_size / (1024 * 1024)

        return AudioMixResult(
            output_path=str(output_path),
            duration_sec=round(duration, 2),
            has_music=has_music,
            has_narration=has_narration,
            ducking_applied=ducking and has_music and has_narration,
            file_size_mb=round(file_size, 2),
        )

    def generate_subtitles(
        self,
        segments: list[SubtitleSegment] | list[dict],
        output_name: str,
        fmt: str = "srt",
        language: str = "pt-BR",
    ) -> SubtitleFile:
        """Gera arquivo de legenda a partir de segmentos temporizados."""
        if fmt not in ("srt", "vtt", "ass"):
            raise ValueError(f"Formato não suportado: {fmt}")

        out_path = self.subtitles_dir / f"{output_name}.{fmt}"

        # Normaliza segmentos
        normalized = []
        for s in segments:
            if isinstance(s, dict):
                normalized.append(SubtitleSegment(
                    start_sec=float(s.get("start_sec", 0)),
                    end_sec=float(s.get("end_sec", 0)),
                    text=s.get("text", ""),
                    speaker=s.get("speaker", ""),
                ))
            else:
                normalized.append(s)

        if fmt == "srt":
            content = self._to_srt(normalized)
        elif fmt == "vtt":
            content = self._to_vtt(normalized)
        else:
            content = self._to_ass(normalized)

        out_path.write_text(content, encoding="utf-8")

        return SubtitleFile(
            path=str(out_path),
            format=fmt,
            segment_count=len(normalized),
            language=language,
        )

    def burn_subtitles(
        self,
        video_path: str | Path,
        subtitle_path: str | Path,
        output_name: str | None = None,
        font_size: int = 24,
        font_color: str = "white",
        outline_color: str = "black",
        outline_width: int = 2,
        position: str = "bottom",  # bottom, center, top
    ) -> str:
        """Grava legendas diretamente no vídeo (hardcoded)."""
        video_path = Path(video_path)
        subtitle_path = Path(subtitle_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Vídeo não encontrado: {video_path}")
        if not subtitle_path.exists():
            raise FileNotFoundError(f"Legenda não encontrada: {subtitle_path}")

        stem = output_name or f"{video_path.stem}_subtitled"
        output_path = self.audio_dir / f"{stem}.mp4"

        # Posição vertical
        y_pos = {"bottom": "h-h*0.1", "center": "(h-th)/2", "top": "h*0.1"}
        y = y_pos.get(position, y_pos["bottom"])

        # Escapa path da legenda para filtro subtitles
        safe_sub = str(subtitle_path).replace("\\", "/").replace(":", "\\:")

        vf = (
            f"subtitles='{safe_sub}':force_style='"
            f"FontSize={font_size},"
            f"PrimaryColour=&H00{''.join(reversed([font_color_to_bgr(font_color)[i:i+2] for i in range(0, 6, 2)]))},"
            f"OutlineColour=&H00{''.join(reversed([font_color_to_bgr(outline_color)[i:i+2] for i in range(0, 6, 2)]))},"
            f"Outline={outline_width},"
            f"Alignment={alignment_from_position(position)}'"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            if result.returncode != 0:
                raise RuntimeError(f"Subtitle burn failed: {result.stderr[-300:]}")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Subtitle burn timeout (>300s)")
        except FileNotFoundError:
            raise RuntimeError("ffmpeg not found")

        return str(output_path)

    def list_mixed(self) -> list[dict]:
        """Lista todos os arquivos de áudio mixados."""
        results = []
        for f in sorted(self.audio_dir.glob("*_mixed.mp4")):
            size_mb = f.stat().st_size / (1024 * 1024)
            dur = self._get_duration(f)
            results.append({
                "file": str(f),
                "name": f.stem,
                "size_mb": round(size_mb, 2),
                "duration_sec": round(dur, 2),
            })
        return results

    def list_subtitles(self) -> list[dict]:
        """Lista todos os arquivos de legenda."""
        results = []
        for f in sorted(self.subtitles_dir.glob("*.*")):
            if f.suffix.lower() in (".srt", ".vtt", ".ass"):
                lines = len(f.read_text(encoding="utf-8").strip().split("\n"))
                results.append({
                    "file": str(f),
                    "name": f.stem,
                    "format": f.suffix.lstrip("."),
                    "lines": lines,
                })
        return results

    # --- Métodos internos ---

    def _get_duration(self, path: Path) -> float:
        cmd = [
            "ffprobe", "-v", "quiet", "-show_entries",
            "format=duration", "-of", "csv=p=0", str(path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            return float(result.stdout.strip())
        except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
            return 0.0

    def _to_srt(self, segments: list[SubtitleSegment]) -> str:
        lines = []
        for i, seg in enumerate(segments, 1):
            start = self._format_srt_time(seg.start_sec)
            end = self._format_srt_time(seg.end_sec)
            text = seg.text.replace("\n", " ")
            lines.append(f"{i}")
            lines.append(f"{start} --> {end}")
            lines.append(text)
            lines.append("")
        return "\n".join(lines)

    def _to_vtt(self, segments: list[SubtitleSegment]) -> str:
        lines = ["WEBVTT", ""]
        for i, seg in enumerate(segments, 1):
            start = self._format_vtt_time(seg.start_sec)
            end = self._format_vtt_time(seg.end_sec)
            text = seg.text.replace("\n", " ")
            lines.append(f"{i}")
            lines.append(f"{start} --> {end}")
            lines.append(text)
            lines.append("")
        return "\n".join(lines)

    def _to_ass(self, segments: list[SubtitleSegment]) -> str:
        header = """[Script Info]
Title: JHC Viral Engine Subtitles
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,20,20,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        events = []
        for seg in segments:
            start = self._format_ass_time(seg.start_sec)
            end = self._format_ass_time(seg.end_sec)
            text = seg.text.replace("\n", "\\N")
            events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
        return header + "\n".join(events)

    @staticmethod
    def _format_srt_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    @staticmethod
    def _format_vtt_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

    @staticmethod
    def _format_ass_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int((seconds % 1) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def font_color_to_bgr(color: str) -> str:
    """Converte nome de cor ou hex para BGR (formato ASS)."""
    colors = {
        "white": "FFFFFF", "black": "000000",
        "red": "0000FF", "green": "00FF00", "blue": "FF0000",
        "yellow": "00FFFF", "cyan": "FFFF00", "magenta": "FF00FF",
    }
    if color.lower() in colors:
        return colors[color.lower()]
    hex_clean = color.lstrip("#")
    if len(hex_clean) == 6:
        return hex_clean
    return "FFFFFF"


def alignment_from_position(position: str) -> int:
    """Converte posição para código de alinhamento ASS."""
    return {"bottom": 2, "center": 5, "top": 8}.get(position, 2)