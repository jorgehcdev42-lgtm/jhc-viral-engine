"""Story Studio — MISSÃO 016 (Histórias Animadas).

Gera vídeos narrativos curtos a partir de roteiros estruturados:
- Cenas sequenciais com transições configuráveis
- Texto animado (legendas, títulos, callouts)
- Narração via TTS ou áudio externo
- Backgrounds estáticos ou em movimento (Ken Burns)
- Exportação otimizada para Reels/Shorts/TikTok
- Presets de estilo (dramático, educativo, humor, news)

Uso:
    studio = StoryStudio(data_root)
    story = studio.create_story(script_path="/path/to/script.json")
    output = studio.render(story, platform="reels")
"""

import json
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class StoryScene:
    """Uma cena individual da história."""
    id: str
    duration_sec: float
    text: str  # texto exibido na tela
    narration: str  # texto para TTS (pode ser diferente do texto visual)
    background_type: str  # "solid", "image", "video", "gradient"
    background_value: str  # cor hex, path de imagem/vídeo, ou gradiente CSS-like
    text_style: dict[str, Any] = field(default_factory=dict)
    transition_in: str = "fade"  # fade, slide_left, slide_up, zoom, cut
    transition_out: str = "fade"
    motion: str = "none"  # none, ken_burns_in, ken_burns_out, pan_left, pan_right


@dataclass
class StoryScript:
    """Roteiro completo de uma história animada."""
    title: str
    scenes: list[StoryScene]
    style_preset: str = "default"  # default, dramatic, educational, humor, news
    aspect_ratio: str = "9:16"  # 9:16, 16:9, 1:1
    fps: int = 30
    audio_track: str = ""  # path opcional de música de fundo
    tts_voice: str = "default"
    tts_speed: float = 1.0
    total_duration_sec: float = 0.0  # calculado automaticamente


@dataclass
class StoryRenderResult:
    """Resultado da renderização de uma história."""
    output_path: str
    duration_sec: float
    scene_count: int
    resolution: tuple[int, int]
    file_size_mb: float
    platform: str
    render_time_sec: float
    scenes_rendered: list[dict[str, Any]] = field(default_factory=list)


STYLE_PRESETS = {
    "default": {
        "font_size": 48,
        "font_color": "#FFFFFF",
        "bg_color": "#1a1a2e",
        "text_shadow": True,
        "transition_duration": 0.5,
    },
    "dramatic": {
        "font_size": 56,
        "font_color": "#FF4444",
        "bg_color": "#0a0a0a",
        "text_shadow": True,
        "transition_duration": 0.8,
    },
    "educational": {
        "font_size": 42,
        "font_color": "#FFFFFF",
        "bg_color": "#16213e",
        "text_shadow": False,
        "transition_duration": 0.3,
    },
    "humor": {
        "font_size": 52,
        "font_color": "#FFD700",
        "bg_color": "#2d1b69",
        "text_shadow": True,
        "transition_duration": 0.4,
    },
    "news": {
        "font_size": 44,
        "font_color": "#FFFFFF",
        "bg_color": "#0f3460",
        "text_shadow": False,
        "transition_duration": 0.2,
    },
}

RESOLUTION_MAP = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}


class StoryStudio:
    """Estúdio de geração de histórias animadas."""

    def __init__(self, data_root: Path | str):
        self.data_root = Path(data_root)
        self.stories_dir = self.data_root / "stories"
        self.stories_dir.mkdir(parents=True, exist_ok=True)
        self.scripts_dir = self.data_root / "scripts"
        self.scripts_dir.mkdir(parents=True, exist_ok=True)

    def create_story(
        self,
        script: dict | StoryScript | None = None,
        script_path: str | Path | None = None,
    ) -> StoryScript:
        """Cria um roteiro de história a partir de dict, objeto ou arquivo JSON."""
        if script_path:
            p = Path(script_path)
            if not p.exists():
                raise FileNotFoundError(f"Script não encontrado: {p}")
            data = json.loads(p.read_text(encoding="utf-8"))
            return self._dict_to_script(data)

        if isinstance(script, StoryScript):
            story = script
        elif isinstance(script, dict):
            story = self._dict_to_script(script)
        else:
            raise ValueError("Forneça script (dict/StoryScript) ou script_path")

        # Calcula duração total
        story.total_duration_sec = sum(s.duration_sec for s in story.scenes)
        return story

    def save_script(self, story: StoryScript, name: str | None = None) -> Path:
        """Salva roteiro como JSON."""
        stem = name or story.title.lower().replace(" ", "_")[:50]
        out = self.scripts_dir / f"{stem}.json"
        out.write_text(
            json.dumps(asdict(story), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return out

    def render(
        self,
        story: StoryScript,
        platform: str = "reels",
        output_name: str | None = None,
    ) -> StoryRenderResult:
        """Renderiza a história como vídeo MP4."""
        import time
        start_time = time.time()

        width, height = RESOLUTION_MAP.get(story.aspect_ratio, (1080, 1920))
        preset = STYLE_PRESETS.get(story.style_preset, STYLE_PRESETS["default"])

        stem = output_name or story.title.lower().replace(" ", "_")[:50]
        output_path = self.stories_dir / f"{stem}_{platform}.mp4"

        with tempfile.TemporaryDirectory() as tmpdir:
            # Renderiza cada cena como segmento individual
            segment_paths = []
            scenes_info = []

            for i, scene in enumerate(story.scenes):
                seg_path = f"{tmpdir}/scene_{i:03d}.mp4"
                self._render_scene(
                    scene, seg_path, width, height,
                    story.fps, preset, tmpdir,
                )
                segment_paths.append(seg_path)
                scenes_info.append({
                    "id": scene.id,
                    "duration": scene.duration_sec,
                    "text_preview": scene.text[:80],
                })

            # Concatena segmentos
            concat_file = f"{tmpdir}/concat.txt"
            with open(concat_file, "w") as f:
                for sp in segment_paths:
                    f.write(f"file '{sp}'\n")

            # Adiciona áudio de fundo se existir
            audio_args = []
            if story.audio_track and Path(story.audio_track).exists():
                audio_args = [
                    "-i", story.audio_track,
                    "-filter_complex",
                    "[0:a]volume=0.3[bg];[bg]apad[bgpad]",
                    "-map", "0:v", "-map", "[bgpad]",
                    "-shortest",
                ]

            cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", concat_file,
                *audio_args,
                "-c:v", "libx264", "-preset", "fast",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                str(output_path),
            ]

            try:
                result = subprocess.run(cmd, capture_output=True, timeout=300)
                if result.returncode != 0:
                    raise RuntimeError(
                        f"ffmpeg concat failed: {result.stderr[-500:]}"
                    )
            except subprocess.TimeoutExpired:
                raise RuntimeError("Render timeout (>300s)")
            except FileNotFoundError:
                raise RuntimeError("ffmpeg not found")

        render_time = time.time() - start_time
        file_size = output_path.stat().st_size / (1024 * 1024) if output_path.exists() else 0

        return StoryRenderResult(
            output_path=str(output_path),
            duration_sec=round(story.total_duration_sec, 2),
            scene_count=len(story.scenes),
            resolution=(width, height),
            file_size_mb=round(file_size, 2),
            platform=platform,
            render_time_sec=round(render_time, 2),
            scenes_rendered=scenes_info,
        )

    def list_stories(self) -> list[dict]:
        """Lista todas as histórias renderizadas."""
        results = []
        for f in sorted(self.stories_dir.glob("*.mp4")):
            size_mb = f.stat().st_size / (1024 * 1024)
            dur = self._get_duration(f)
            results.append({
                "file": str(f),
                "name": f.stem,
                "size_mb": round(size_mb, 2),
                "duration_sec": round(dur, 2),
            })
        return results

    def list_scripts(self) -> list[dict]:
        """Lista todos os roteiros salvos."""
        results = []
        for f in sorted(self.scripts_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                results.append({
                    "file": str(f),
                    "title": data.get("title", f.stem),
                    "scenes": len(data.get("scenes", [])),
                    "style": data.get("style_preset", "default"),
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return results

    # --- Métodos internos ---

    def _dict_to_script(self, data: dict) -> StoryScript:
        """Converte dict para StoryScript."""
        scenes = []
        for s in data.get("scenes", []):
            scenes.append(StoryScene(
                id=s.get("id", f"scene_{len(scenes)}"),
                duration_sec=float(s.get("duration_sec", 3)),
                text=s.get("text", ""),
                narration=s.get("narration", s.get("text", "")),
                background_type=s.get("background_type", "solid"),
                background_value=s.get("background_value", "#1a1a2e"),
                text_style=s.get("text_style", {}),
                transition_in=s.get("transition_in", "fade"),
                transition_out=s.get("transition_out", "fade"),
                motion=s.get("motion", "none"),
            ))

        return StoryScript(
            title=data.get("title", "Untitled Story"),
            scenes=scenes,
            style_preset=data.get("style_preset", "default"),
            aspect_ratio=data.get("aspect_ratio", "9:16"),
            fps=int(data.get("fps", 30)),
            audio_track=data.get("audio_track", ""),
            tts_voice=data.get("tts_voice", "default"),
            tts_speed=float(data.get("tts_speed", 1.0)),
        )

    def _render_scene(
        self,
        scene: StoryScene,
        output_path: str,
        width: int,
        height: int,
        fps: int,
        preset: dict,
        tmpdir: str,
    ) -> bool:
        """Renderiza uma única cena como segmento de vídeo."""
        frames = int(scene.duration_sec * fps)
        if frames < 1:
            frames = fps  # mínimo 1 segundo

        # Determina cor de fundo
        bg_color = preset.get("bg_color", "#1a1a2e")
        if scene.background_type == "solid" and scene.background_value.startswith("#"):
            bg_color = scene.background_value

        # Converte hex para formato ffmpeg (0xRRGGBB → 0xBBGGRR)
        hex_clean = bg_color.lstrip("#")
        if len(hex_clean) == 6:
            r, g, b = hex_clean[0:2], hex_clean[2:4], hex_clean[4:6]
            ffmpeg_color = f"0x{b}{g}{r}"
        else:
            ffmpeg_color = "0x2e1a1a"

        # Fonte e tamanho
        font_size = scene.text_style.get("font_size", preset.get("font_size", 48))
        font_color = scene.text_style.get("font_color", preset.get("font_color", "#FFFFFF"))

        # Escapa texto para filtro drawtext do ffmpeg
        safe_text = (
            scene.text
            .replace("'", "’")
            .replace(":", "\\:")
            .replace("\\", "\\\\")
            .replace("%", "%%")
        )

        # Constrói filtro de vídeo
        vf_parts = [f"color=c={ffmpeg_color}:s={width}x{height}:d={scene.duration_sec}:r={fps}"]

        # Ken Burns effect
        if scene.motion == "ken_burns_in":
            vf_parts.append(
                f"zoompan=z='min(zoom+0.001,1.2)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":d={frames}:s={width}x{height}:fps={fps}"
            )
        elif scene.motion == "ken_burns_out":
            vf_parts.append(
                f"zoompan=z='if(eq(on,1),1.2,max(zoom-0.001,1.0))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":d={frames}:s={width}x{height}:fps={fps}"
            )

        # Texto centralizado com word wrap aproximado
        max_chars = width // (font_size // 2)
        lines = []
        words = safe_text.split()
        current_line = ""
        for word in words:
            if len(current_line) + len(word) + 1 <= max_chars:
                current_line += (" " if current_line else "") + word
            else:
                lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)

        wrapped_text = "\n".join(lines[:6])  # máximo 6 linhas

        # Drawtext filter
        shadow = ""
        if preset.get("text_shadow"):
            shadow = ":shadowx=3:shadowy=3:shadowcolor=black"

        drawtext = (
            f"drawtext=text='{wrapped_text}'"
            f":fontsize={font_size}"
            f":fontcolor={font_color}"
            f":x=(w-text_w)/2:y=(h-text_h)/2"
            f"{shadow}"
        )
        vf_parts.append(drawtext)

        # Transição de entrada (fade in)
        trans_dur = preset.get("transition_duration", 0.5)
        if scene.transition_in == "fade":
            vf_parts.append(f"fade=t=in:st=0:d={trans_dur}")
        if scene.transition_out == "fade":
            vf_parts.append(
                f"fade=t=out:st={scene.duration_sec - trans_dur}:d={trans_dur}"
            )

        vf = ",".join(vf_parts)

        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", vf,
            "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            "-t", str(scene.duration_sec),
            output_path,
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, timeout=60)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

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