#!/usr/bin/env python3
"""Foreground entry point for launchd — runs worker without os.fork().

launchd manages process lifecycle; this script must NOT daemonize.
It imports run_loop directly and blocks until work is done or stopped.
"""
import sys
import os
import logging
from pathlib import Path

# Ensure project root is on sys.path
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.chdir(str(BASE))

# Clear stop flag so worker can run on launchd restart
stop_flag = BASE / "data" / "bulk_import" / "worker.stop"
stop_flag.unlink(missing_ok=True)

# Import worker internals (avoid cmd_start which forks)
from scripts.bulk_worker import run_loop, setup_logging  # noqa: E402

logger = setup_logging()
logger.info("Foreground worker starting (PID %d)", os.getpid())
run_loop(logger)
logger.info("Foreground worker exited cleanly")