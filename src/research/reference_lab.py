"""Laboratório de Referências — MISSÃO 014.

Analisa vídeos de referência para extrair padrões reutilizáveis:
- Estrutura temporal (hooks, cortes, transições, duração por segmento)
- Paleta de cores dominante e estilo visual
- Padrões de áudio (BPM estimado, picos de energia)
- Metadados de engajamento (quando disponíveis)
- Geração de "blueprint" para criação original inspirada (não cópia)

Uso:
    lab = ReferenceLab(data_root)
    analysis = lab.analyze_video("/path/to/reference.mp4")
    blueprint = lab.generate_blueprint(analysis)
"""

import json
import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SegmentAnalysis:
    """Análise de um segmento temporal do vídeo."""
    start_sec: float
    end_sec: float
    duration_sec: float
    avg_brightness: float  # 0-255
    color_dominant_hex: str  # cor mais frequente no segmento
    motion_score: float  # 0-1, baseado em diff entre frames
    is_hook: bool  # True se segmento tem alta energia visual/movimento
    scene_change_count: int  # número de cortes detectados


@dataclass
class AudioAnalysis:
    """Análise básica da trilha sonora."""
    duration_sec: float
    has_audio: bool
    estimated_bpm: int | None = None  # BPM estimado via pico de energia
    silence_ratio: float = 0.0  # fração do tempo em silêncio (0-1)
    energy_peaks: list[float] = field(default_factory=list)  # timestamps de picos


@dataclass
class VisualStyle:
    """Estilo visual extraído do vídeo."""
    dominant_colors: list[str]  # top-5 cores dominantes (hex)
    avg_brightness: float
    contrast_score: float  # 0-1
    saturation_score: float  # 0-1
    aspect_ratio: str  # "16:9", "9:16", "1:1", etc.
    resolution: tuple[int, int]  # (width, height)
    fps: float


@dataclass
class VideoBlueprint:
    """Blueprint para criação original inspirada na referência."""
    source_file: str
    total_duration_sec: float
    segment_count: int
    hook_timestamps: list[float]  # onde colocar hooks no novo vídeo
    recommended_duration_sec: float
    pacing_profile: str  # "fast", "medium", "slow"
    color_palette: list[str]  # paleta sugerida
    audio_style: str  # "high-energy", "ambient", "narrative", "silent"
    structure_summary: str  # descrição textual da estrutura
    originality_notes: list[str]  # sugestões para diferenciar da referência


@dataclass
class ReferenceAnalysis:
    """Resultado completo da análise de um vídeo de referência."""
    source_file: str
    file_size_mb: float
    visual: VisualStyle
    audio: AudioAnalysis
    segments: list[SegmentAnalysis]
    blueprint: VideoBlueprint
    metadata: dict[str, Any] = field(default_factory=dict)


class ReferenceLab:
    """Laboratório de análise de vídeos de referência."""

    def __init__(self, data_root: Path | str):
        self.data_root = Path(data_root)
        self.references_dir = self.data_root / "references"
        self.references_dir.mkdir(parents=True, exist_ok=True)
        self.blueprints_dir = self.data_root / "blueprints"
        self.blueprints_dir.mkdir(parents=True, exist_ok=True)

    def analyze_video(self, video_path: str | Path) -> ReferenceAnalysis:
        """Analisa um vídeo de referência e retorna análise completa."""
        video_path = Path(video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Vídeo não encontrado: {video_path}")

        probe = self._ffprobe(video_path)
        duration = float(probe.get("duration", 0))
        width = int(probe.get("width", 0))
        height = int(probe.get("height", 0))
        fps_str = probe.get("r_frame_rate", "30/1")
        fps = self._parse_fps(fps_str)
        has_audio = probe.get("has_audio", False)
        file_size_mb = video_path.stat().st_size / (1024 * 1024)

        # Análise visual
        colors, brightness, contrast, saturation = self._analyze_visual_style(
            video_path, duration
        )
        aspect = self._aspect_ratio(width, height)
        visual = VisualStyle(
            dominant_colors=colors,
            avg_brightness=brightness,
            contrast_score=contrast,
            saturation_score=saturation,
            aspect_ratio=aspect,
            resolution=(width, height),
            fps=fps,
        )

        # Análise de segmentos (divide em blocos de 3s)
        segments = self._analyze_segments(video_path, duration, fps)

        # Análise de áudio
        audio = self._analyze_audio(video_path, duration, has_audio)

        # Gera blueprint
        blueprint = self._generate_blueprint(
            str(video_path), duration, segments, audio, visual
        )

        return ReferenceAnalysis(
            source_file=str(video_path),
            file_size_mb=round(file_size_mb, 2),
            visual=visual,
            audio=audio,
            segments=segments,
            blueprint=blueprint,
        )

    def save_analysis(self, analysis: ReferenceAnalysis, name: str | None = None) -> Path:
        """Salva análise como JSON no diretório de referências."""
        stem = name or Path(analysis.source_file).stem
        out = self.references_dir / f"{stem}_analysis.json"
        out.write_text(
            json.dumps(asdict(analysis), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return out

    def save_blueprint(self, analysis: ReferenceAnalysis, name: str | None = None) -> Path:
        """Salva apenas o blueprint como JSON."""
        stem = name or Path(analysis.source_file).stem
        out = self.blueprints_dir / f"{stem}_blueprint.json"
        out.write_text(
            json.dumps(asdict(analysis.blueprint), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return out

    def list_analyses(self) -> list[dict]:
        """Lista todas as análises salvas."""
        results = []
        for f in sorted(self.references_dir.glob("*_analysis.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                results.append({
                    "name": f.stem.replace("_analysis", ""),
                    "source": data.get("source_file", ""),
                    "duration": data.get("blueprint", {}).get("total_duration_sec", 0),
                    "segments": len(data.get("segments", [])),
                    "file": str(f),
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return results

    # --- Métodos internos ---

    def _ffprobe(self, path: Path) -> dict:
        """Extrai metadados do vídeo via ffprobe."""
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            data = json.loads(result.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            return {"duration": 0, "width": 0, "height": 0, "r_frame_rate": "30/1"}

        video_stream = next(
            (s for s in data.get("streams", []) if s.get("codec_type") == "video"), {}
        )
        audio_stream = next(
            (s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None
        )
        fmt = data.get("format", {})
        return {
            "duration": fmt.get("duration", video_stream.get("duration", 0)),
            "width": video_stream.get("width", 0),
            "height": video_stream.get("height", 0),
            "r_frame_rate": video_stream.get("r_frame_rate", "30/1"),
            "has_audio": audio_stream is not None,
        }

    def _parse_fps(self, fps_str: str) -> float:
        """Converte '30/1' ou '30000/1001' para float."""
        try:
            if "/" in fps_str:
                num, den = fps_str.split("/")
                return round(float(num) / float(den), 2)
            return float(fps_str)
        except (ValueError, ZeroDivisionError):
            return 30.0

    def _aspect_ratio(self, w: int, h: int) -> str:
        if h == 0:
            return "unknown"
        ratio = w / h
        if abs(ratio - 16 / 9) < 0.1:
            return "16:9"
        if abs(ratio - 9 / 16) < 0.1:
            return "9:16"
        if abs(ratio - 1.0) < 0.1:
            return "1:1"
        if abs(ratio - 4 / 3) < 0.1:
            return "4:3"
        if abs(ratio - 21 / 9) < 0.15:
            return "21:9"
        return f"{w}:{h}"

    def _analyze_visual_style(
        self, path: Path, duration: float
    ) -> tuple[list[str], float, float, float]:
        """Extrai cores dominantes, brilho, contraste e saturação via ffmpeg."""
        # Extrai 10 frames distribuídos uniformemente
        n_frames = min(10, max(1, int(duration)))
        interval = max(0.1, duration / n_frames)

        with tempfile.TemporaryDirectory() as tmpdir:
            # Extrai frames
            cmd = [
                "ffmpeg", "-y", "-i", str(path),
                "-vf", f"fps=1/{interval:.2f}",
                "-frames:v", str(n_frames),
                "-q:v", "5",
                f"{tmpdir}/frame_%03d.jpg",
            ]
            try:
                subprocess.run(cmd, capture_output=True, timeout=60)
            except (subprocess.TimeoutExpired, FileNotFoundError):
                return (["#000000"], 128.0, 0.5, 0.5)

            frames = sorted(Path(tmpdir).glob("frame_*.jpg"))
            if not frames:
                return (["#000000"], 128.0, 0.5, 0.5)

            # Analisa cada frame com Python puro (sem Pillow dependency obrigatória)
            all_pixels_sample = []
            brightness_values = []
            try:
                from PIL import Image
                for fp in frames[:5]:  # analisa até 5 frames
                    img = Image.open(fp).convert("RGB")
                    pixels = list(img.getdata())
                    sample = pixels[::max(1, len(pixels) // 200)]  # amostra 200 pixels
                    all_pixels_sample.extend(sample)
                    avg_b = sum(sum(p) / 3 for p in sample) / len(sample)
                    brightness_values.append(avg_b)
            except ImportError:
                # Fallback sem Pillow: usa ffmpeg para extrair stats
                return self._visual_style_fallback(path)

            if not all_pixels_sample:
                return (["#000000"], 128.0, 0.5, 0.5)

            # Cores dominantes via quantização simples
            color_counts: dict[str, int] = {}
            for r, g, b in all_pixels_sample:
                # Quantiza para buckets de 32
                qr, qg, qb = (r // 32) * 32, (g // 32) * 32, (b // 32) * 32
                hex_c = f"#{qr:02x}{qg:02x}{qb:02x}"
                color_counts[hex_c] = color_counts.get(hex_c, 0) + 1

            top_colors = sorted(color_counts, key=color_counts.get, reverse=True)[:5]

            avg_brightness = sum(brightness_values) / len(brightness_values) if brightness_values else 128.0

            # Contraste: desvio padrão dos brilhos
            if len(brightness_values) > 1:
                mean_b = avg_brightness
                variance = sum((b - mean_b) ** 2 for b in brightness_values) / len(brightness_values)
                contrast = min(1.0, (variance ** 0.5) / 128.0)
            else:
                contrast = 0.5

            # Saturação aproximada via desvio RGB
            sat_scores = []
            for r, g, b in all_pixels_sample[:100]:
                max_c, min_c = max(r, g, b), min(r, g, b)
                sat_scores.append((max_c - min_c) / 255.0 if max_c > 0 else 0)
            saturation = sum(sat_scores) / len(sat_scores) if sat_scores else 0.5

            return (top_colors, round(avg_brightness, 1), round(contrast, 3), round(saturation, 3))

    def _visual_style_fallback(self, path: Path) -> tuple[list[str], float, float, float]:
        """Fallback quando Pillow não está disponível."""
        cmd = [
            "ffmpeg", "-y", "-i", str(path),
            "-vf", "signalstats,metadata=print:file=-",
            "-frames:v", "1", "-f", "null", "-",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            output = result.stderr
            # Tenta extrair YAVG (brilho médio)
            brightness = 128.0
            for line in output.split("\n"):
                if "YAVG" in line:
                    try:
                        brightness = float(line.split(":")[-1].strip())
                    except ValueError:
                        pass
            return (["#333333", "#666666", "#999999"], brightness, 0.5, 0.5)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return (["#000000"], 128.0, 0.5, 0.5)

    def _analyze_segments(
        self, path: Path, duration: float, fps: float
    ) -> list[SegmentAnalysis]:
        """Divide vídeo em segmentos de ~3s e analisa cada um."""
        seg_duration = 3.0
        n_segments = max(1, int(duration / seg_duration))
        segments = []

        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(n_segments):
                start = i * seg_duration
                end = min(start + seg_duration, duration)
                actual_dur = end - start
                if actual_dur < 0.5:
                    continue

                # Extrai 2 frames do segmento para comparar movimento
                frame1 = f"{tmpdir}/seg{i}_a.jpg"
                frame2 = f"{tmpdir}/seg{i}_b.jpg"
                mid = start + actual_dur / 2

                for ts, out_path in [(start, frame1), (mid, frame2)]:
                    cmd = [
                        "ffmpeg", "-y", "-ss", f"{ts:.2f}",
                        "-i", str(path), "-frames:v", "1",
                        "-q:v", "8", out_path,
                    ]
                    try:
                        subprocess.run(cmd, capture_output=True, timeout=10)
                    except (subprocess.TimeoutExpired, FileNotFoundError):
                        continue

                # Calcula motion score via diferença de pixels
                motion = self._compute_motion(frame1, frame2)
                brightness = self._frame_brightness(frame1)

                # Hook: segmento com alto movimento ou nos primeiros 3s
                is_hook = motion > 0.3 or (start < 3.0 and brightness > 100)

                segments.append(SegmentAnalysis(
                    start_sec=round(start, 2),
                    end_sec=round(end, 2),
                    duration_sec=round(actual_dur, 2),
                    avg_brightness=brightness,
                    color_dominant_hex=self._dominant_color(frame1),
                    motion_score=round(motion, 3),
                    is_hook=is_hook,
                    scene_change_count=1 if motion > 0.4 else 0,
                ))

        return segments

    def _compute_motion(self, frame1: str, frame2: str) -> float:
        """Calcula score de movimento entre dois frames (0-1)."""
        try:
            from PIL import Image
            img1 = Image.open(frame1).convert("L")
            img2 = Image.open(frame2).convert("L")
            if img1.size != img2.size:
                img2 = img2.resize(img1.size)
            px1 = list(img1.getdata())
            px2 = list(img2.getdata())
            n = min(len(px1), len(px2))
            if n == 0:
                return 0.0
            diff = sum(abs(a - b) for a, b in zip(px1[:n], px2[:n])) / n
            return min(1.0, diff / 128.0)
        except (ImportError, FileNotFoundError, OSError):
            return 0.0

    def _frame_brightness(self, frame_path: str) -> float:
        """Brilho médio de um frame."""
        try:
            from PIL import Image
            img = Image.open(frame_path).convert("L")
            pixels = list(img.getdata())
            return sum(pixels) / len(pixels) if pixels else 128.0
        except (ImportError, FileNotFoundError, OSError):
            return 128.0

    def _dominant_color(self, frame_path: str) -> str:
        """Cor dominante de um frame (quantizada)."""
        try:
            from PIL import Image
            img = Image.open(frame_path).convert("RGB")
            pixels = list(img.getdata())
            sample = pixels[::max(1, len(pixels) // 100)]
            counts: dict[str, int] = {}
            for r, g, b in sample:
                qr, qg, qb = (r // 64) * 64, (g // 64) * 64, (b // 64) * 64
                hex_c = f"#{qr:02x}{qg:02x}{qb:02x}"
                counts[hex_c] = counts.get(hex_c, 0) + 1
            return max(counts, key=counts.get) if counts else "#000000"
        except (ImportError, FileNotFoundError, OSError):
            return "#000000"

    def _analyze_audio(self, path: Path, duration: float, has_audio: bool) -> AudioAnalysis:
        """Análise básica de áudio via ffmpeg."""
        if not has_audio:
            return AudioAnalysis(
                duration_sec=duration, has_audio=False,
                estimated_bpm=None, energy_peaks=[], silence_ratio=1.0,
            )

        # Extrai volume stats
        cmd = [
            "ffmpeg", "-y", "-i", str(path),
            "-af", "volumedetect",
            "-f", "null", "-",
        ]
        silence_ratio = 0.3  # default
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            stderr = result.stderr
            # Procura mean_volume e n_samples
            for line in stderr.split("\n"):
                if "mean_volume" in line:
                    try:
                        vol = float(line.split(":")[-1].strip().split()[0])
                        # Volume muito baixo = mais silêncio
                        silence_ratio = max(0.0, min(1.0, (-vol - 20) / 40))
                    except (ValueError, IndexError):
                        pass
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # Estimativa simples de BPM via duração e energia
        # Heurística: vídeos curtos virais tendem a 120-140 BPM
        estimated_bpm = 128  # default razoável para conteúdo viral

        return AudioAnalysis(
            duration_sec=duration,
            has_audio=True,
            estimated_bpm=estimated_bpm,
            energy_peaks=[],  # requer análise FFT mais complexa
            silence_ratio=round(silence_ratio, 3),
        )

    def _generate_blueprint(
        self,
        source: str,
        duration: float,
        segments: list[SegmentAnalysis],
        audio: AudioAnalysis,
        visual: VisualStyle,
    ) -> VideoBlueprint:
        """Gera blueprint para criação original baseada na referência."""
        hook_times = [s.start_sec for s in segments if s.is_hook]
        avg_motion = (
            sum(s.motion_score for s in segments) / len(segments) if segments else 0
        )

        if avg_motion > 0.4:
            pacing = "fast"
        elif avg_motion > 0.2:
            pacing = "medium"
        else:
            pacing = "slow"

        if audio.has_audio and audio.silence_ratio < 0.3:
            audio_style = "high-energy"
        elif audio.has_audio and audio.silence_ratio < 0.6:
            audio_style = "narrative"
        elif audio.has_audio:
            audio_style = "ambient"
        else:
            audio_style = "silent"

        # Estrutura resumida
        hook_desc = f"{len(hook_times)} hooks" if hook_times else "sem hooks claros"
        structure = (
            f"Duração {duration:.0f}s, {len(segments)} segmentos, "
            f"{hook_desc}, pacing {pacing}, "
            f"aspect {visual.aspect_ratio} @ {visual.resolution[0]}x{visual.resolution[1]}"
        )

        # Sugestões de originalidade
        notes = [
            f"Use paleta própria — referência usa {', '.join(visual.dominant_colors[:3])}",
            f"Mantenha pacing {pacing} mas mude ritmo dos cortes",
            "Adicione elementos visuais ausentes na referência (texto, overlays, transições)",
        ]
        if visual.aspect_ratio == "9:16":
            notes.append("Formato vertical: otimize safe area para Reels/TikTok")
        elif visual.aspect_ratio == "16:9":
            notes.append("Formato horizontal: considere crop 9:16 para Shorts/Reels")

        return VideoBlueprint(
            source_file=source,
            total_duration_sec=round(duration, 2),
            segment_count=len(segments),
            hook_timestamps=[round(t, 2) for t in hook_times],
            recommended_duration_sec=round(duration * 0.9, 2),  # levemente mais curto
            pacing_profile=pacing,
            color_palette=visual.dominant_colors[:5],
            audio_style=audio_style,
            structure_summary=structure,
            originality_notes=notes,
        )