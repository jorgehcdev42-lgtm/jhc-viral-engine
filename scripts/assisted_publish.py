#!/usr/bin/env python3
"""Publicação Assistida — Abre fluxo de upload no Safari com sessão autenticada.

NÃO publica automaticamente. Apenas:
1. Prepara metadados (título, descrição, hashtags)
2. Abre a URL correta de upload no Safari (onde o usuário já está logado)
3. Copia título/descrição para a área de transferência
4. Aguarda confirmação manual do usuário
5. Registra resultado na PublishStateMachine

Uso:
    python scripts/assisted_publish.py <job_id>              # publica job específico
    python scripts/assisted_publish.py list                   # lista jobs prontos
    python scripts/assisted_publish.py confirm <job_id> <url> # confirma publicação manual
"""

import json
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA_ROOT = BASE / "data"

PLATFORM_UPLOAD_URLS = {
    "tiktok": "https://www.tiktok.com/upload",
    "instagram": "https://www.instagram.com/",
    "youtube": "https://studio.youtube.com/channel/UC/upload",
}


def get_ready_jobs() -> list[dict]:
    """Lista jobs do pipeline prontos para publicação (status=scheduled ou completed)."""
    jobs_file = DATA_ROOT / "production_pipeline" / "production_jobs.json"
    if not jobs_file.exists():
        return []
    data = json.loads(jobs_file.read_text())
    ready = []
    for jid, job in data.items():
        if job.get("status") in ("scheduled", "completed") and job.get("output_path"):
            p = Path(job["output_path"])
            if p.exists() and p.stat().st_size > 100_000:
                ready.append(job)
    return sorted(ready, key=lambda j: j.get("created_at", 0), reverse=True)


def prepare_metadata(job: dict) -> dict:
    """Prepara título, descrição e hashtags para o job."""
    title = job.get("title", "GTA 6 Reel")
    platform = job.get("platform", "tiktok")

    # Hashtags por plataforma
    hashtags_map = {
        "tiktok": ["#gta6", "#gtavi", "#rockstargames", "#gaming", "#viral", "#fyp"],
        "instagram": ["#gta6", "#gtavi", "#rockstargames", "#gaming", "#reels"],
        "youtube": ["#gta6", "#gtavi", "#rockstargames", "#shorts"],
    }
    hashtags = hashtags_map.get(platform, hashtags_map["tiktok"])

    description = f"{title}\n\n{' '.join(hashtags)}"

    return {
        "title": title,
        "description": description,
        "hashtags": hashtags,
        "platform": platform,
        "video_path": job.get("output_path", ""),
        "job_id": job.get("job_id", ""),
    }


def open_safari_upload(meta: dict) -> bool:
    """Abre URL de upload no Safari e copia metadados para clipboard."""
    platform = meta["platform"]
    url = PLATFORM_UPLOAD_URLS.get(platform)
    if not url:
        print(f"   ❌ Plataforma desconhecida: {platform}")
        return False

    # Copiar título para clipboard
    try:
        subprocess.run(
            ["pbcopy"], input=meta["title"].encode(), check=True, timeout=5
        )
        print(f"   📋 Título copiado: {meta['title']}")
    except Exception:
        pass

    # Abrir Safari na URL de upload
    try:
        subprocess.run(
            ["open", "-a", "Safari", url], check=True, timeout=10
        )
        print(f"   🌐 Safari aberto: {url}")
        return True
    except Exception as e:
        print(f"   ❌ Erro ao abrir Safari: {e}")
        return False


def confirm_publish(job_id: str, post_url: str = "") -> dict:
    """Registra confirmação manual de publicação."""
    from src.publishing.publish_state_machine import PublishStateMachine, PublishConfirmation

    psm = PublishStateMachine(data_root=str(DATA_ROOT))

    # Verificar se job existe na state machine
    job = psm.get_job(job_id)
    if not job:
        # Criar job na state machine a partir do pipeline job
        jobs_file = DATA_ROOT / "production_pipeline" / "production_jobs.json"
        if jobs_file.exists():
            data = json.loads(jobs_file.read_text())
            pjob = data.get(job_id)
            if pjob:
                psm.create_job(
                    market=pjob.get("market", "br"),
                    platform=pjob.get("platform", "tiktok"),
                    video_path=pjob.get("output_path", ""),
                    title=pjob.get("title", ""),
                    autoreel_job_id=job_id,
                )
                # Transicionar para publishing
                psm.transition(job_id, "publishing", "manual_assisted")

    # Confirmar com proof manual
    result = psm.confirm_publish(
        job_id=job_id,
        post_id=f"manual_{int(time.time())}",
        permalink=post_url,
        verification_method="manual",
        metadata={"assisted": True, "confirmed_at": time.time()},
    )
    return result


def list_ready():
    """Lista jobs prontos para publicação assistida."""
    jobs = get_ready_jobs()
    if not jobs:
        print("   Nenhum job pronto para publicação.")
        return

    print(f"\n📦 Jobs prontos para publicação ({len(jobs)}):\n")
    for j in jobs:
        size_mb = Path(j["output_path"]).stat().st_size / (1024 * 1024)
        print(f"   [{j['status']:10s}] {j['job_id']} | {j['platform']:8s} | {size_mb:.1f}MB | {j.get('title', 'N/A')}")
    print()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "list":
        list_ready()
        return

    if cmd == "confirm":
        if len(sys.argv) < 3:
            print("   Uso: assisted_publish.py confirm <job_id> [post_url]")
            sys.exit(1)
        job_id = sys.argv[2]
        post_url = sys.argv[3] if len(sys.argv) > 3 else ""
        result = confirm_publish(job_id, post_url)
        print(f"   Resultado: {json.dumps(result, indent=2)}")
        return

    # Publicar job específico
    job_id = cmd
    jobs = get_ready_jobs()
    target = next((j for j in jobs if j["job_id"] == job_id), None)

    if not target:
        print(f"   ❌ Job não encontrado ou não pronto: {job_id}")
        print("   Use 'list' para ver jobs disponíveis.")
        sys.exit(1)

    meta = prepare_metadata(target)

    print(f"\n🚀 Publicação Assistida — {meta['platform'].upper()}")
    print(f"   Job: {meta['job_id']}")
    print(f"   Vídeo: {meta['video_path']}")
    print(f"   Título: {meta['title']}")
    print(f"   Hashtags: {' '.join(meta['hashtags'])}")
    print()

    if not open_safari_upload(meta):
        sys.exit(1)

    print()
    print("   ⚠️  INSTRUÇÕES:")
    print("   1. O vídeo está em:", meta["video_path"])
    print("   2. Arraste o vídeo para o upload no Safari")
    print("   3. Cole o título (já copiado: Cmd+V)")
    print("   4. Adicione a descrição manualmente se desejar")
    print("   5. Publique quando estiver pronto")
    print(f"   6. Confirme: python scripts/assisted_publish.py confirm {meta['job_id']} <url_do_post>")
    print()


if __name__ == "__main__":
    main()