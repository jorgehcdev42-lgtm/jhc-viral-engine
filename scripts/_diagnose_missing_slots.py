#!/usr/bin/env python3
"""Diagnóstico dos slots faltantes — MISSÃO 034.7.1 FASE 2."""
import json, time
from pathlib import Path

data = json.loads(Path("data/production_pipeline/production_jobs.json").read_text())
now = time.time()

print("=== JOBS RECENTES (ultimos 30min) ===")
recent_count = 0
for jid, j in sorted(data.items(), key=lambda x: x[1].get("created_at", 0)):
    created = j.get("created_at", 0)
    if created < now - 1800:
        continue
    recent_count += 1
    op = j.get("output_path", "")
    status = j.get("status", "?")
    has_file = False
    if op and Path(op).exists():
        has_file = Path(op).stat().st_size > 100000
    err = j.get("error", "")[:80]
    title = j.get("title", "?")[:40]
    print(f"  {jid} | {status:10s} | file={has_file} | {title}")
    if err:
        print(f"    ERROR: {err}")

print(f"\nTotal jobs recentes: {recent_count}")

# Verificar batch log
log_path = Path("/tmp/batch_m0347_final2.log")
if log_path.exists():
    content = log_path.read_text()
    print(f"\n=== BATCH LOG ({len(content)} bytes) ===")
    print(content[-2000:] if len(content) > 2000 else content)
else:
    print("\n=== BATCH LOG: nao encontrado ===")

# Contar materiais usados vs disponiveis
used_materials = set()
for j in data.values():
    for m in j.get("materials_used", []):
        used_materials.add(m)
    vp = j.get("video_path", "")
    if vp:
        used_materials.add(Path(vp).name)

print(f"\nMateriais ja usados em jobs: {len(used_materials)}")
print(f"Blacklist: Video 0013.mp4")