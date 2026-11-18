#!/usr/bin/env python3
"""Radar YouTube Monitor — periodic search for GTA VI content.

Runs as a background worker or via cron. Searches YouTube for recent
GTA VI videos, deduplicates against catalog, and logs results.

Usage:
    python scripts/radar_monitor.py              # single run
    python scripts/radar_monitor.py --daemon     # loop every 30min
    python scripts/radar_monitor.py --interval 600  # custom interval (seconds)
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [radar-monitor] %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/tmp/jhc_radar_monitor.log"),
    ],
)
logger = logging.getLogger(__name__)

STATE_FILE = PROJECT_ROOT / "data" / "scheduler" / "radar_monitor_state.json"
RESULTS_FILE = PROJECT_ROOT / "data" / "radar" / "latest_youtube_results.json"

DEFAULT_QUERIES = [
    "GTA VI trailer",
    "GTA 6 novidades",
    "Rockstar Games GTA",
    "Grand Theft Auto VI",
]


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"enabled": False, "last_run": None, "interval": 1800, "total_runs": 0, "total_results": 0}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def run_search(queries: list[str], limit_per_query: int = 5) -> list[dict]:
    """Run radar search via the backend API or directly."""
    all_results = []
    seen_urls = set()

    # Try direct import first
    try:
        from src.research.youtube_radar import YouTubeRadar
        radar = YouTubeRadar()
        for query in queries:
            try:
                results = radar.search(query, max_results=limit_per_query)
                for r in results:
                    url = r.get("url") or r.get("link", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        r["_query"] = query
                        r["_found_at"] = time.time()
                        all_results.append(r)
                logger.info("Query '%s': %d results", query, len(results))
            except Exception as e:
                logger.warning("Query '%s' failed: %s", query, e)
    except ImportError:
        logger.warning("YouTubeRadar module not available, skipping direct search")

    return all_results


def save_results(results: list[dict]) -> None:
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": time.time(),
        "count": len(results),
        "results": results[:50],  # keep last 50
    }
    RESULTS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def single_run(queries: list[str] | None = None) -> dict:
    """Execute one search cycle."""
    state = load_state()
    qs = queries or DEFAULT_QUERIES
    logger.info("Starting radar search cycle (%d queries)", len(qs))

    results = run_search(qs)
    save_results(results)

    state["last_run"] = time.time()
    state["total_runs"] = state.get("total_runs", 0) + 1
    state["total_results"] = state.get("total_results", 0) + len(results)
    state["last_result_count"] = len(results)
    save_state(state)

    logger.info("Search cycle complete: %d results found", len(results))
    return {"results": len(results), "state": state}


def daemon_loop(interval: int = 1800) -> None:
    """Run search cycles in a loop."""
    state = load_state()
    state["enabled"] = True
    state["interval"] = interval
    save_state(state)
    logger.info("Radar monitor daemon started (interval=%ds)", interval)

    while True:
        try:
            state = load_state()
            if not state.get("enabled", True):
                logger.info("Monitor paused, waiting...")
                time.sleep(60)
                continue
            single_run()
        except KeyboardInterrupt:
            logger.info("Monitor stopped by user")
            break
        except Exception as e:
            logger.error("Monitor cycle error: %s", e)
        time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="JHC Radar YouTube Monitor")
    parser.add_argument("--daemon", action="store_true", help="Run in daemon mode")
    parser.add_argument("--interval", type=int, default=1800, help="Search interval in seconds (default: 1800)")
    parser.add_argument("--query", type=str, nargs="*", help="Custom search queries")
    args = parser.parse_args()

    if args.daemon:
        daemon_loop(args.interval)
    else:
        result = single_run(args.query)
        print(json.dumps(result, indent=2))