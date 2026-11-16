#!/usr/bin/env python3
"""Worker persistente para importação em massa — roda independente do Claude Code.

Uso:
    python scripts/bulk_worker.py start   # inicia daemon em background
    python scripts/bulk_worker.py status  # mostra progresso + PID
    python scripts/bulk_worker.py pause   # pausa após lote atual
    python scripts/bulk_worker.py resume  # retoma
    python scripts/bulk_worker.py stop    # graceful shutdown
"""
import sys
import os
import json
import signal
import time
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime

# Setup path
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

PID_FILE = BASE / "data" / "bulk_import" / "worker.pid"
PAUSE_FLAG = BASE / "data" / "bulk_import" / "worker.pause"
STOP_FLAG = BASE / "data" / "bulk_import" / "worker.stop"
LOG_DIR = BASE / "data" / "bulk_import" / "logs"
STATE_DIR = BASE / "data" / "bulk_import" / "state"
CATALOG_PATH = BASE / "data" / "auth" / "pro_catalog.json"
TARGET_DIR = "VIDEOS CORTES"
BATCH_SIZE = 100
POLL_INTERVAL = 5  # segundos entre lotes


def setup_logging() -> logging.Logger:
    """Configura logger com rotação: max 10 arquivos, 5MB cada."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("bulk_worker")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        handler = RotatingFileHandler(
            LOG_DIR / "worker.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=10,
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(handler)

        # Console handler para quando roda em foreground
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
        logger.addHandler(console)

    return logger


def write_pid():
    """Escreve PID do worker."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))


def read_pid() -> int | None:
    """Lê PID do worker, retorna None se não existe ou processo morto."""
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)  # Verifica se processo existe
        return pid
    except (ValueError, OSError):
        PID_FILE.unlink(missing_ok=True)
        return None


def is_running() -> bool:
    return read_pid() is not None


def cmd_start(logger: logging.Logger):
    """Inicia worker daemon em background."""
    if is_running():
        pid = read_pid()
        print(f"Worker já rodando (PID {pid}). Use 'status' para ver progresso.")
        return

    # Fork para background
    pid = os.fork()
    if pid > 0:
        # Parent
        print(f"Worker iniciado em background (PID {pid}).")
        print(f"Logs: {LOG_DIR}/worker.log")
        print(f"Status: python scripts/bulk_worker.py status")
        return

    # Child — daemon loop
    os.setsid()
    # Redirect stdout/stderr para /dev/null
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    os.close(devnull)

    write_pid()
    logger.info(f"Worker iniciado (PID {os.getpid()})")

    # Cleanup flags
    PAUSE_FLAG.unlink(missing_ok=True)
    STOP_FLAG.unlink(missing_ok=True)

    # Signal handlers
    def handle_stop(signum, frame):
        logger.info("Signal recebido, parando...")
        STOP_FLAG.touch()

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    run_loop(logger)

    # Cleanup
    PID_FILE.unlink(missing_ok=True)
    logger.info("Worker parado.")


STALL_THRESHOLD_MIN = 10  # minutos sem progresso para considerar stalled


def _check_stalled_downloads(imp, logger: logging.Logger) -> None:
    """Watchdog: detecta downloads DOWNLOADING com >10min e size=0, reseta para PENDING."""
    import json as _json

    entries_file = STATE_DIR / "download_entries.json"
    if not entries_file.exists():
        return
    try:
        with open(entries_file) as f:
            entries = _json.load(f)
    except Exception:
        return

    now = time.time()
    changed = False
    for e in entries:
        if e.get("state") != "DOWNLOADING":
            continue
        started = e.get("started_at", 0)
        if not started:
            continue
        age_min = (now - started) / 60
        size = e.get("size_bytes", 0)
        if age_min > STALL_THRESHOLD_MIN and size == 0:
            fn = e.get("filename", "?")
            logger.warning(f"WATCHDOG: {fn} stalled ({age_min:.0f}min, 0 bytes) → PENDING")
            e["state"] = "PENDING"
            e["retries"] = max(0, e.get("retries", 0) - 1)  # não conta como retry falho
            e["error"] = ""
            e["started_at"] = None
            changed = True

    if changed:
        with open(entries_file, "w") as f:
            _json.dump(entries, f, indent=2, default=str)
        logger.info("WATCHDOG: checkpoint atualizado após reset de stalled")


def run_loop(logger: logging.Logger):
    """Loop principal: processa lotes até stop/pause ou tudo concluído."""
    from src.media.pack_bulk_importer import PackBulkImporter

    imp = PackBulkImporter(ssd_root=str(BASE))

    # Recarregar catálogo para garantir todos os entries
    result = imp.load_catalog_from_file(str(CATALOG_PATH), target_dir=TARGET_DIR)
    logger.info(f"Catálogo carregado: {result}")

    consecutive_empty = 0
    batch_num = 0

    while True:
        # Check stop flag
        if STOP_FLAG.exists():
            logger.info("Stop flag detectado, encerrando loop.")
            break

        # Check pause flag
        if PAUSE_FLAG.exists():
            logger.info("Pause flag detectado, aguardando...")
            time.sleep(10)
            continue

        # Processar lote
        batch_num += 1
        logger.info(f"Iniciando lote #{batch_num} (size={BATCH_SIZE})")

        try:
            results = imp.process_batch(batch_size=BATCH_SIZE)
        except Exception as e:
            logger.error(f"Erro no lote #{batch_num}: {e}", exc_info=True)
            time.sleep(30)
            continue

        completed = sum(1 for r in results if r.get("state") == "COMPLETED")
        failed = sum(1 for r in results if r.get("state") == "FAILED")
        skipped = len(results) - completed - failed

        progress = imp.get_progress()
        by_state = progress.get("by_state", {})

        logger.info(
            f"Lote #{batch_num}: {completed} ok, {failed} fail, {skipped} skip | "
            f"Total: {by_state.get('COMPLETED', 0)} done, "
            f"{by_state.get('PENDING', 0)} pend, "
            f"{by_state.get('FAILED', 0)} fail | "
            f"SSD: {progress.get('ssd_free_gb', '?')}GB"
        )

        # Watchdog: detectar downloads stalled (>10min sem progresso)
        _check_stalled_downloads(imp, logger)

        # Se lote vazio, verificar se acabou
        if len(results) == 0:
            pending = by_state.get("PENDING", 0) + by_state.get("DOWNLOADING", 0)
            if pending == 0:
                logger.info("Todos os itens processados! Worker completou.")
                break
            consecutive_empty += 1
            if consecutive_empty >= 3:
                logger.warning(f"{consecutive_empty} lotes vazios consecutivos, aguardando 60s...")
                time.sleep(60)
                consecutive_empty = 0
            else:
                time.sleep(POLL_INTERVAL)
        else:
            consecutive_empty = 0
            time.sleep(POLL_INTERVAL)

        # Check stop novamente após lote
        if STOP_FLAG.exists():
            logger.info("Stop flag detectado pós-lote, encerrando.")
            break


def cmd_status():
    """Mostra status do worker."""
    pid = read_pid()
    if pid:
        print(f"✅ Worker RODANDO (PID {pid})")
    else:
        print("❌ Worker PARADO")

    # Mostrar progresso
    progress_file = STATE_DIR / "import_progress.json"
    if progress_file.exists():
        try:
            prog = json.loads(progress_file.read_text())
            print(f"\n📊 Progresso:")
            print(f"  Baixado: {prog.get('bytes_downloaded', 0) / (1024**2):.1f} MB")
            print(f"  SSD livre: {prog.get('ssd_free_bytes', 0) / (1024**3):.1f} GB")
            print(f"  Rodando: {prog.get('is_running', False)}")
            print(f"  Pausado: {prog.get('is_paused', False)}")
        except Exception as e:
            print(f"  Erro lendo progresso: {e}")

    # Mostrar entries summary
    entries_file = STATE_DIR / "download_entries.json"
    if entries_file.exists():
        try:
            entries = json.loads(entries_file.read_text())
            from collections import Counter
            states = Counter(e.get("state") for e in entries)
            print(f"\n📋 Entries ({len(entries)} total):")
            for s, c in sorted(states.items()):
                print(f"  {s}: {c}")
        except Exception as e:
            print(f"  Erro lendo entries: {e}")

    # Flags
    if PAUSE_FLAG.exists():
        print("\n⏸️  PAUSE FLAG ativo")
    if STOP_FLAG.exists():
        print("\n🛑 STOP FLAG ativo")

    # Últimas linhas do log
    log_file = LOG_DIR / "worker.log"
    if log_file.exists():
        lines = log_file.read_text().strip().split("\n")
        print(f"\n📝 Últimas 5 linhas do log:")
        for line in lines[-5:]:
            print(f"  {line}")


def cmd_pause():
    """Grava pause flag."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PAUSE_FLAG.touch()
    print("⏸️  Pause flag criado. Worker vai parar após lote atual.")


def cmd_resume():
    """Remove pause flag."""
    PAUSE_FLAG.unlink(missing_ok=True)
    print("▶️  Pause flag removido. Worker vai retomar.")


def cmd_stop():
    """Graceful shutdown via flag + signal."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STOP_FLAG.touch()
    pid = read_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"🛑 SIGTERM enviado para PID {pid}. Worker vai parar após lote atual.")
        except OSError:
            print(f"🛑 Stop flag criado. Processo {pid} não responde.")
    else:
        print("🛑 Stop flag criado. Worker não está rodando.")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()
    logger = setup_logging()

    if command == "start":
        cmd_start(logger)
    elif command == "status":
        cmd_status()
    elif command == "pause":
        cmd_pause()
    elif command == "resume":
        cmd_resume()
    elif command == "stop":
        cmd_stop()
    else:
        print(f"Comando desconhecido: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()