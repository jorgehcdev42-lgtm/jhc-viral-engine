#!/usr/bin/env python3
"""Demo E2E — Catálogo → Seleção → Produção → Validação → Agendamento."""
import sys, json, time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from src.production.pipeline import ProductionPipeline

pipeline = ProductionPipeline(data_root=str(BASE / "data"))

# Reset stuck jobs
jobs_file = BASE / "data" / "production_pipeline" / "production_jobs.json"
if jobs_file.exists():
    d = json.loads(jobs_file.read_text())
    for k, v in d.items():
        if v.get("status") == "producing":
            v["status"] = "failed"
            v["error"] = "Render interrompido"
    jobs_file.write_text(json.dumps(d, indent=2, ensure_ascii=False))
    print("[OK] Jobs travados resetados")

# Create job with auto-select
print("\n>>> Criando job com auto-seleção do SmartCatalog...")
job = pipeline.create_job(
    platform="tiktok",
    market="br",
    title="GTA 6 LEONIDA E2E DEMO M034.1",
    subtitle_text="O HYPE É REAL!",
    auto_select=True,
)
print(f"Job ID: {job.job_id}")
print(f"Status: {job.status}")
print(f"Material: {job.materials_used}")
print(f"Video: {job.video_path}")

if job.status == "failed":
    print(f"ERRO na seleção: {job.error}")
    sys.exit(1)

# Execute production
print("\n>>> Executando produção (semáforo de render)...")
start = time.time()
result = pipeline.execute_job(job.job_id)
elapsed = time.time() - start
print(f"Status final: {result.status}")
print(f"Tempo: {elapsed:.1f}s")
print(f"Output: {result.output_path}")
print(f"Quality Score: {result.quality_score:.1f}")
print(f"Quality Passed: {result.quality_passed}")
if result.error:
    print(f"Erro: {result.error}")

if result.status != "completed":
    print("\n>>> E2E FALHOU NA PRODUÇÃO")
    sys.exit(1)

# Validate output exists
output_path = Path(result.output_path)
if not output_path.exists():
    print(f"\n>>> ERRO: Output não existe: {result.output_path}")
    sys.exit(1)
size_mb = output_path.stat().st_size / 1024 / 1024
print(f"Output size: {size_mb:.1f}MB")

# Schedule internally
print("\n>>> Agendando internamente (AutoPublishScheduler)...")
sched = pipeline.schedule_job(job.job_id)
print(f"Schedule result: {json.dumps(sched, indent=2)}")

# Verify persistence
print("\n>>> Verificando persistência...")
stats = pipeline.get_stats()
print(f"Pipeline stats: {json.dumps(stats, indent=2)}")

jobs = pipeline.list_jobs(limit=5)
print(f"\nJobs na fila ({len(jobs)}):")
for j in jobs:
    mats = j.get("materials_used", [])
    mat_str = mats[0] if mats else "manual"
    print(f"  [{j['status']:10s}] {j['job_id']} | {j['platform']} | {mat_str}")

print("\n>>> ✅ E2E DEMO CONCLUÍDO COM SUCESSO")
print(f">>> Vídeo: {result.output_path}")
print(f">>> Scheduler Job: {sched.get('job_id', 'N/A')}")