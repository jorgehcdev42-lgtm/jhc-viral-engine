#!/usr/bin/env python3
"""Batch Reels Launch — Gera reels frescos para o launch day 19/11/2026.

Usa SmartCatalog + ProductionPipeline com semáforo (1 render por vez).
Gera N reels, valida cada um rigorosamente, agenda internamente.
Respeita limite de RAM do M2 8GB.

Uso:
    python scripts/batch_reels_launch.py              # gera 10 reels (default)
    python scripts/batch_reels_launch.py 20           # gera 20 reels
    python scripts/batch_reels_launch.py status       # mostra progresso
"""

import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

DATA_ROOT = BASE / "data"
BATCH_LOG = DATA_ROOT / "production_pipeline" / "batch_launch_log.json"


def get_existing_job_materials() -> set:
    """Retorna conjunto de materiais já usados em jobs existentes."""
    jobs_file = DATA_ROOT / "production_pipeline" / "production_jobs.json"
    if not jobs_file.exists():
        return set()
    data = json.loads(jobs_file.read_text())
    used = set()
    for job in data.values():
        for m in job.get("materials_used", []):
            used.add(m)
    return used


def run_batch(count: int = 10) -> dict:
    """Gera `count` reels frescos usando pipeline."""
    from src.production.smart_catalog import SmartCatalog, SelectionCriteria
    from src.production.pipeline import ProductionPipeline

    print(f"\n🚀 BATCH LAUNCH — Gerando {count} reels para 19/11")
    print(f"   Iniciado: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Carregar catálogo
    catalog = SmartCatalog(data_root=str(DATA_ROOT))
    catalog.load()
    stats = catalog.get_stats()
    print(f"   Catálogo: {stats['unused_materials']} materiais frescos disponíveis")

    # Pipeline
    pipeline = ProductionPipeline(data_root=str(DATA_ROOT))

    # Materiais já usados em jobs anteriores
    already_used = get_existing_job_materials()
    print(f"   Já processados: {len(already_used)} materiais")

    # Blacklist de materiais que falharam com black frames (HEVC incompatível com crop/scale)
    BLACKLIST_MATERIALS = {"Vídeo 0013.mp4"}
    # Adicionar materiais que falharam neste batch ou anteriores por QG rejection
    jobs_file = DATA_ROOT / "production_pipeline" / "production_jobs.json"
    if jobs_file.exists():
        try:
            jdata = json.loads(jobs_file.read_text())
            for j in jdata.values():
                if j.get("status") == "failed" and "black" in j.get("error", "").lower():
                    for m in j.get("materials_used", []):
                        BLACKLIST_MATERIALS.add(m)
                    vp = j.get("video_path", "")
                    if vp:
                        BLACKLIST_MATERIALS.add(Path(vp).name)
        except Exception:
            pass
    if BLACKLIST_MATERIALS:
        print(f"   ⛔ Blacklisted (black frames): {BLACKLIST_MATERIALS}")

    results = {"success": 0, "failed": 0, "skipped": 0, "jobs": []}
    start_time = time.time()

    for i in range(count):
        print(f"\n[{i+1}/{count}] Selecionando material fresco...")

        # Selecionar material não usado
        criteria = SelectionCriteria(
            prefer_vertical=True,
            min_duration=10.0,
            max_duration=90.0,
            min_width=720,
            max_results=5,
        )
        fresh = catalog.select_fresh_materials(criteria)

        # Filtrar materiais já processados, falhos com black frames, ou blacklisted
        unused_fresh = [m for m in fresh if m.filename not in already_used and m.filename not in BLACKLIST_MATERIALS]

        if not unused_fresh:
            print(f"   ⚠️  Sem materiais frescos restantes. Batch concluído.")
            break

        material = unused_fresh[0]
        print(f"   📹 {material.filename} ({material.width}x{material.height}, {material.duration:.1f}s)")

        # Criar job
        titles = [
            "GTA 6 TÁ CHEGANDO! 🔥",
            "O HYPE É REAL! 🎮",
            "GTA VI VAZOU? 👀",
            "FLASH BR NO GTA 6! ⚡",
            "CONTAGEM REGRESSIVA! ⏰",
            "GTA 6 GAMEPLAY LEAK! 🕹️",
            "ROCKSTAR SURPREENDENDO! 💥",
            "VICE CITY DE VOLTA! 🌴",
            "GTA 6 MULTIPLAYER? 🤝",
            "LANÇAMENTO HISTÓRICO! 🚀",
        ]
        title = titles[i % len(titles)]

        try:
            job = pipeline.create_job(
                video_path=material.path,
                platform="tiktok",
                market="br",
                title=title,
                subtitle_text="GTA 6 - 19/11/2026",
            )
            print(f"   📋 Job criado: {job.job_id}")

            # Executar (semáforo garante 1 por vez)
            print(f"   ⏳ Renderizando...")
            result = pipeline.execute_job(job.job_id)

            if result.status == "completed":
                size_mb = Path(result.output_path).stat().st_size / (1024 * 1024) if result.output_path else 0
                print(f"   ✅ Concluído! Score={result.quality_score:.0f} | {size_mb:.1f}MB | {result.duration_seconds:.0f}s")
                results["success"] += 1
                results["jobs"].append({
                    "job_id": result.job_id,
                    "material": material.filename,
                    "output": result.output_path,
                    "score": result.quality_score,
                    "size_mb": round(size_mb, 1),
                    "duration": result.duration_seconds,
                })
                already_used.add(material.filename)

                # Agendar internamente
                sched = pipeline.schedule_job(result.job_id)
                if sched.get("status") == "submitted":
                    print(f"   📅 Agendado: {sched['job_id']}")

            else:
                print(f"   ❌ Falhou: {result.error}")
                results["failed"] += 1
                results["jobs"].append({
                    "job_id": result.job_id,
                    "material": material.filename,
                    "error": result.error,
                })

        except Exception as e:
            print(f"   ❌ Erro: {e}")
            results["failed"] += 1

    elapsed = time.time() - start_time
    results["elapsed_seconds"] = round(elapsed, 1)
    results["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    # Salvar log
    BATCH_LOG.parent.mkdir(parents=True, exist_ok=True)
    existing_log = []
    if BATCH_LOG.exists():
        try:
            existing_log = json.loads(BATCH_LOG.read_text())
        except Exception:
            pass
    existing_log.append(results)
    BATCH_LOG.write_text(json.dumps(existing_log, indent=2, ensure_ascii=False))

    # Resumo
    print(f"\n{'='*60}")
    print(f"📊 BATCH CONCLUÍDO")
    print(f"   Sucesso: {results['success']}")
    print(f"   Falhas:  {results['failed']}")
    print(f"   Tempo:   {elapsed:.0f}s ({elapsed/60:.1f}min)")
    if results["success"] > 0:
        avg_time = elapsed / results["success"]
        print(f"   Média:   {avg_time:.0f}s/reel")
    print(f"{'='*60}\n")

    return results


def show_status():
    """Mostra status do batch e jobs prontos."""
    jobs_file = DATA_ROOT / "production_pipeline" / "production_jobs.json"
    if not jobs_file.exists():
        print("Nenhum job encontrado.")
        return

    data = json.loads(jobs_file.read_text())
    by_status = {}
    ready = []
    for jid, job in data.items():
        s = job.get("status", "?")
        by_status[s] = by_status.get(s, 0) + 1
        if s in ("completed", "scheduled") and job.get("output_path"):
            p = Path(job["output_path"])
            if p.exists():
                ready.append(job)

    print(f"\n📊 Status dos Jobs:")
    for s, c in sorted(by_status.items()):
        print(f"   {s:12s}: {c}")

    print(f"\n📦 Prontos para upload: {len(ready)}")
    total_mb = 0
    for j in sorted(ready, key=lambda x: x.get("created_at", 0), reverse=True)[:20]:
        size_mb = Path(j["output_path"]).stat().st_size / (1024 * 1024)
        total_mb += size_mb
        print(f"   [{j['status']:10s}] {j['job_id']} | {size_mb:6.1f}MB | {j.get('title', 'N/A')}")

    print(f"\n   Total: {total_mb:.0f}MB ({total_mb/1024:.1f}GB)")

    # Batch log
    if BATCH_LOG.exists():
        logs = json.loads(BATCH_LOG.read_text())
        if logs:
            last = logs[-1]
            print(f"\n🔄 Último batch: {last.get('completed_at', '?')}")
            print(f"   Sucesso: {last.get('success', 0)} | Falhas: {last.get('failed', 0)} | Tempo: {last.get('elapsed_seconds', 0):.0f}s")


def main():
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg == "status":
            show_status()
            return
        try:
            count = int(arg)
        except ValueError:
            print(f"❌ Argumento inválido: {arg}")
            print("   Uso: batch_reels_launch.py [N|status]")
            sys.exit(1)
    else:
        count = 10

    run_batch(count)


if __name__ == "__main__":
    main()