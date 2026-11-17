#!/usr/bin/env python3
"""Inventário rápido de reels novos vs demos — MISSÃO 034.7.1 FASE 2."""
import json, hashlib
from pathlib import Path

data = json.loads(Path("data/production_pipeline/production_jobs.json").read_text())
by_status = {}
for j in data.values():
    s = j.get("status", "?")
    by_status[s] = by_status.get(s, 0) + 1
print(f"Total: {len(data)} | {by_status}")

seen = set()
pub = 0
demo = 0
new_reels = []

for jid, j in sorted(data.items(), key=lambda x: x[1].get("created_at", 0)):
    op = j.get("output_path", "")
    if not op or not Path(op).exists():
        continue
    if j.get("status") not in ("completed", "scheduled"):
        continue
    h = hashlib.sha256(Path(op).read_bytes()).hexdigest()[:12]
    if h in seen:
        continue
    seen.add(h)
    t = j.get("title", "")
    is_demo = "E2E DEMO" in t.upper() or "LEONIDA DEMO" in t.upper()
    sz = Path(op).stat().st_size / (1024 * 1024)
    if is_demo:
        demo += 1
    else:
        pub += 1
    new_reels.append((jid, t, sz, j.get("scheduler_job_id", ""), is_demo))

print(f"Reels novos unicos: {pub}/10 | Demos: {demo} | Total unicos: {len(seen)}")
print()
for i, (jid, t, sz, sched, is_d) in enumerate(new_reels, 1):
    tag = "DEMO" if is_d else "NOVO"
    print(f"{i:2d}. [{tag}] {jid} | {sz:6.1f}MB | sched:{sched} | {t}")