import json, os, subprocess, time
from pathlib import Path
from datetime import datetime

BASE = Path("/Volumes/SSD EXT MACBOOK/JHC-PROJETOS/JHC VIRAL ENGINE/GTA 6")
ENTRIES = BASE / "data/bulk_import/state/download_entries.json"
PROGRESS = BASE / "data/bulk_import/state/import_progress.json"
WORKER_LOG = BASE / "data/bulk_import/logs/worker.log"

print("=" * 60)
print("MISSÃO 032.1 — PRIORIDADE 1: DIAGNÓSTICO COMPLETO")
print("=" * 60)

with open(ENTRIES) as f:
    entries = json.load(f)

print(f"\n[1] CHECKPOINT: {len(entries)} entries")
from collections import Counter
states = Counter(e.get("state") for e in entries)
for s, c in sorted(states.items()):
    print(f"  {s}: {c}")

mt = os.path.getmtime(ENTRIES)
print(f"\n[2] Checkpoint mtime: {datetime.fromtimestamp(mt).isoformat()} ({time.time() - mt:.0f}s atrás)")

print(f"\n[3] DIAGNÓSTICO DOS 3 DOWNLOADS:")
targets = ["Vídeo 0117.mp4", "Vídeo 0772.mp4", "Vídeo 0174.mp4"]
for t in targets:
    found = [e for e in entries if e.get("filename") == t]
    if not found:
        print(f"  {t}: NÃO ENCONTRADO")
        continue
    e = found[0]
    started = e.get("started_at")
    age_min = (time.time() - started) / 60 if started else None
    print(f"  {t}:")
    print(f"    state={e.get('state')} retries={e.get('retries',0)}/{e.get('max_retries',0)}")
    print(f"    size_bytes={e.get('size_bytes',0)} expected={e.get('expected_size',0)}")
    print(f"    error='{e.get('error','')}'")
    if age_min is not None:
        print(f"    started={datetime.fromtimestamp(started).isoformat()} ({age_min:.1f}min atrás)")
    fn = e.get("filename")
    for base in [BASE / "VIDEOS CORTES", Path("/Volumes/SSD EXT MACBOOK/VIDEOS CORTES")]:
        p = base / fn
        if p.exists():
            print(f"    arquivo físico: {p} ({p.stat().st_size} bytes)")

print(f"\n[4] WORKER PROCESS:")
r = subprocess.run(["ps", "aux"], capture_output=True, text=True)
procs = [l for l in r.stdout.split("\n") if "bulk_worker" in l and "grep" not in l]
print(f"  Processos ativos: {len(procs)}")
for p in procs:
    print(f"  {p[:120]}")

print(f"\n[5] LAUNCHD:")
r = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
jhc = [l for l in r.stdout.split("\n") if "jhc" in l.lower()]
for j in jhc:
    print(f"  {j}")

print(f"\n[6] SSD ESPAÇO:")
r = subprocess.run(["df", "-h", "/Volumes/SSD EXT MACBOOK"], capture_output=True, text=True)
lines = r.stdout.strip().split("\n")
if len(lines) > 1:
    parts = lines[-1].split()
    print(f"  Livre: {parts[3]} de {parts[1]}")

print(f"\n[7] WORKER LOG (últimas 20 linhas):")
if WORKER_LOG.exists():
    log_lines = WORKER_LOG.read_text().strip().split("\n")
    for line in log_lines[-20:]:
        print(f"  {line}")

print(f"\n[8] PROGRESS FILE:")
if PROGRESS.exists():
    with open(PROGRESS) as f:
        prog = json.load(f)
    print(f"  bytes_downloaded: {prog.get('bytes_downloaded', 0) / (1024**2):.1f} MB")
    print(f"  ssd_free: {prog.get('ssd_free_bytes', 0) / (1024**3):.1f} GB")
    print(f"  last_updated: {datetime.fromtimestamp(prog.get('last_updated', 0)).isoformat()}")

print(f"\n[9] WATCHDOG STALLED CHECK:")
stalled = []
for e in entries:
    if e.get("state") == "DOWNLOADING":
        st = e.get("started_at", 0)
        age_min = (time.time() - st) / 60 if st else 0
        size = e.get("size_bytes", 0)
        print(f"  {e.get('filename')}: age={age_min:.1f}min size={size}")
        if age_min > 10 and size == 0:
            stalled.append(e.get("filename"))
            print(f"    ⚠️ STALLED (>10min, 0 bytes)")
if stalled:
    print(f"  AÇÃO: resetar {stalled} para PENDING")
else:
    print(f"  ✅ Nenhum download stalled")

print("\n" + "=" * 60)