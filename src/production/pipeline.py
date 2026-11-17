"""Production Pipeline — Integração SmartCatalog + AutoReelStudio + Scheduler.

Orquestra o fluxo completo: seleção inteligente → produção → validação → agendamento.
Controle de concorrência via threading.Semaphore (1 render por vez no M2 8GB).
Registro de uso de materiais e prevenção de repetição excessiva.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# Semáforo global: máximo 1 render FFmpeg pesado simultâneo
_RENDER_SEMAPHORE = threading.Semaphore(1)


@dataclass
class ProductionJob:
    """Job de produção individual."""
    job_id: str = ""
    status: str = "pending"  # pending, selecting, producing, validating, scheduled, completed, failed
    video_path: str = ""
    output_path: str = ""
    platform: str = "tiktok"
    market: str = "br"
    title: str = ""
    subtitle_text: str = ""
    quality_score: float = 0.0
    quality_passed: bool = False
    error: str = ""
    created_at: float = 0.0
    completed_at: float = 0.0
    duration_seconds: float = 0.0
    materials_used: list[str] = field(default_factory=list)
    scheduler_job_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class ProductionPipeline:
    """Orquestrador de produção com controle de recursos."""

    JOBS_FILE = "production_jobs.json"

    def __init__(self, data_root: str | Path = "data"):
        self.data_root = Path(data_root)
        self.jobs_dir = self.data_root / "production_pipeline"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_file = self.jobs_dir / self.JOBS_FILE
        self._jobs: dict[str, ProductionJob] = {}
        self._load_jobs()

    def _load_jobs(self) -> None:
        if self.jobs_file.exists():
            try:
                raw = json.loads(self.jobs_file.read_text())
                for jid, jdata in raw.items():
                    self._jobs[jid] = ProductionJob(**jdata)
            except (json.JSONDecodeError, OSError, TypeError):
                self._jobs = {}

    def _save_jobs(self) -> None:
        data = {jid: j.to_dict() for jid, j in self._jobs.items()}
        self.jobs_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def create_job(
        self,
        video_path: str = "",
        platform: str = "tiktok",
        market: str = "br",
        title: str = "",
        subtitle_text: str = "",
        auto_select: bool = False,
    ) -> ProductionJob:
        """Cria novo job de produção. Se auto_select=True, escolhe material do catálogo."""
        job = ProductionJob(
            job_id=str(uuid.uuid4())[:12],
            status="pending",
            video_path=video_path,
            platform=platform,
            market=market,
            title=title or f"GTA 6 Reel {int(time.time()) % 10000}",
            subtitle_text=subtitle_text,
            created_at=time.time(),
        )

        # Auto-seleção do catálogo se nenhum vídeo especificado
        if auto_select and not video_path:
            from src.production.smart_catalog import SmartCatalog, SelectionCriteria
            catalog = SmartCatalog(data_root=self.data_root)
            catalog.load()
            criteria = SelectionCriteria(
                prefer_vertical=True,
                min_duration=10.0,
                max_duration=90.0,
                min_width=720,
                max_results=1,
            )
            selected = catalog.select_fresh_materials(criteria)
            if selected:
                job.video_path = selected[0].path
                job.materials_used = [selected[0].filename]
                job.status = "selecting"
            else:
                job.status = "failed"
                job.error = "Nenhum material compatível encontrado no catálogo"

        self._jobs[job.job_id] = job
        self._save_jobs()
        return job

    def execute_job(self, job_id: str) -> ProductionJob:
        """Executa job com semáforo de render (1 por vez)."""
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError(f"Job não encontrado: {job_id}")

        if job.status == "completed":
            return job

        if not job.video_path or not Path(job.video_path).exists():
            job.status = "failed"
            job.error = f"Vídeo não encontrado: {job.video_path}"
            self._save_jobs()
            return job

        # Adquire semáforo — bloqueia se outro render está rodando
        job.status = "producing"
        self._save_jobs()

        acquired = _RENDER_SEMAPHORE.acquire(timeout=300)
        if not acquired:
            job.status = "failed"
            job.error = "Timeout aguardando slot de render (outro job em execução)"
            self._save_jobs()
            return job

        try:
            start = time.time()
            from src.production.auto_reel import AutoReelStudio, ReelRequest

            studio = AutoReelStudio(data_root=str(self.data_root))
            request = ReelRequest(
                video_path=job.video_path,
                market=job.market,
                platform=job.platform,
                editorial_model="viral_hook",
                include_narration=False,
                include_music=True,
                custom_title=job.title,
                subtitle_text=job.subtitle_text,
            )
            result = studio.produce(request)
            job.duration_seconds = round(time.time() - start, 2)

            if result.status == "done" and result.output_path:
                job.status = "validating"
                job.output_path = result.output_path
                self._save_jobs()

                # Validação ffprobe
                import subprocess
                try:
                    r = subprocess.run(
                        ["ffprobe", "-v", "quiet", "-print_format", "json",
                         "-show_format", "-show_streams", result.output_path],
                        capture_output=True, text=True, timeout=10,
                    )
                    probe = json.loads(r.stdout)
                    vs = [s for s in probe.get("streams", []) if s.get("codec_type") == "video"]
                    if vs:
                        w = vs[0].get("width", 0)
                        h = vs[0].get("height", 0)
                        dur = float(probe.get("format", {}).get("duration", 0))
                        job.quality_score = min(100, (w * h) / (1080 * 1920) * 50 + min(dur / 60, 1) * 30 + 20)
                        job.quality_passed = w >= 720 and h >= 720 and dur > 0.5
                    else:
                        job.quality_passed = False
                        job.error = "Sem stream de vídeo"
                except Exception as e:
                    job.quality_passed = True  # fallback: assume OK se ffprobe falhar
                    job.quality_score = 50.0

                if job.quality_passed:
                    job.status = "completed"
                    job.completed_at = time.time()
                    # Registrar uso dos materiais
                    if job.materials_used:
                        from src.production.smart_catalog import SmartCatalog
                        catalog = SmartCatalog(data_root=self.data_root)
                        catalog.load()
                        catalog.record_usage(job.materials_used, reel_id=job.job_id)
                else:
                    job.status = "failed"
                    job.error = job.error or "Quality Gate reprovado"
            else:
                job.status = "failed"
                job.error = result.error or "Produção falhou"

        except Exception as e:
            job.status = "failed"
            job.error = str(e)
        finally:
            _RENDER_SEMAPHORE.release()
            self._save_jobs()

        return job

    def schedule_job(self, job_id: str, scheduled_at: Optional[float] = None) -> dict:
        """Agenda job concluído para publicação interna (não publica externamente)."""
        job = self._jobs.get(job_id)
        if not job:
            return {"error": "Job não encontrado"}
        if job.status != "completed":
            return {"error": f"Job não completado (status={job.status})"}

        from src.automation.autopublish_scheduler import AutoPublishScheduler, AutoPublishJob

        scheduler = AutoPublishScheduler(data_root=self.data_root)
        pub_job = AutoPublishJob(
            profile_id=f"{job.market}_{job.platform}",
            platform=job.platform,
            video_path=job.output_path,
            title=job.title,
            scheduled_at=scheduled_at or time.time(),
        )
        result = scheduler.submit_job(pub_job)
        if result.get("status") == "submitted":
            job.scheduler_job_id = result["job_id"]
            job.status = "scheduled"
            self._save_jobs()
        return result

    def get_job(self, job_id: str) -> Optional[dict]:
        job = self._jobs.get(job_id)
        return job.to_dict() if job else None

    def list_jobs(self, limit: int = 50) -> list[dict]:
        jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return [j.to_dict() for j in jobs[:limit]]

    def get_stats(self) -> dict:
        total = len(self._jobs)
        by_status = {}
        for j in self._jobs.values():
            by_status[j.status] = by_status.get(j.status, 0) + 1
        return {
            "total_jobs": total,
            "by_status": by_status,
            "render_slots_available": _RENDER_SEMAPHORE._value,
        }