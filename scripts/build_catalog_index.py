#!/usr/bin/env python3
"""FASE 4 — Constrói índice não destrutivo do acervo.

Lê checkpoint entries + metadados ffprobe/Pillow e gera catalog_index.json.
Nenhum arquivo é movido ou renomeado. Índice é referência apenas.

Uso: python scripts/build_catalog_index.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ENTRIES_PATH = BASE / "data" / "bulk_import" / "state" / "download_entries.json"
INDEX_PATH = BASE / "data" / "bulk_import" / "state" / "catalog_index.json"
VIDEOS_DIR = BASE / "VIDEOS CORTES"


def get_video_metadata(filepath: str) -> dict:
    """Extrai duração, resolução, codec via ffprobe."""
    if not os.path.isfile(filepath):
        return {"error": "file_not_found"}
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries",
             "format=duration,size:stream=width,height,codec_name",
             "-of", "json", filepath],
            capture_output=True, text=True, timeout=10,
        )
        data = json.loads(result.stdout)
        fmt = data.get("format", {})
        streams = data.get("streams", [{}])
        video_stream = next(
            (s for s in streams if s.get("codec_name") not in ("aac", "mp3", "opus")),
            {},
        )
        return {
            "duration_s": round(float(fmt.get("duration", 0)), 1),
            "width": video_stream.get("width"),
            "height": video_stream.get("height"),
            "codec": video_stream.get("codec_name"),
            "size_bytes": int(fmt.get("size", 0)),
        }
    except Exception as ex:
        return {"error": str(ex)}


def get_image_metadata(filepath: str) -> dict:
    """Extrai dimensões e formato via Pillow."""
    if not os.path.isfile(filepath):
        return {"error": "file_not_found"}
    try:
        from PIL import Image
        with Image.open(filepath) as img:
            return {
                "width": img.width,
                "height": img.height,
                "format": img.format,
                "mode": img.mode,
                "size_bytes": os.path.getsize(filepath),
            }
    except Exception as ex:
        return {"error": str(ex)}


def is_autoreels_compatible(meta: dict) -> bool:
    """Verifica compatibilidade com AutoReels (vídeo vertical >=720p, <=120s)."""
    if meta.get("error"):
        return False
    w = meta.get("width")
    h = meta.get("height")
    dur = meta.get("duration_s", 0)
    if not w or not h:
        return False
    # Vertical ou quadrado, pelo menos 720p na menor dimensão, até 120s
    min_dim = min(w, h)
    return min_dim >= 720 and dur <= 120


def main():
    print("=== FASE 4 — CONSTRUÇÃO DO ÍNDICE DE CATÁLOGO ===\n")

    with open(ENTRIES_PATH) as f:
        entries = json.load(f)

    completed = [e for e in entries if e.get("state") == "COMPLETED"]
    print(f"Entries COMPLETED: {len(completed)}")

    index = []
    videos_processed = 0
    images_processed = 0
    autoreels_compatible = 0
    errors = 0

    for i, entry in enumerate(completed):
        filename = entry.get("filename", "")
        filepath = os.path.join(str(VIDEOS_DIR), filename)
        tags = entry.get("tags", [])
        category = entry.get("category", "")

        # Determinar tipo
        is_video = any("type=v" in str(t) for t in tags)
        is_image = any("type=img" in str(t) for t in tags)
        if not is_video and not is_image:
            if filename.endswith((".mp4", ".mov", ".avi", ".mkv", ".webm")):
                is_video = True
            elif filename.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                is_image = True

        # Extrair metadados
        meta = {}
        if is_video:
            meta = get_video_metadata(filepath)
            videos_processed += 1
        elif is_image:
            meta = get_image_metadata(filepath)
            images_processed += 1

        if meta.get("error"):
            errors += 1

        # Tags como dict
        tag_dict = {}
        for t in tags:
            if "=" in str(t):
                k, v = str(t).split("=", 1)
                tag_dict[k] = v
            else:
                tag_dict[str(t)] = True

        record = {
            "filename": filename,
            "path": filepath,
            "type": "video" if is_video else ("image" if is_image else "unknown"),
            "category": category,
            "source_pack": entry.get("source_pack", ""),
            "hd": tag_dict.get("hd") == "1",
            "metadata": meta,
            "autoreels_compatible": is_autoreels_compatible(meta) if is_video else False,
            "downloaded_at": entry.get("completed_at"),
            "sha256": entry.get("sha256", ""),
        }

        if record["autoreels_compatible"]:
            autoreels_compatible += 1

        index.append(record)

        # Progresso a cada 100
        if (i + 1) % 100 == 0:
            print(f"  Processados: {i + 1}/{len(completed)}")

    # Salvar índice
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(INDEX_PATH, "w") as f:
        json.dump(index, f, indent=2, default=str)

    print(f"\n=== RESULTADO ===")
    print(f"Índice salvo: {INDEX_PATH}")
    print(f"Total indexado: {len(index)}")
    print(f"Vídeos processados: {videos_processed}")
    print(f"Imagens processadas: {images_processed}")
    print(f"AutoReels compatíveis: {autoreels_compatible}")
    print(f"Erros de metadados: {errors}")

    # Resumo por categoria
    from collections import Counter
    cats = Counter(r["category"] for r in index)
    print(f"\nCategorias:")
    for cat, count in sorted(cats.items()):
        print(f"  {cat}: {count}")

    # Resumo por tipo
    types = Counter(r["type"] for r in index)
    print(f"\nTipos:")
    for t, count in sorted(types.items()):
        print(f"  {t}: {count}")


if __name__ == "__main__":
    main()