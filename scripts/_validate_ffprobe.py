import json, os, subprocess, random

BASE = "/Volumes/SSD EXT MACBOOK/JHC-PROJETOS/JHC VIRAL ENGINE/GTA 6"

with open(os.path.join(BASE, "data/bulk_import/state/download_entries.json")) as f:
    entries = json.load(f)

completed = [e for e in entries if e.get("state") == "COMPLETED"]
videos = [e for e in completed if e.get("filename","").endswith((".mp4",".mov",".avi",".mkv",".webm"))]
images = [e for e in completed if e.get("filename","").endswith((".jpg",".jpeg",".png",".gif",".webp"))]

print(f"=== VALIDAÇÃO FFPROBE AMOSTRAL ===")
print(f"Vídeos COMPLETED: {len(videos)}")
print(f"Imagens COMPLETED: {len(images)}")

sample_size = max(1, len(videos) // 10)
sample = random.sample(videos, sample_size)
print(f"Amostra: {sample_size} vídeos")

valid = 0
invalid = 0
missing = 0
for e in sample:
    dest = e.get("dest_path", "")
    if not os.path.isfile(dest):
        alt = os.path.join(BASE, "VIDEOS CORTES", e.get("filename",""))
        if os.path.isfile(alt):
            dest = alt
    if not os.path.isfile(dest):
        missing += 1
        continue
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", dest],
            capture_output=True, text=True, timeout=10
        )
        duration = float(result.stdout.strip()) if result.stdout.strip() else 0
        if duration > 0.5:
            valid += 1
        else:
            invalid += 1
            print(f"  INVÁLIDO: {e['filename']} duration={duration}")
    except Exception as ex:
        invalid += 1
        print(f"  ERRO: {e['filename']}: {ex}")

print(f"\nResultado ffprobe:")
print(f"  Válidos: {valid}/{sample_size}")
print(f"  Inválidos: {invalid}/{sample_size}")
print(f"  Arquivos não encontrados: {missing}/{sample_size}")

failed = [e for e in entries if e.get("state") == "FAILED"]
print(f"\n=== FAILED ({len(failed)}) ===")
for fe in failed:
    print(f"  {fe.get('filename')}: {fe.get('error','?')}")
    print(f"  URL: {fe.get('url','?')[:80]}...")
    print(f"  Retries: {fe.get('retries',0)}/{fe.get('max_retries',0)}")