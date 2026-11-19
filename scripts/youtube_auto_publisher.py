#!/usr/bin/env python3
"""YouTube Auto-Publisher Worker — publishes eligible Shorts on schedule.

Runs as a background daemon or via cron. Reads publish_queue.json,
respects daily limits (max 3/day), checks for duplicates, and uploads
via YouTube Data API v3 using stored OAuth tokens.

Usage:
    python scripts/youtube_auto_publisher.py              # single run
    python scripts/youtube_auto_publisher.py --daemon     # loop every 30min
    python scripts/youtube_auto_publisher.py --interval 1800  # custom interval
"""

import argparse
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

QUEUE_FILE = PROJECT_ROOT / "data" / "scheduler" / "publish_queue.json"
STATS_FILE = PROJECT_ROOT / "data" / "scheduler" / "daily_stats.json"
PUBLISH_LOG = PROJECT_ROOT / "data" / "publishing" / "auto_publish_log.json"
TOKEN_PATH = PROJECT_ROOT / "data" / "credentials" / "leonidagta6flashbr" / "youtube_oauth.json"
EXPECTED_CHANNEL_ID = "UCQZkEbFYWN2ReXeH-ZZvQEA"

BRAZIL_TZ = timezone(timedelta(hours=-3))


def load_queue() -> dict:
    if QUEUE_FILE.exists():
        try:
            return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_queue(queue: dict) -> None:
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")


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


def get_today_key(profile_id: str) -> str:
    today = datetime.now(BRAZIL_TZ).strftime("%Y-%m-%d")
    return f"{profile_id}:{today}"


def get_published_today_count(stats: dict, profile_id: str) -> int:
    key = get_today_key(profile_id)
    entry = stats.get(key, {})
    return entry.get("approved", 0)


def is_scheduled_hour(schedule_hours: list[int]) -> bool:
    """Check if current hour in Brazil timezone matches a scheduled slot."""
    now = datetime.now(BRAZIL_TZ)
    return now.hour in schedule_hours


def get_credentials():
    """Load and refresh OAuth credentials."""
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

    if not TOKEN_PATH.exists():
        logger.error("Token file not found: %s", TOKEN_PATH)
        return None

    data = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    data["client_id"] = os.environ.get("YOUTUBE_CLIENT_ID", "")
    data["client_secret"] = os.environ.get("YOUTUBE_CLIENT_SECRET", "")

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    creds = Credentials.from_authorized_user_info(data)
    if not creds.valid:
        if creds.refresh_token:
            creds.refresh(Request())
            # Save refreshed token
            data["token"] = creds.token
            if creds.expiry:
                data["expiry"] = creds.expiry.isoformat()
            TOKEN_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
            logger.info("OAuth token refreshed successfully")
        else:
            logger.error("Token expired and no refresh token available")
            return None

    return creds


def verify_channel(creds) -> tuple[bool, str]:
    """Verify authenticated channel matches expected channel ID."""
    from googleapiclient.discovery import build
    youtube = build("youtube", "v3", credentials=creds)
    response = youtube.channels().list(part="snippet", mine=True).execute()
    items = response.get("items", [])
    if not items:
        return False, "No channel found for authenticated user"
    channel_id = items[0]["id"]
    channel_title = items[0].get("snippet", {}).get("title", "Unknown")
    if channel_id != EXPECTED_CHANNEL_ID:
        return False, f"Channel mismatch: got {channel_id}, expected {EXPECTED_CHANNEL_ID}"
    return True, channel_title


def upload_video(creds, video_path: str, title: str, description: str, tags: list[str]) -> dict:
    """Upload video to YouTube via Data API v3."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title[:100],  # YouTube title limit
            "description": description[:5000],
            "tags": tags[:30],
            "categoryId": "20",  # Gaming
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info("Upload progress: %.1f%%", status.progress() * 100)

    video_id = response.get("id", "")
    return {"video_id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}"}


def generate_metadata(video_filename: str) -> tuple[str, str, list[str]]:
    """Generate title, description and tags from video filename."""
    base = video_filename.replace("_br_reels.mp4", "").replace("_", " ")
    title = f"GTA VI Novidades - Leonida GTA VI Flash BR #Shorts"
    description = (
        f"Novidades sobre GTA VI! 🎮\n\n"
        f"Inscreva-se no canal @leonidagta6flashbr para mais conteúdo diário!\n\n"
        f"#GTA6 #GTAVI #Leonida #Shorts #GTA #RockstarGames"
    )
    tags = ["GTA VI", "GTA 6", "Leonida", "Shorts", "GTA", "Rockstar Games", "GTA VI News"]
    return title, description, tags


def single_run(force: bool = False) -> dict:
    """Execute one publish cycle."""
    queue = load_queue()
    if not queue:
        logger.warning("No publish queue found")
        return {"published": 0, "error": "no_queue"}

    if not queue.get("auto_publish", False) and not force:
        logger.info("Auto-publish disabled, skipping")
        return {"published": 0, "reason": "auto_publish_disabled"}

    # Check pause flag
    if queue.get("paused", False) and not force:
        reason = queue.get("pause_reason", "unknown")
        logger.info("Publisher paused (reason: %s), skipping", reason)
        return {"published": 0, "reason": "paused", "pause_reason": reason}

    profile_id = queue.get("profile_id", "leonidagta6flashbr")
    max_per_day = queue.get("max_per_day", 3)
    schedule_hours = queue.get("schedule_hours", [11, 16, 20])
    pending = queue.get("pending", [])

    # Check schedule (skip if not in scheduled hour and not forced)
    if not force and not is_scheduled_hour(schedule_hours):
        next_hour = min(h for h in schedule_hours if h > datetime.now(BRAZIL_TZ).hour) if any(
            h > datetime.now(BRAZIL_TZ).hour for h in schedule_hours
        ) else schedule_hours[0]
        logger.info("Not in scheduled hour. Next slot: %dh", next_hour)
        return {"published": 0, "reason": "not_scheduled_hour", "next_hour": next_hour}

    # Check daily limit
    stats = load_daily_stats()
    published_today = get_published_today_count(stats, profile_id)
    if published_today >= max_per_day:
        logger.info("Daily limit reached (%d/%d)", published_today, max_per_day)
        return {"published": 0, "reason": "daily_limit_reached", "count": published_today}

    if not pending:
        logger.info("No pending videos in queue")
        return {"published": 0, "reason": "no_pending_videos"}

    # Get credentials and verify channel
    creds = get_credentials()
    if not creds:
        return {"published": 0, "error": "credentials_failed"}

    channel_ok, channel_info = verify_channel(creds)
    if not channel_ok:
        logger.error("Channel verification failed: %s", channel_info)
        return {"published": 0, "error": channel_info}

    logger.info("Channel verified: %s", channel_info)

    # Publish next video (with dedup by content hash)
    import hashlib
    video_path = pending[0]
    if not Path(video_path).exists():
        logger.warning("Video file not found: %s", video_path)
        queue["pending"] = pending[1:]
        save_queue(queue)
        return {"published": 0, "error": "file_not_found"}

    # Deduplication: skip if same content already published
    published_hashes = set(queue.get("published_hashes", []))
    file_hash = hashlib.sha256(Path(video_path).read_bytes()).hexdigest()[:16]
    if file_hash in published_hashes:
        logger.info("Skipping duplicate content (hash=%s): %s", file_hash, Path(video_path).name)
        queue["pending"] = pending[1:]
        save_queue(queue)
        return {"published": 0, "reason": "duplicate_content", "hash": file_hash}

    video_filename = Path(video_path).name
    title, description, tags = generate_metadata(video_filename)

    try:
        result = upload_video(creds, video_path, title, description, tags)
        video_id = result.get("video_id", "")

        if not video_id:
            logger.error("Upload returned no video_id")
            return {"published": 0, "error": "upload_failed"}

        logger.info("Published: %s -> %s", video_filename, result["url"])

        # Update queue: remove from pending, add to published_today, record hash
        queue["pending"] = pending[1:]
        published_entry = {
            "video_id": video_id,
            "file": video_filename,
            "published_at": time.time(),
            "url": result["url"],
            "content_hash": file_hash,
        }
        queue.setdefault("published_today", []).append(published_entry)
        queue.setdefault("published_hashes", []).append(file_hash)
        save_queue(queue)

        # Update daily stats
        key = get_today_key(profile_id)
        if key not in stats:
            stats[key] = {"date": datetime.now(BRAZIL_TZ).strftime("%Y-%m-%d"), "profile_id": profile_id, "candidates": 0, "approved": 0, "failed": 0}
        stats[key]["approved"] = stats[key].get("approved", 0) + 1
        stats[key]["candidates"] = stats[key].get("candidates", 0) + 1
        stats[key].setdefault("published_videos", []).append(video_id)
        stats[key]["last_publish_at"] = time.time()
        save_daily_stats(stats)

        # Append to publish log
        log_entries = []
        if PUBLISH_LOG.exists():
            try:
                log_entries = json.loads(PUBLISH_LOG.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                log_entries = []
        log_entries.append({
            "platform": "youtube",
            "video_id": video_id,
            "file": video_filename,
            "title": title,
            "url": result["url"],
            "channel_id": EXPECTED_CHANNEL_ID,
            "published_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "method": "auto_scheduler",
        })
        PUBLISH_LOG.parent.mkdir(parents=True, exist_ok=True)
        PUBLISH_LOG.write_text(json.dumps(log_entries, ensure_ascii=False, indent=2), encoding="utf-8")

        return {"published": 1, "video_id": video_id, "url": result["url"]}

    except Exception as e:
        logger.error("Upload failed: %s", e)
        # Record failure in stats
        key = get_today_key(profile_id)
        if key not in stats:
            stats[key] = {"date": datetime.now(BRAZIL_TZ).strftime("%Y-%m-%d"), "profile_id": profile_id, "candidates": 0, "approved": 0, "failed": 0}
        stats[key]["failed"] = stats[key].get("failed", 0) + 1
        save_daily_stats(stats)
        return {"published": 0, "error": str(e)[:200]}


def daemon_loop(interval: int = 1800) -> None:
    """Run publish cycles in a loop."""
    logger.info("YouTube auto-publisher daemon started (interval=%ds)", interval)
    while True:
        try:
            result = single_run()
            logger.info("Cycle result: %s", json.dumps(result))
        except KeyboardInterrupt:
            logger.info("Publisher stopped by user")
            break
        except Exception as e:
            logger.error("Publisher cycle error: %s", e)
        time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="JHC YouTube Auto-Publisher")
    parser.add_argument("--daemon", action="store_true", help="Run in daemon mode")
    parser.add_argument("--interval", type=int, default=1800, help="Check interval in seconds")
    parser.add_argument("--force", action="store_true", help="Force publish regardless of schedule")
    args = parser.parse_args()

    if args.daemon:
        daemon_loop(args.interval)
    else:
        result = single_run(force=args.force)
        print(json.dumps(result, indent=2))