import json, os
from collections import Counter

BASE = "/Volumes/SSD EXT MACBOOK/JHC-PROJETOS/JHC VIRAL ENGINE/GTA 6"
SSD_ROOT = "/Volumes/SSD EXT MACBOOK"

# 1. Busca arquivos físicos nos caminhos possíveis
search_dirs = [
    os.path.join(SSD_ROOT, "VIDEOS CORTES"),
    os.path.join(BASE, "VIDEOS CORTES"),
    os.path.join(BASE, "data", "bulk_import", "downloads"),
    os.path.join(BASE, "downloads"),
]

print("=== ARQUIVOS FÍSICOS ===")
for d in search_dirs:
    if os.path.isdir(d):
        files = [f for f in os.listdir(d) if not f.startswith('.')]
        exts = Counter(os.path.splitext(f)[1].lower() for f in files)
        print(f"{d}: {len(files)} arquivos")
        for ext, c in sorted(exts.items()):
            print(f"  {ext or '(sem)'}: {c}")
    else:
        print(f"{d}: NÃO EXISTE")

# 2. Entries analysis
entries_path = os.path.join(BASE, "data/bulk_import/state/download_entries.json")
with open(entries_path) as f:
    entries = json.load(f)

completed = [e for e in entries if e.get("state") == "COMPLETED"]
print(f"\n=== ENTRIES COMPLETED ({len(completed)}) ===")
if completed:
    print(f"Campos sample: {list(completed[0].keys())}")
    tdirs = Counter(e.get("target_dir", e.get("path", e.get("dir", "?"))) for e in completed)
    for td, c in tdirs.most_common(5):
        print(f"  target={td}: {c}")

# 3. Gap analysis
cat_path = os.path.join(BASE, "data/auth/pro_catalog.json")
with open(cat_path) as f:
    catalog = json.load(f)

entry_ids = set(str(e.get("drive_id", e.get("id", e.get("filename", "")))) for e in entries)
cat_ids = set(str(item.get("drive", item.get("id", ""))) for item in catalog)

only_cat = cat_ids - entry_ids
print(f"\n=== GAP ===")
print(f"Entries: {len(entry_ids)}, Catálogo: {len(cat_ids)}")
print(f"Só catálogo (não enfileirados): {len(only_cat)}")

not_queued = [item for item in catalog if str(item.get("drive", item.get("id",""))) not in entry_ids]
nq_types = Counter(item.get("type", "?") for item in not_queued)
for t, c in sorted(nq_types.items()):
    print(f"  type={t}: {c}")