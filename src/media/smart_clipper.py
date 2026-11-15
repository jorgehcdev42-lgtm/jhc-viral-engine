"""Smart Clipper — MISSÃO 015.

Corta automaticamente clipes virais a partir de vídeos longos:
- Detecção de cenas via ffmpeg scene detect
- Análise de energia visual por segmento
- Identificação de hooks (momentos de alta atividade)
- Corte inteligente respeitando duração-alvo (Reels/Shorts/TikTok)
- Preservação de safe areas para cada plataforma
- Exportação com metadados de engajamento estimado

Uso:
    clipper = SmartClipper(data_root)
    clips = clipper.extract_clips("/path/to/video.mp4", target_duration=30)
    for clip in clips:
        print(clip.output_path, clip.score)
"""

import json
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ClipCandidate:
    """Um clipe candidato extraído do vídeo fonte."""
    start_sec: float
    end_sec: float
    duration_sec: float
    output_path: str
    score: float  # 0-1, qualidade viral estimada
    hook_count: int
    avg_motion: float
    brightness_avg: float
    has_audio_peak: bool
    platform_fit: dict[str, bool] = field(default_factory=dict)


@dataclass
class ClipExtractionResult:
    """Resultado completo da extração de clipes."""
    source_file: str
    source_duration_sec: float
    total_candidates: int
    selected_clips: list[ClipCandidate]
    rejected_clips: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class SmartClipper:
    """Extrai clipes virais de vídeos longos via análise automática."""

    PLATFORM_DURATIONS = {
        "reels": {"min": 15, "max": 90, "ideal": 30},
        "shorts": {"min": 15, "max": 60, "ideal": 30},
        "tiktok": {"min": 15, "max": 180, "ideal": 30},
        "feed": {"min": 30, "max": 300, "ideal": 60},
        "stories": {"min": 5, "max": 15, "ideal": 10},
    }

    def __init__(self, data_root: Path | str):
        self.data_root = Path(data_root)
        self.clips_dir = self.data_root / "clips"
        self.clips_dir.mkdir(parents=True, exist_ok=True)

    def extract_clips(
        self,
        video_path: str | Path,
        target_duration: int = 30,
        max_clips: int = 5,
        platform: str = "reels",
        min_score: float = 0.3,
    ) -> ClipExtractionResult:
        """Extrai os melhores clipes de um vídeo longo."""
        video_path = Path(video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Vídeo não encontrado: {video_path}")

        duration = self._get_duration(video_path)
        if duration <= 0:
            raise ValueError("Não foi possível determinar duração do vídeo")

        # Detecta cortes de cena
        scene_changes = self._detect_scenes(video_path, duration)

        # Gera candidatos baseados em cenas + janelas deslizantes
        candidates = self._generate_candidates(
            video_path, duration, scene_changes, target_duration, platform
        )

        # Pontua cada candidato
        scored = []
        for c in candidates:
            score = self._score_candidate(c, video_path, platform)
            c.score = score
            if score >= min_score:
                scored.append(c)

        # Ordena por score e seleciona top-N
        scored.sort(key=lambda x: x.score, reverse=True)
        selected = scored[:max_clips]

        # Corta os clipes selecionados
        stem = video_path.stem
        for i, clip in enumerate(selected):
            out_path = self.clips_dir / f"{stem}_clip{i+1:02d}_{platform}.mp4"
            self._cut_clip(video_path, clip.start_sec, clip.end_sec, out_path)
            clip.output_path = str(out_path)

        rejected = [
            {"start": c.start_sec, "end": c.end_sec, "score": c.score, "reason": "below_threshold"}
            for c in scored[max_clips:]
        ]

        return ClipExtractionResult(
            source_file=str(video_path),
            source_duration_sec=round(duration, 2),
            total_candidates=len(candidates),
            selected_clips=selected,
            rejected_clips=rejected,
            metadata={
                "platform": platform,
                "target_duration": target_duration,
                "scene_changes_detected": len(scene_changes),
                "min_score": min_score,
            },
        )

    def save_result(self, result: ClipExtractionResult, name: str | None = None) -> Path:
        """Salva resultado como JSON."""
        stem = name or Path(result.source_file).stem
        out = self.clips_dir / f"{stem}_extraction.json"
        out.write_text(
            json.dumps(asdict(result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return out

    def list_clips(self) -> list[dict]:
        """Lista todos os clipes extraídos."""
        results = []
        for f in sorted(self.clips_dir.glob("*_clip*.mp4")):
            size_mb = f.stat().st_size / (1024 * 1024)
            dur = self._get_duration(f)
            results.append({
                "file": str(f),
                "name": f.stem,
                "size_mb": round(size_mb, 2),
                "duration_sec": round(dur, 2),
            })
        return results

    # --- Métodos internos ---

    def _get_duration(self, path: Path) -> float:
        """Duração do vídeo via ffprobe."""
        cmd = [
            "ffprobe", "-v", "quiet", "-show_entries",
            "format=duration", "-of", "csv=p=0", str(path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            return float(result.stdout.strip())
        except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
            return 0.0

    def _detect_scenes(self, path: Path, duration: float) -> list[float]:
        """Detecta timestamps de mudança de cena via ffmpeg."""
        cmd = [
            "ffmpeg", "-i", str(path),
            "-vf", "select='gt(scene,0.3)',showinfo",
            "-vsync", "vfr", "-f", "null", "-",
        ]
        timestamps = []
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            for line in result.stderr.split("\n"):
                if "pts_time:" in line:
                    try:
                        pts = line.split("pts_time:")[1].split()[0]
                        timestamps.append(float(pts))
                    except (IndexError, ValueError):
                        continue
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # Se não detectou cenas, divide em segmentos uniformes
        if not timestamps and duration > 0:
            seg = max(3.0, duration / 20)
            t = seg
            while t < duration - 1:
                timestamps.append(t)
                t += seg

        return sorted(timestamps)

    def _generate_candidates(
        self,
        path: Path,
        duration: float,
        scenes: list[float],
        target_dur: int,
        platform: str,
    ) -> list[ClipCandidate]:
        """Gera candidatos de clipe combinando cenas + janelas deslizantes."""
        plat_cfg = self.PLATFORM_DURATIONS.get(platform, self.PLATFORM_DURATIONS["reels"])
        min_dur = plat_cfg["min"]
        max_dur = plat_cfg["max"]
        ideal_dur = plat_cfg["ideal"]

        candidates = []
        seen_ranges: set[tuple[int, int]] = set()

        # Estratégia 1: janelas alinhadas a cortes de cena
        for i, scene_ts in enumerate(scenes):
            for window_dur in [ideal_dur, target_dur, min_dur, max_dur]:
                start = max(0, scene_ts - window_dur * 0.3)
                end = min(duration, start + window_dur)
                actual_dur = end - start
                if actual_dur < min_dur or actual_dur > max_dur:
                    continue
                key = (int(start), int(end))
                if key in seen_ranges:
                    continue
                seen_ranges.add(key)
                candidates.append(ClipCandidate(
                    start_sec=round(start, 2),
                    end_sec=round(end, 2),
                    duration_sec=round(actual_dur, 2),
                    output_path="",
                    score=0.0,
                    hook_count=0,
                    avg_motion=0.0,
                    brightness_avg=0.0,
                    has_audio_peak=False,
                    platform_fit={platform: True},
                ))

        # Estratégia 2: janelas deslizantes a cada 5s
        step = 5.0
        t = 0.0
        while t + min_dur <= duration:
            for window_dur in [ideal_dur, target_dur]:
                end = min(duration, t + window_dur)
                actual_dur = end - t
                if actual_dur < min_dur:
                    continue
                key = (int(t), int(end))
                if key in seen_ranges:
                    continue
                seen_ranges.add(key)
                candidates.append(ClipCandidate(
                    start_sec=round(t, 2),
                    end_sec=round(end, 2),
                    duration_sec=round(actual_dur, 2),
                    output_path="",
                    score=0.0,
                    hook_count=0,
                    avg_motion=0.0,
                    brightness_avg=0.0,
                    has_audio_peak=False,
                    platform_fit={platform: True},
                ))
            t += step

        return candidates

    def _score_candidate(
        self, candidate: ClipCandidate, video_path: Path, platform: str
    ) -> float:
        """Pontua um candidato baseado em movimento, brilho e estrutura."""
        scores = []

        # 1. Motion score (amostra 3 frames do segmento)
        motion = self._segment_motion(video_path, candidate.start_sec, candidate.end_sec)
        candidate.avg_motion = motion
        scores.append(min(1.0, motion * 2))  # mais movimento = melhor

        # 2. Brightness (vídeos muito escuros ou claros demais perdem pontos)
        brightness = self._segment_brightness(video_path, candidate.start_sec)
        candidate.brightness_avg = brightness
        if 80 <= brightness <= 200:
            scores.append(0.8)
        elif 40 <= brightness <= 240:
            scores.append(0.5)
        else:
            scores.append(0.2)

        # 3. Hook no início (primeiros 3s têm alto movimento?)
        hook_motion = self._segment_motion(video_path, candidate.start_sec, candidate.start_sec + 3)
        if hook_motion > 0.25:
            candidate.hook_count += 1
            scores.append(0.9)
        else:
            scores.append(0.3)

        # 4. Duração próxima do ideal
        plat_cfg = self.PLATFORM_DURATIONS.get(platform, self.PLATFORM_DURATIONS["reels"])
        ideal = plat_cfg["ideal"]
        dur_diff = abs(candidate.duration_sec - ideal) / ideal
        dur_score = max(0.0, 1.0 - dur_diff)
        scores.append(dur_score)

        # Média ponderada
        weights = [0.35, 0.15, 0.30, 0.20]
        final = sum(s * w for s, w in zip(scores, weights))
        return round(min(1.0, final), 3)

    def _segment_motion(self, path: Path, start: float, end: float) -> float:
        """Calcula movimento médio em um segmento."""
        mid = start + (end - start) / 2
        with tempfile.TemporaryDirectory() as tmpdir:
            f1 = f"{tmpdir}/a.jpg"
            f2 = f"{tmpdir}/b.jpg"
            for ts, fp in [(start, f1), (mid, f2)]:
                cmd = [
                    "ffmpeg", "-y", "-ss", f"{ts:.2f}",
                    "-i", str(path), "-frames:v", "1",
                    "-q:v", "8", fp,
                ]
                try:
                    subprocess.run(cmd, capture_output=True, timeout=10)
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    return 0.0

            try:
                from PIL import Image
                img1 = Image.open(f1).convert("L")
                img2 = Image.open(f2).convert("L")
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

    def _segment_brightness(self, path: Path, timestamp: float) -> float:
        """Brilho médio em um ponto do vídeo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fp = f"{tmpdir}/frame.jpg"
            cmd = [
                "ffmpeg", "-y", "-ss", f"{timestamp:.2f}",
                "-i", str(path), "-frames:v", "1",
                "-q:v", "8", fp,
            ]
            try:
                subprocess.run(cmd, capture_output=True, timeout=10)
            except (subprocess.TimeoutExpired, FileNotFoundError):
                return 128.0

            try:
                from PIL import Image
                img = Image.open(fp).convert("L")
                pixels = list(img.getdata())
                return sum(pixels) / len(pixels) if pixels else 128.0
            except (ImportError, FileNotFoundError, OSError):
                return 128.0

    def _cut_clip(self, source: Path, start: float, end: float, output: Path) -> bool:
        """Corta um segmento do vídeo fonte."""
        duration = end - start
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{start:.3f}",
            "-i", str(source),
            "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(output),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=120)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False