import json
from collections import Counter

BASE = "/Volumes/SSD EXT MACBOOK/JHC-PROJETOS/JHC VIRAL ENGINE/GTA 6"

with open(f"{BASE}/data/auth/pro_catalog.json") as f:
    catalog = json.load(f)

print(f"Total itens catálogo: {len(catalog)}")

drive_ids = [item.get("drive", "") for item in catalog]
unique_drives = set(drive_ids)
print(f"Drive IDs únicos: {len(unique_drives)}")
print(f"Duplicatas: {len(catalog) - len(unique_drives)}")

dup_counts = Counter(drive_ids)
top_dups = [(did, count) for did, count in dup_counts.most_common(20) if count > 1]
print(f"\nDrive IDs repetidos ({len(top_dups)}):")
for did, count in top_dups[:10]:
    titles = [item.get("t", "?") for item in catalog if item.get("drive") == did][:3]
    print(f"  {did[:30]}... x{count}: {titles}")

type_unique = Counter()
seen = set()
for item in catalog:
    did = item.get("drive", "")
    if did not in seen:
        seen.add(did)
        type_unique[item.get("type", "?")] += 1
print(f"\nÚnicos por tipo:")
for t, c in sorted(type_unique.items()):
    print(f"  {t}: {c}")
print(f"  Total único: {sum(type_unique.values())}")