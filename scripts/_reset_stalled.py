import json, time, os
from pathlib import Path
from collections import Counter

BASE = Path("/Volumes/SSD EXT MACBOOK/JHC-PROJETOS/JHC VIRAL ENGINE/GTA 6")
ENTRIES_FILE = BASE / "data/bulk_import/state/download_entries.json"

with open(ENTRIES_FILE) as f:
    entries = json.load(f)

changed = 0
for e in entries:
    fn = e.get("filename", "")

    # Resetar Vídeo 0117.mp4: DOWNLOADING stalled → PENDING (preserva arquivo parcial)
    if fn == "Vídeo 0117.mp4" and e.get("state") == "DOWNLOADING":
        print(f"RESET: {fn} DOWNLOADING → PENDING (arquivo parcial 8.3MB preservado)")
        e["state"] = "PENDING"
        e["retries"] = 0
        e["error"] = ""
        e["started_at"] = None
        changed += 1

    # Confirmar Vídeo 0174.mp4 como FAILED permanente
    if fn == "Vídeo 0174.mp4" and e.get("state") == "FAILED":
        print(f"CONFIRMADO: {fn} FAILED permanente (3/3 retries, arquivo indisponível)")

    # Vídeo 0772.mp4 já está PENDING, ok
    if fn == "Vídeo 0772.mp4":
        print(f"OK: {fn} state={e.get('state')} retries={e.get('retries',0)}")

if changed > 0:
    with open(ENTRIES_FILE, "w") as f:
        json.dump(entries, f, indent=2, default=str)
    print(f"\n✅ Checkpoint atualizado: {changed} entry resetada")
else:
    print("\n⚠️ Nenhuma mudança necessária")

# Verificar estado final
states = Counter(e.get("state") for e in entries)
print(f"\nEstado após correção:")
for s, c in sorted(states.items()):
    print(f"  {s}: {c}")