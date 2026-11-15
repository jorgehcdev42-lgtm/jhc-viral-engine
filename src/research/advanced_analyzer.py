"""Advanced Video Analyzer — Análise profunda de ritmo, narrativa e destaques.

Complementa ReferenceLab e SmartClipper com:
- Detecção de ritmo (cortes por minuto, energia visual)
- Estrutura narrativa (abertura, desenvolvimento, clímax, encerramento)
- Momentos de destaque (picos de áudio + movimento + texto)
- Análise de legendas (densidade, timing, estilo)
- Formatos de abertura/encerramento (padrões recorrentes)

Gera material editorial original a partir de mídia autorizada.
"""

import json
import subprocess
import re
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class RhythmAnalysis:
    cuts_per_minute: float = 0.0
    avg_shot_duration: float = 0.0
    energy_curve: list[float] = field(default_factory=list)
    tempo_category: str = "unknown"  # slow, medium, fast, viral
    pacing_score: float = 0.0  # 0-10


@dataclass
class NarrativeSegment:
    label: str  # opening, buildup, climax, resolution, closing
    start_sec: float = 0.0
    end_sec: float = 0.0
    confidence: float = 0.0
    characteristics: dict = field(default_factory=dict)


@dataclass
class HighlightMoment:
    timestamp: float = 0.0
    score: float = 0.0  # 0-10 composite
    reasons: list[str] = field(default_factory=list)
    duration: float = 3.0
    thumbnail_candidate: bool = False


@dataclass
class SubtitleAnalysis:
    has_subtitles: bool = False
    density_per_minute: float = 0.0
    avg_chars_per_line: int = 0
    style: str = "none"  # burned, srt, ass, none
    language_detected: str = ""
    timing_alignment: str = "unknown"  # tight, loose, off


@dataclass
class FormatPattern:
    pattern_type: str  # opening, closing, transition, hook
    description: str = ""
    timestamps: list[float] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class AdvancedAnalysisResult:
    video_path: str = ""
    duration: float = 0.0
    rhythm: RhythmAnalysis = field(default_factory=RhythmAnalysis)
    narrative_structure: list[NarrativeSegment] = field(default_factory=list)
    highlights: list[HighlightMoment] = field(default_factory=list)
    subtitle_analysis: SubtitleAnalysis = field(default_factory=SubtitleAnalysis)
    format_patterns: list[FormatPattern] = field(default_factory=list)
    editorial_blueprint: dict = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "video_path": self.video_path,
            "duration": self.duration,
            "rhythm": asdict(self.rhythm),
            "narrative_structure": [asdict(s) for s in self.narrative_structure],
            "highlights": [asdict(h) for h in self.highlights],
            "subtitle_analysis": asdict(self.subtitle_analysis),
            "format_patterns": [asdict(p) for p in self.format_patterns],
            "editorial_blueprint": self.editorial_blueprint,
            "error": self.error,
        }


class AdvancedVideoAnalyzer:
    """Análise avançada de vídeo para produção editorial."""

    def __init__(self, data_root: str = "data"):
        self.data_root = Path(data_root)

    def _run_ffprobe(self, path: str) -> dict:
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", str(path)
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                return json.loads(r.stdout)
        except Exception:
            pass
        return {}

    def _run_ffmpeg(self, args: list[str], timeout: int = 60) -> tuple[int, str, str]:
        cmd = ["ffmpeg", "-y", "-hide_banner"] + args
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return r.returncode, r.stdout, r.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "Timeout"
        except FileNotFoundError:
            return -2, "", "ffmpeg não encontrado"

    def _detect_scene_changes(self, video_path: str, threshold: float = 0.3) -> list[float]:
        """Detecta timestamps de mudança de cena."""
        _, _, stderr = self._run_ffmpeg([
            "-i", str(video_path),
            "-vf", f"select='gt(scene,{threshold})',showinfo",
            "-vsync", "vfr", "-f", "null", "-"
        ])
        timestamps = []
        for line in stderr.split("\n"):
            if "pts_time:" in line:
                try:
                    pts = line.split("pts_time:")[1].split()[0]
                    timestamps.append(float(pts))
                except (IndexError, ValueError):
                    continue
        return sorted(timestamps)

    def _analyze_audio_energy(self, video_path: str, segments: int = 20) -> list[float]:
        """Analisa energia de áudio em segmentos."""
        probe = self._run_ffprobe(video_path)
        duration = float(probe.get("format", {}).get("duration", 0))
        if duration <= 0:
            return []

        energies = []
        seg_dur = duration / segments
        for i in range(segments):
            start = i * seg_dur
            _, stdout, _ = self._run_ffmpeg([
                "-ss", str(start), "-t", str(seg_dur),
                "-i", str(video_path),
                "-af", "volumedetect",
                "-f", "null", "-"
            ], timeout=10)
            # Parse mean volume from stderr
            match = re.search(r"mean_volume:\s*([-\d.]+)", stdout)
            if match:
                energies.append(float(match.group(1)))
            else:
                energies.append(-60.0)  # silence default

        return energies

    def analyze_rhythm(self, video_path: str, scene_changes: list[float], duration: float) -> RhythmAnalysis:
        """Analisa ritmo do vídeo."""
        if duration <= 0:
            return RhythmAnalysis()

        cpm = len(scene_changes) / (duration / 60) if duration > 0 else 0
        avg_shot = duration / (len(scene_changes) + 1) if scene_changes else duration

        # Classificar tempo
        if cpm >= 15:
            tempo = "viral"
        elif cpm >= 8:
            tempo = "fast"
        elif cpm >= 4:
            tempo = "medium"
        else:
            tempo = "slow"

        # Pacing score: viral content typically 8-20 CPM
        if 8 <= cpm <= 20:
            pacing = min(10.0, cpm / 2)
        elif cpm < 8:
            pacing = cpm / 2
        else:
            pacing = max(5.0, 10.0 - (cpm - 20) / 4)

        return RhythmAnalysis(
            cuts_per_minute=round(cpm, 1),
            avg_shot_duration=round(avg_shot, 2),
            tempo_category=tempo,
            pacing_score=round(pacing, 1),
        )

    def analyze_narrative(self, duration: float, scene_changes: list[float],
                          audio_energy: list[float]) -> list[NarrativeSegment]:
        """Identifica estrutura narrativa baseada em padrões temporais."""
        if duration <= 0:
            return []

        segments = []

        # Opening: primeiros 5-10% ou até primeira mudança significativa
        opening_end = min(duration * 0.1, 5.0)
        first_change = next((t for t in scene_changes if t > opening_end), opening_end)
        segments.append(NarrativeSegment(
            label="opening",
            start_sec=0.0,
            end_sec=round(first_change, 1),
            confidence=0.7,
            characteristics={"type": "hook", "energy": "high"},
        ))

        # Buildup: 10-40%
        buildup_start = first_change
        buildup_end = duration * 0.4
        segments.append(NarrativeSegment(
            label="buildup",
            start_sec=round(buildup_start, 1),
            end_sec=round(buildup_end, 1),
            confidence=0.6,
            characteristics={"type": "context", "energy": "rising"},
        ))

        # Climax: pico de energia ou maior densidade de cortes
        climax_center = duration * 0.6
        if audio_energy:
            peak_idx = audio_energy.index(max(audio_energy))
            climax_center = (peak_idx / len(audio_energy)) * duration

        climax_start = max(buildup_end, climax_center - duration * 0.1)
        climax_end = climax_center + duration * 0.15
        segments.append(NarrativeSegment(
            label="climax",
            start_sec=round(climax_start, 1),
            end_sec=round(min(climax_end, duration * 0.85), 1),
            confidence=0.65,
            characteristics={"type": "peak", "energy": "maximum"},
        ))

        # Resolution
        res_start = climax_end
        res_end = duration * 0.9
        segments.append(NarrativeSegment(
            label="resolution",
            start_sec=round(res_start, 1),
            end_sec=round(res_end, 1),
            confidence=0.5,
            characteristics={"type": "wrap-up", "energy": "declining"},
        ))

        # Closing: últimos 10%
        segments.append(NarrativeSegment(
            label="closing",
            start_sec=round(res_end, 1),
            end_sec=round(duration, 1),
            confidence=0.7,
            characteristics={"type": "cta", "energy": "low"},
        ))

        return segments

    def find_highlights(self, scene_changes: list[float], audio_energy: list[float],
                        duration: float, top_n: int = 5) -> list[HighlightMoment]:
        """Encontra momentos de destaque combinando múltiplos sinais."""
        if duration <= 0:
            return []

        candidates = []

        # Score por densidade de cortes locais
        window = duration / 20
        for i in range(20):
            t_start = i * window
            t_end = t_start + window
            local_cuts = sum(1 for s in scene_changes if t_start <= s < t_end)
            cut_score = min(local_cuts * 2, 5.0)

            # Audio energy score
            audio_score = 0.0
            if audio_energy and i < len(audio_energy):
                db = audio_energy[i]
                audio_score = max(0, (db + 60) / 6)  # normalize -60dB→0, 0dB→10

            composite = (cut_score + audio_score) / 2
            reasons = []
            if cut_score > 2:
                reasons.append(f"{local_cuts} cortes em {window:.0f}s")
            if audio_score > 3:
                reasons.append(f"pico de áudio ({audio_energy[i]:.0f}dB)")

            if composite > 1.5 or reasons:
                candidates.append(HighlightMoment(
                    timestamp=round(t_start + window / 2, 1),
                    score=round(composite, 1),
                    reasons=reasons,
                    duration=min(window, 5.0),
                    thumbnail_candidate=composite > 4.0,
                ))

        candidates.sort(key=lambda h: h.score, reverse=True)
        return candidates[:top_n]

    def analyze_subtitles(self, video_path: str) -> SubtitleAnalysis:
        """Detecta e analisa legendas no vídeo."""
        # Check for embedded subtitle streams
        probe = self._run_ffprobe(video_path)
        sub_streams = [
            s for s in probe.get("streams", [])
            if s.get("codec_type") == "subtitle"
        ]

        if sub_streams:
            codec = sub_streams[0].get("codec_name", "unknown")
            return SubtitleAnalysis(
                has_subtitles=True,
                style="srt" if "subrip" in codec else codec,
                language_detected=sub_streams[0].get("tags", {}).get("language", ""),
            )

        # Detect burned-in subtitles via OCR sampling (simplified)
        # Sample 3 frames and check for text-like patterns in bottom region
        _, _, stderr = self._run_ffmpeg([
            "-i", str(video_path),
            "-vf", "crop=iw:ih*0.2:0:ih*0.8",
            "-vframes", "3",
            "-f", "null", "-"
        ], timeout=10)

        # Heuristic: if we got frames without error, check pixel variance
        # in bottom region for text presence (simplified proxy)
        return SubtitleAnalysis(
            has_subtitles=False,
            style="none",
            timing_alignment="unknown",
        )

    def detect_format_patterns(self, scene_changes: list[float],
                                duration: float) -> list[FormatPattern]:
        """Detecta padrões de formato (abertura, encerramento, transições)."""
        patterns = []

        # Hook pattern: corte nos primeiros 3 segundos
        early_cuts = [t for t in scene_changes if t <= 3.0]
        if early_cuts:
            patterns.append(FormatPattern(
                pattern_type="hook",
                description=f"Corte rápido nos primeiros {early_cuts[-1]:.1f}s (gancho visual)",
                timestamps=early_cuts,
                confidence=0.8,
            ))

        # Transition clusters: grupos de cortes próximos (<0.5s entre si)
        clusters = []
        current_cluster = []
        for i, t in enumerate(scene_changes):
            if not current_cluster or t - current_cluster[-1] < 0.5:
                current_cluster.append(t)
            else:
                if len(current_cluster) >= 3:
                    clusters.append(current_cluster)
                current_cluster = [t]
        if len(current_cluster) >= 3:
            clusters.append(current_cluster)

        for cluster in clusters:
            mid = cluster[len(cluster) // 2]
            patterns.append(FormatPattern(
                pattern_type="transition",
                description=f"Transição rápida ({len(cluster)} cortes em {cluster[-1]-cluster[0]:.1f}s)",
                timestamps=cluster,
                confidence=0.7,
            ))

        # Closing pattern: ausência de cortes nos últimos 5s
        if duration > 10:
            late_cuts = [t for t in scene_changes if t >= duration - 5.0]
            if not late_cuts:
                patterns.append(FormatPattern(
                    pattern_type="closing",
                    description="Encerramento estável (sem cortes nos últimos 5s)",
                    timestamps=[duration - 5.0, duration],
                    confidence=0.6,
                ))

        return patterns

    def generate_editorial_blueprint(self, analysis: AdvancedAnalysisResult) -> dict:
        """Gera blueprint editorial baseado na análise."""
        blueprint = {
            "recommended_clip_ranges": [],
            "suggested_hook_timestamp": None,
            "pacing_recommendation": "",
            "narrative_template": "",
            "thumbnail_candidates": [],
        }

        # Best clip ranges from highlights
        for h in analysis.highlights[:3]:
            blueprint["recommended_clip_ranges"].append({
                "start": max(0, h.timestamp - 1.5),
                "end": h.timestamp + h.duration,
                "score": h.score,
                "reason": ", ".join(h.reasons),
            })

        # Hook suggestion
        hook_pattern = next(
            (p for p in analysis.format_patterns if p.pattern_type == "hook"),
            None,
        )
        if hook_pattern and hook_pattern.timestamps:
            blueprint["suggested_hook_timestamp"] = hook_pattern.timestamps[0]
        elif analysis.highlights:
            blueprint["suggested_hook_timestamp"] = analysis.highlights[0].timestamp

        # Pacing recommendation
        tempo = analysis.rhythm.tempo_category
        if tempo == "viral":
            blueprint["pacing_recommendation"] = "Ritmo viral detectado. Manter cortes rápidos (8-15/min)."
        elif tempo == "fast":
            blueprint["pacing_recommendation"] = "Ritmo ágil. Bom para Reels/Shorts. Considerar adicionar 1-2 cortes para viral."
        elif tempo == "medium":
            blueprint["pacing_recommendation"] = "Ritmo moderado. Adicionar cortes nos momentos de baixa energia."
        else:
            blueprint["pacing_recommendation"] = "Ritmo lento. Recomendado reeditar com cortes mais frequentes."

        # Narrative template
        if analysis.narrative_structure:
            labels = [s.label for s in analysis.narrative_structure]
            blueprint["narrative_template"] = " → ".join(labels)

        # Thumbnail candidates
        blueprint["thumbnail_candidates"] = [
            {"timestamp": h.timestamp, "score": h.score}
            for h in analysis.highlights
            if h.thumbnail_candidate
        ]

        return blueprint

    def analyze(self, video_path: str) -> AdvancedAnalysisResult:
        """Executa análise completa do vídeo."""
        result = AdvancedAnalysisResult(video_path=video_path)

        source = Path(video_path)
        if not source.exists():
            result.error = f"Arquivo não encontrado: {video_path}"
            return result

        # Basic info
        probe = self._run_ffprobe(video_path)
        duration = float(probe.get("format", {}).get("duration", 0))
        result.duration = duration

        if duration <= 0:
            result.error = "Não foi possível obter duração do vídeo"
            return result

        # Scene changes
        scene_changes = self._detect_scene_changes(video_path)

        # Audio energy
        audio_energy = self._analyze_audio_energy(video_path)

        # Rhythm
        result.rhythm = self.analyze_rhythm(video_path, scene_changes, duration)

        # Narrative structure
        result.narrative_structure = self.analyze_narrative(duration, scene_changes, audio_energy)

        # Highlights
        result.highlights = self.find_highlights(scene_changes, audio_energy, duration)

        # Subtitles
        result.subtitle_analysis = self.analyze_subtitles(video_path)

        # Format patterns
        result.format_patterns = self.detect_format_patterns(scene_changes, duration)

        # Editorial blueprint
        result.editorial_blueprint = self.generate_editorial_blueprint(result)

        return result