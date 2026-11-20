import json, os
from collections import Counter

BASE = "/Volumes/SSD EXT MACBOOK/JHC-PROJETOS/JHC VIRAL ENGINE/GTA 6"

with open(os.path.join(BASE, "data/bulk_import/state/download_entries.json")) as f:
    entries = json.load(f)

completed = [e for e in entries if e.get("state") == "COMPLETED"]
videos = sum(1 for e in completed if e.get("filename","").endswith((".mp4",".mov",".avi",".mkv",".webm")))
images = sum(1 for e in completed if e.get("filename","").endswith((".jpg",".jpeg",".png",".gif",".webp")))

print(f"=== BREAKDOWN FINAL ===")
print(f"Vídeos baixados: {videos}")
print(f"Imagens baixadas: {images}")
print(f"Total COMPLETED: {len(completed)}")

failed = [e for e in entries if e.get("state") == "FAILED"]
print(f"\n=== FAILED ({len(failed)}) ===")
for fe in failed:
    print(f"  {fe.get('filename')}: {fe.get('error','?')}")
    print(f"  URL: {fe.get('url','?')[:80]}...")
    print(f"  Retries: {fe.get('retries',0)}/{fe.get('max_retries',0)}")

dl = [e for e in entries if e.get("state") == "DOWNLOADING"]
print(f"\n=== DOWNLOADING ({len(dl)}) ===")
for d in dl:
    print(f"  {d.get('filename')}: started={d.get('started_at','?')}")

# Velocidade estimada
times = [e.get("completed_at", 0) for e in completed if e.get("completed_at")]
if len(times) >= 2:
    first_t = min(times)
    last_t = max(times)
    total_bytes = sum(e.get("size_bytes", 0) for e in completed)
    duration_hours = (last_t - first_t) / 3600
    speed_mbps = (total_bytes / (1024*1024)) / (duration_hours * 3600) if duration_hours > 0 else 0
    print(f"\n=== VELOCIDADE ===")
    print(f"Total baixado: {total_bytes/(1024**3):.2f} GB")
    print(f"Duração: {duration_hours:.1f} horas")
    print(f"Velocidade média: {speed_mbps:.2f} MB/s")

print(f"\nItens faltando: {len(failed)} FAILED + {len(dl)} DOWNLOADING")
print(f"Local: {os.path.join(BASE, 'VIDEOS CORTES')}")