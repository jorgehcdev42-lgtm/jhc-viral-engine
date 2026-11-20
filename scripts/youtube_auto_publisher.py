#!/usr/bin/env python3
"""YouTube Auto-Publisher Worker — Hybrid API/Playwright publisher.

YT-008: Rewritten to delegate to AutoPublishScheduler.execute_youtube_hybrid().
Preserves CLI/daemon interface and LaunchAgent compatibility.

Flow:
  1. Load eligible YouTube jobs from AutoPublishScheduler
  2. For each eligible job, call execute_youtube_hybrid()
  3. Log results (method used, status, errors)
  4. Respect daily limits, schedule hours, pause flags

Usage:
    python scripts/youtube_auto_publisher.py              # single run
    python scripts/youtube_auto_publisher.py --daemon     # loop every 30min
    python scripts/youtube_auto_publisher.py --interval 1800  # custom interval
    python scripts/youtube_auto_publisher.py --dry-run    # validate without publishing
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [yt-publisher] %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/tmp/jhc_yt_publisher.log"),
    ],
)
logger = logging.getLogger(__name__)

DATA_ROOT = PROJECT_ROOT / "data"
QUEUE_FILE = DATA_ROOT / "scheduler" / "publish_queue.json"
STATS_FILE = DATA_ROOT / "scheduler" / "daily_stats.json"
PUBLISH_LOG = DATA_ROOT / "publishing" / "auto_publish_log.json"
BRAZIL_TZ = timezone(timedelta(hours=-3))


def load_queue() -> dict:
    """Load legacy publish_queue.json for schedule/pause/daily-limit config."""
    if QUEUE_FILE.exists():
        try:
            return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def is_scheduled_hour(schedule_hours: list[int]) -> bool:
    """Check if current hour (Brazil time) is in the scheduled hours."""
    now_hour = datetime.now(BRAZIL_TZ).hour
    return now_hour in schedule_hours


def get_today_key(profile_id: str) -> str:
    today = datetime.now(BRAZIL_TZ).strftime("%Y-%m-%d")
    return f"{profile_id}:{today}"


def load_daily_stats() -> dict:
    if STATS_FILE.exists():
        try:
            return json.loads(STATS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_daily_stats(stats: dict) -> None:
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATS_FILE.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")


def append_publish_log(entry: dict) -> None:
    """Append an entry to the auto-publish log."""
    log_entries = []
    if PUBLISH_LOG.exists():
        try:
            log_entries = json.loads(PUBLISH_LOG.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log_entries = []
    log_entries.append(entry)
    PUBLISH_LOG.parent.mkdir(parents=True, exist_ok=True)
    PUBLISH_LOG.write_text(json.dumps(log_entries, ensure_ascii=False, indent=2), encoding="utf-8")


async def single_run(force: bool = False, dry_run: bool = False) -> dict:
    """Execute one publish cycle using AutoPublishScheduler + execute_youtube_hybrid.

    Args:
        force: Ignore schedule hours and pause flags.
        dry_run: Validate jobs and auth state without executing upload.

    Returns:
        Dict with cycle results summary.
    """
    from src.automation.autopublish_scheduler import AutoPublishScheduler

    queue = load_queue()
    profile_id = queue.get("profile_id", "leonidagta6flashbr")
    max_per_day = queue.get("max_per_day", 3)
    schedule_hours = queue.get("schedule_hours", [11, 16, 20])

    # Check pause flag (legacy queue compatibility)
    if not force and queue.get("paused", False):
        reason = queue.get("pause_reason", "unknown")
        logger.info("Publisher paused (reason: %s), skipping", reason)
        return {"published": 0, "reason": "paused", "pause_reason": reason}

    # Check auto_publish enabled (legacy queue compatibility)
    if not force and not queue.get("auto_publish", False):
        # Also check if there are any approved jobs in the canonical scheduler
        scheduler = AutoPublishScheduler(DATA_ROOT)
        eligible = scheduler.get_eligible_jobs(limit=1)
        youtube_eligible = [j for j in eligible if j.platform == "youtube"]
        if not youtube_eligible:
            logger.info("Auto-publish disabled and no eligible YouTube jobs, skipping")
            return {"published": 0, "reason": "auto_publish_disabled"}

    # Check schedule hours
    if not force and not is_scheduled_hour(schedule_hours):
        next_hour = min(
            (h for h in schedule_hours if h > datetime.now(BRAZIL_TZ).hour),
            default=schedule_hours[0],
        )
        logger.info("Not in scheduled hour. Next slot: %dh", next_hour)
        return {"published": 0, "reason": "not_scheduled_hour", "next_hour": next_hour}

    # Check daily limit
    stats = load_daily_stats()
    key = get_today_key(profile_id)
    published_today = len(stats.get(key, {}).get("published_videos", []))
    if published_today >= max_per_day:
        logger.info("Daily limit reached (%d/%d)", published_today, max_per_day)
        return {"published": 0, "reason": "daily_limit_reached", "count": published_today}

    # Get eligible YouTube jobs from canonical scheduler
    scheduler = AutoPublishScheduler(DATA_ROOT)
    eligible = scheduler.get_eligible_jobs(limit=max_per_day - published_today)
    youtube_jobs = [j for j in eligible if j.platform == "youtube"]

    if not youtube_jobs:
        logger.info("No eligible YouTube jobs in scheduler")
        return {"published": 0, "reason": "no_eligible_jobs"}

    logger.info("Found %d eligible YouTube job(s)", len(youtube_jobs))

    # Dry-run mode: validate without publishing
    if dry_run:
        results = []
        for job in youtube_jobs:
            from src.publishing.adapters import YouTubeAdapter, PublishState
            adapter = YouTubeAdapter(DATA_ROOT, job.profile_id)
            state = await adapter.check_connection()
            results.append({
                "job_id": job.job_id,
                "title": job.title[:40],
                "auth_state": state.value,
                "scheduled_at": job.scheduled_at,
                "video_exists": Path(job.video_path).exists(),
            })
        logger.info("Dry-run complete: %d jobs validated", len(results))
        return {"dry_run": True, "jobs_validated": len(results), "details": results}

    # Execute hybrid publish for each eligible job
    published_count = 0
    failed_count = 0
    results_summary = []

    for job in youtube_jobs:
        # Re-check daily limit before each publish
        stats = load_daily_stats()
        published_today = len(stats.get(key, {}).get("published_videos", []))
        if published_today >= max_per_day:
            logger.info("Daily limit reached during cycle (%d/%d)", published_today, max_per_day)
            break

        logger.info("Processing job %s: %s", job.job_id, job.title[:40])
        result = await scheduler.execute_youtube_hybrid(job)

        results_summary.append({
            "job_id": job.job_id,
            "method": result.get("method"),
            "status": result.get("status"),
            "error": result.get("error"),
        })

        if result.get("status") == "published":
            published_count += 1
            video_id = result.get("remote_id", "")
            url = result.get("url", "")

            # Update daily stats
            if key not in stats:
                stats[key] = {
                    "date": datetime.now(BRAZIL_TZ).strftime("%Y-%m-%d"),
                    "profile_id": profile_id,
                    "candidates": 0,
                    "approved": 0,
                    "failed": 0,
                }
            stats[key]["approved"] = stats[key].get("approved", 0) + 1
            stats[key]["candidates"] = stats[key].get("candidates", 0) + 1
            stats[key].setdefault("published_videos", []).append(video_id)
            stats[key]["last_publish_at"] = time.time()
            save_daily_stats(stats)

            # Append to publish log
            append_publish_log({
                "platform": "youtube",
                "video_id": video_id,
                "job_id": job.job_id,
                "title": job.title,
                "url": url,
                "method": result.get("method", "unknown"),
                "published_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            })

            logger.info("Published job %s via %s: %s", job.job_id, result.get("method"), url)

        elif result.get("status") == "processing":
            # Upload accepted but not yet confirmed — don't count as published or failed
            logger.info("Job %s processing (method=%s), will confirm on next cycle",
                        job.job_id, result.get("method"))

        else:
            failed_count += 1
            logger.warning("Job %s failed: %s (method=%s)",
                           job.job_id, result.get("error"), result.get("method"))

    return {
        "published": published_count,
        "failed": failed_count,
        "processed": len(youtube_jobs),
        "results": results_summary,
    }


def daemon_loop(interval: int = 1800) -> None:
    """Run publish cycles in a loop."""
    logger.info("YouTube hybrid publisher daemon started (interval=%ds)", interval)
    while True:
        try:
            result = asyncio.run(single_run())
            logger.info("Cycle result: %s", json.dumps(result, default=str))
        except KeyboardInterrupt:
            logger.info("Publisher stopped by user")
            break
        except Exception as e:
            logger.error("Publisher cycle error: %s", e)
        time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="JHC YouTube Hybrid Publisher (YT-008)")
    parser.add_argument("--daemon", action="store_true", help="Run in daemon mode")
    parser.add_argument("--interval", type=int, default=1800, help="Check interval in seconds")
    parser.add_argument("--force", action="store_true", help="Force publish regardless of schedule")
    parser.add_argument("--dry-run", action="store_true", help="Validate jobs without publishing")
    args = parser.parse_args()

    if args.daemon:
        daemon_loop(args.interval)
    else:
        result = asyncio.run(single_run(force=args.force, dry_run=args.dry_run))
        print(json.dumps(result, indent=2, default=str))