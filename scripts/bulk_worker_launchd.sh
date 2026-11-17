#!/bin/bash
# Launchd wrapper for bulk worker — runs in FOREGROUND (no fork)
# launchd manages process lifecycle; do NOT use os.fork() here.
cd "/Volumes/SSD EXT MACBOOK/JHC-PROJETOS/JHC VIRAL ENGINE/GTA 6" || exit 1
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"

# Clear stop flag on launchd start so service can run
rm -f data/bulk_import/worker.stop

# Run worker inline (foreground) — launchd keeps it alive
exec .venv/bin/python3 -I -c "
import sys, logging
sys.path.insert(0, '.')
from scripts.bulk_worker import run_loop, setup_logging
logger = setup_logging()
run_loop(logger)
"