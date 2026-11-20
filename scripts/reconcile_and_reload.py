#!/usr/bin/env python3
"""FASE 0+1+2: Reconciliação, retry do FAILED, recarga dos 1.113 faltantes com filter_type."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.media.pack_bulk_importer import PackBulkImporter

BASE = "/Volumes/SSD EXT MACBOOK/JHC-PROJETOS/JHC VIRAL ENGINE/GTA 6"
CATALOG = os.path.join(BASE, "data/auth/pro_catalog.json")
TARGET_DIR = "VIDEOS CORTES"

print("=== FASE 0: RECONCILIAÇÃO ===")
imp = PackBulkImporter(ssd_root=BASE)
result = imp.load_catalog_from_file(CATALOG, target_dir=TARGET_DIR)
print(f"Recarga catálogo: {result}")

progress = imp.get_progress()
by_state = progress.get("by_state", {})
print(f"\nEstado após recarga:")
for state, count in sorted(by_state.items()):
    print(f"  {state}: {count}")
print(f"  total_discovered: {progress.get('total_discovered')}")
print(f"  total_pending: {progress.get('total_pending')}")

# Verificar se todos os 2654 estão agora
total_entries = len(imp._entries)
print(f"\nTotal entries na memória: {total_entries}")
if total_entries >= 2654:
    print("✅ GAP RESOLVIDO: todos os 2.654 itens enfileirados")
else:
    print(f"⚠️  Gap persiste: {2654 - total_entries} itens faltando")

print("\n=== FASE 1: RETRY DO FAILED ===")
retried = imp.retry_failed()
print(f"Entries reenfileiradas para retry: {retried}")

# Verificar estado após retry
progress2 = imp.get_progress()
by_state2 = progress2.get("by_state", {})
print(f"Estado após retry:")
for state, count in sorted(by_state2.items()):
    print(f"  {state}: {count}")

print("\n=== BREAKDOWN POR TIPO ===")
video_count = 0
image_count = 0
for e in imp._entries.values():
    tags = e.tags if hasattr(e, 'tags') else []
    if any("type=img" in str(t) for t in tags):
        image_count += 1
    elif any("type=v" in str(t) for t in tags):
        video_count += 1
print(f"  Vídeos: {video_count}")
print(f"  Imagens: {image_count}")
print(f"  Total: {video_count + image_count}")

print("\n=== SSD STATUS ===")
print(f"  Livre: {progress2.get('ssd_free_gb', '?')} GB")
print(f"  Bytes baixados: {progress2.get('bytes_downloaded', 0)}")