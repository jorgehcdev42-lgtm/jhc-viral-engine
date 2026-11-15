"""Thumbnail Factory 2.0 — Geração automática de 3 alternativas por vídeo.

Gera 3 thumbnails distintas a partir do mesmo vídeo:
1. Frame mais dinâmico (maior variação de cor/movimento)
2. Frame com rosto/pessoa detectada (se disponível) ou segundo melhor frame
3. Frame com composição editorial (texto + gradiente + identidade visual)

Permite preview, escolha de capa, edição de título, exportação e
associação da thumbnail ao job de publicação.
"""

import os
import json
import time
import subprocess
import hashlib
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

@dataclass
class ThumbnailVariant:
    variant_id: str
    label: str
    path: str
    timestamp_sec: float = 0.0
    score: float = 0.0
    width: int = 0
    height: int = 0
    size_kb: float = 0.0
    created_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ThumbnailJob:
    job_id: str
    video_path: str
    market: str = "br"
    title: str = ""
    variants: list[ThumbnailVariant] = field(default_factory=list)
    selected_variant: Optional[str] = None
    exported_path: Optional[str] = None
    associated_job_id: Optional[str] = None
    status: str = "pending"
    error: Optional[str] = None
    created_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "variants": [v.to_dict() for v in self.variants],
        }


MARKET_THUMB_STYLES = {
    "br": {
        "title_color": "#FFD700",
        "bg_gradient_start": "#1a0a2e",
        "bg_gradient_end": "#2d1b69",
        "accent_color": "#f5576c",
        "font_size": 48,
        "border_color": "#FFD700",
    },
    "global": {
        "title_color": "#00BFFF",
        "bg_gradient_start": "#0a1628",
        "bg_gradient_end": "#1b3a5c",
        "accent_color": "#667eea",
        "font_size": 44,
        "border_color": "#00BFFF",
    },
}


class ThumbnailFactory:
    """Gera 3 alternativas de thumbnail por vídeo com identidade BR/Global."""

    def __init__(self, data_root: str = "data"):
        self.data_root = Path(data_root)
        self.output_dir = self.data_root / "thumbnails" / "factory"
        self.export_dir = self.data_root / "thumbnails" / "exported"
        self.jobs_dir = self.data_root / "thumbnails" / "jobs"

        for d in [self.output_dir, self.export_dir, self.jobs_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def _run_ffmpeg(self, args: list[str], timeout: int = 30) -> tuple[int, str, str]:
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + args
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return r.returncode, r.stdout, r.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "Timeout"
        except FileNotFoundError:
            return -2, "", "ffmpeg não encontrado"

    def _extract_frame(self, video_path: str, timestamp: float, output_path: str) -> bool:
        rc, _, _ = self._run_ffmpeg([
            "-ss", str(timestamp),
            "-i", str(video_path),
            "-vframes", "1",
            "-q:v", "2",
            str(output_path),
        ])
        return rc == 0 and Path(output_path).exists()

    def _get_video_duration(self, video_path: str) -> float:
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", str(video_path),
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                data = json.loads(r.stdout)
                return float(data.get("format", {}).get("duration", 0))
        except Exception:
            pass
        return 0.0

    def _score_frame(self, image_path: str) -> float:
        """Score baseado em variação de cor (proxy para dinamismo visual)."""
        try:
            from PIL import Image
            img = Image.open(image_path)
            pixels = list(img.getdata())
            if not pixels:
                return 0.0

            # Variância simples dos canais RGB
            r_vals = [p[0] for p in pixels[:10000]]
            g_vals = [p[1] for p in pixels[:10000]]
            b_vals = [p[2] for p in pixels[:10000]]

            def variance(vals):
                if not vals:
                    return 0
                mean = sum(vals) / len(vals)
                return sum((x - mean) ** 2 for x in vals) / len(vals)

            score = (variance(r_vals) + variance(g_vals) + variance(b_vals)) / 3
            return min(score / 1000, 10.0)  # Normaliza para 0-10
        except Exception:
            return 0.0

    def _apply_editorial_overlay(
        self, input_path: str, output_path: str,
        title: str, market: str
    ) -> bool:
        """Aplica overlay editorial com gradiente e título na thumbnail."""
        style = MARKET_THUMB_STYLES.get(market, MARKET_THUMB_STYLES["br"])

        safe_title = title.replace("'", "\\'").replace(":", "\\:")[:60]
        if not safe_title:
            safe_title = "GTA VI Leonida"

        # Gradiente inferior + texto com borda
        vf = (
            f"drawbox=x=0:y=ih*0.6:w=iw:h=ih*0.4:color=black@0.6:t=fill,"
            f"drawtext=text='{safe_title}'"
            f":fontsize={style['font_size']}"
            f":fontcolor={style['title_color']}"
            f":borderw=3:bordercolor={style['border_color']}"
            f":x=(w-text_w)/2:y=h-th-30"
        )

        rc, _, _ = self._run_ffmpeg([
            "-i", str(input_path),
            "-vf", vf,
            "-q:v", "2",
            str(output_path),
        ], timeout=15)
        return rc == 0 and Path(output_path).exists()

    def generate_variants(
        self, video_path: str, market: str = "br",
        title: str = "", associated_job_id: str = ""
    ) -> ThumbnailJob:
        """Gera 3 variantes de thumbnail para um vídeo."""
        job_id = hashlib.md5(
            f"{video_path}{market}{time.time()}".encode()
        ).hexdigest()[:12]

        job = ThumbnailJob(
            job_id=job_id,
            video_path=video_path,
            market=market,
            title=title,
            associated_job_id=associated_job_id or None,
            created_at=time.time(),
        )

        source = Path(video_path)
        if not source.exists():
            job.status = "failed"
            job.error = f"Vídeo não encontrado: {video_path}"
            self._save_job(job)
            return job

        duration = self._get_video_duration(str(source))
        if duration <= 0:
            job.status = "failed"
            job.error = "Não foi possível obter duração do vídeo"
            self._save_job(job)
            return job

        # Timestamps candidatos para extração
        candidates = sorted(set([
            1.0,
            duration * 0.15,
            duration * 0.25,
            duration * 0.33,
            duration * 0.5,
            duration * 0.66,
            duration * 0.75,
            max(0.5, duration - 2.0),
        ]))

        # Extrair frames candidatos e pontuar
        scored_frames = []
        for ts in candidates:
            tmp_path = self.output_dir / f"{job_id}_tmp_{ts:.1f}.jpg"
            if self._extract_frame(str(source), ts, str(tmp_path)):
                score = self._score_frame(str(tmp_path))
                scored_frames.append((ts, score, tmp_path))

        scored_frames.sort(key=lambda x: x[1], reverse=True)

        if len(scored_frames) < 2:
            job.status = "failed"
            job.error = "Frames insuficientes extraídos"
            self._save_job(job)
            return job

        # Variante 1: Frame mais dinâmico
        best_ts, best_score, best_tmp = scored_frames[0]
        v1_path = self.output_dir / f"{job_id}_v1_dynamic.jpg"
        if best_tmp.exists():
            best_tmp.rename(v1_path)
        job.variants.append(ThumbnailVariant(
            variant_id=f"{job_id}_v1",
            label="🔥 Mais Dinâmico",
            path=str(v1_path),
            timestamp_sec=best_ts,
            score=best_score,
            created_at=time.time(),
        ))

        # Variante 2: Segundo melhor frame (ou frame médio)
        second_idx = min(1, len(scored_frames) - 1)
        sec_ts, sec_score, sec_tmp = scored_frames[second_idx]
        v2_path = self.output_dir / f"{job_id}_v2_alt.jpg"
        if sec_tmp.exists():
            sec_tmp.rename(v2_path)
        job.variants.append(ThumbnailVariant(
            variant_id=f"{job_id}_v2",
            label="🎯 Alternativa",
            path=str(v2_path),
            timestamp_sec=sec_ts,
            score=sec_score,
            created_at=time.time(),
        ))

        # Variante 3: Composição editorial com overlay
        mid_idx = min(len(scored_frames) // 2, len(scored_frames) - 1)
        _, _, mid_tmp = scored_frames[mid_idx]
        v3_path = self.output_dir / f"{job_id}_v3_editorial.jpg"
        if mid_tmp.exists():
            if self._apply_editorial_overlay(str(mid_tmp), str(v3_path), title, market):
                mid_tmp.unlink(missing_ok=True)
            else:
                mid_tmp.rename(v3_path)
        job.variants.append(ThumbnailVariant(
            variant_id=f"{job_id}_v3",
            label="🎨 Editorial",
            path=str(v3_path),
            timestamp_sec=scored_frames[mid_idx][0],
            score=scored_frames[mid_idx][1],
            created_at=time.time(),
        ))

        # Limpar temporários restantes
        for _, _, tmp in scored_frames:
            if tmp.exists():
                tmp.unlink(missing_ok=True)

        # Preencher dimensões e tamanhos
        for v in job.variants:
            p = Path(v.path)
            if p.exists():
                v.size_kb = round(p.stat().st_size / 1024, 1)
                try:
                    from PIL import Image
                    img = Image.open(str(p))
                    v.width, v.height = img.size
                except Exception:
                    pass

        # Selecionar melhor por padrão
        job.selected_variant = job.variants[0].variant_id if job.variants else None
        job.status = "done"
        self._save_job(job)
        return job

    def select_variant(self, job_id: str, variant_id: str) -> bool:
        """Seleciona qual variante usar como capa."""
        job = self._load_job(job_id)
        if not job:
            return False
        valid_ids = [v.variant_id for v in job.variants]
        if variant_id not in valid_ids:
            return False
        job.selected_variant = variant_id
        self._save_job(job)
        return True

    def export_selected(
        self, job_id: str, filename: str = ""
    ) -> Optional[str]:
        """Exporta a variante selecionada em formato compatível."""
        job = self._load_job(job_id)
        if not job or not job.selected_variant:
            return None

        selected = next(
            (v for v in job.variants if v.variant_id == job.selected_variant),
            None,
        )
        if not selected or not Path(selected.path).exists():
            return None

        if not filename:
            filename = f"{job_id}_{job.market}_thumb.jpg"

        export_path = self.export_dir / filename
        import shutil
        shutil.copy2(selected.path, str(export_path))

        job.exported_path = str(export_path)
        self._save_job(job)
        return str(export_path)

    def update_title(self, job_id: str, new_title: str) -> bool:
        """Atualiza título e regenera variante editorial."""
        job = self._load_job(job_id)
        if not job:
            return False
        job.title = new_title

        # Regenerar variante editorial (v3) se vídeo ainda existe
        if Path(job.video_path).exists():
            v3 = next((v for v in job.variants if "v3" in v.variant_id), None)
            if v3:
                duration = self._get_video_duration(job.video_path)
                ts = v3.timestamp_sec if v3.timestamp_sec > 0 else duration * 0.5
                tmp = self.output_dir / f"{job_id}_regen_tmp.jpg"
                if self._extract_frame(job.video_path, ts, str(tmp)):
                    if self._apply_editorial_overlay(str(tmp), v3.path, new_title, job.market):
                        tmp.unlink(missing_ok=True)
                    else:
                        tmp.rename(v3.path)

        self._save_job(job)
        return True

    def associate_with_job(self, job_id: str, publish_job_id: str) -> bool:
        """Associa thumbnail a um job de publicação."""
        job = self._load_job(job_id)
        if not job:
            return False
        job.associated_job_id = publish_job_id
        self._save_job(job)
        return True

    def list_jobs(self, limit: int = 20) -> list[dict]:
        """Lista jobs de thumbnail recentes."""
        results = []
        for f in sorted(self.jobs_dir.glob("*.json"), reverse=True)[:limit]:
            try:
                data = json.loads(f.read_text())
                results.append({
                    "job_id": data["job_id"],
                    "market": data.get("market", "unknown"),
                    "title": data.get("title", ""),
                    "status": data.get("status", "unknown"),
                    "variants_count": len(data.get("variants", [])),
                    "selected": data.get("selected_variant"),
                    "created_at": data.get("created_at", 0),
                })
            except Exception:
                continue
        return results

    def get_job(self, job_id: str) -> Optional[dict]:
        """Retorna detalhes completos de um job."""
        job = self._load_job(job_id)
        return job.to_dict() if job else None

    def _save_job(self, job: ThumbnailJob):
        path = self.jobs_dir / f"{job.job_id}.json"
        path.write_text(json.dumps(job.to_dict(), indent=2))

    def _load_job(self, job_id: str) -> Optional[ThumbnailJob]:
        path = self.jobs_dir / f"{job_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            variants = [ThumbnailVariant(**v) for v in data.pop("variants", [])]
            return ThumbnailJob(**data, variants=variants)
        except Exception:
            return None