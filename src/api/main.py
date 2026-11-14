"""JHC Viral Engine — FastAPI Backend.

REST API exposing all engine capabilities to the React frontend.
Endpoints consume real SQLite data, SmartMediaLibrary, TopicSelector,
MediaDirector, and ReelTemplates — no mocks or fake arrays.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.core.profile_config import ALL_PROFILES, get_profile, list_profiles
from src.media.library import SmartMediaLibrary, VIDEO_EXTENSIONS
from src.media.video_selector import SmartVideoSelector
from src.editorial.topic_selector import TopicSelector, TopicCandidate
from src.production.reel_templates import (
    ALL_TEMPLATES,
    get_template,
    select_template_for_category,
    list_templates,
)
from src.automation.media_director import MediaDirector, JobState
from src.research.trend_hunter import TrendHunter

logger = logging.getLogger(__name__)

# --- App Setup ---

app = FastAPI(
    title="JHC Viral Engine API",
    description="Backend for autonomous content production platform",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Shared State ---

DATA_ROOT = Path("data")
DB_PATH = DATA_ROOT / "media_library.db"
THUMBS_DIR = DATA_ROOT / "thumbnails"

library = SmartMediaLibrary(DB_PATH, THUMBS_DIR)

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"


@app.get("/", include_in_schema=False)
async def serve_frontend():
    """Serve the frontend SPA at root URL."""
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(str(index_path), media_type="text/html")


# --- Response Models ---

class HealthResponse(BaseModel):
    status: str
    version: str
    profiles_count: int
    templates_count: int
    media_files_count: int
    uptime_seconds: float


class ProfileSummary(BaseModel):
    profile_id: str
    name: str
    niche: str
    enabled: bool
    description: str


class TemplateSummary(BaseModel):
    name: str
    description: str
    category: str
    duration: float
    scene_count: int
    requires_media: bool
    music_mood: str


class MediaStatsResponse(BaseModel):
    total_files: int
    corrupt_files: int
    total_size_mb: float
    categories: dict
    rights_statuses: dict


class MediaAssetResponse(BaseModel):
    file_path: str
    file_name: str
    file_size: int
    duration_seconds: Optional[float]
    width: Optional[int]
    height: Optional[int]
    fps: Optional[float]
    codec: Optional[str]
    tags: list[str]
    category: str
    rights_status: str
    thumbnail_path: Optional[str]
    is_corrupt: bool


class IndexRequest(BaseModel):
    directory: str
    recursive: bool = True


class IndexProgressResponse(BaseModel):
    total_files: int
    scanned: int
    indexed: int
    skipped_duplicate: int
    skipped_corrupt: int
    errors: int
    percent: float
    elapsed_seconds: float
    summary: str


class TopicResponse(BaseModel):
    title: str
    source_url: str
    source_name: str
    category: str
    relevance_score: float
    freshness_hours: float
    editorial_score: float
    selected: bool
    rejection_reason: str


class BatchSummaryResponse(BaseModel):
    batch_id: Optional[str]
    profile_id: str
    total_jobs: int
    state_counts: dict
    created_at: Optional[float]


class ReelProductionRequest(BaseModel):
    profile_id: str
    topic: str
    template_name: Optional[str] = None


# --- Startup ---

_start_time = time.time()


@app.on_event("startup")
async def startup():
    logger.info("JHC Viral Engine API starting...")
    stats = library.get_stats()
    logger.info("Media library: %d files indexed", stats["total_files"])


# --- Health & Status ---

@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    stats = library.get_stats()
    return HealthResponse(
        status="operational",
        version="1.0.0",
        profiles_count=len(ALL_PROFILES),
        templates_count=len(ALL_TEMPLATES),
        media_files_count=stats["total_files"],
        uptime_seconds=round(time.time() - _start_time, 1),
    )


# --- Profiles ---

@app.get("/api/profiles", response_model=list[ProfileSummary])
async def get_profiles():
    return [
        ProfileSummary(
            profile_id=p.profile_id,
            name=p.name,
            niche=p.niche,
            enabled=p.enabled,
            description=p.description,
        )
        for p in ALL_PROFILES.values()
    ]


@app.get("/api/profiles/{profile_id}", response_model=ProfileSummary)
async def get_profile_detail(profile_id: str):
    try:
        p = get_profile(profile_id)
        return ProfileSummary(
            profile_id=p.profile_id,
            name=p.name,
            niche=p.niche,
            enabled=p.enabled,
            description=p.description,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")


# --- Templates ---

@app.get("/api/templates", response_model=list[TemplateSummary])
async def get_templates():
    return [
        TemplateSummary(
            name=t["name"],
            description=t["description"],
            category=t["category"],
            duration=t["duration"],
            scene_count=t["scene_count"],
            requires_media=t["requires_media"],
            music_mood=t["music_mood"],
        )
        for t in list_templates()
    ]


@app.get("/api/templates/{name}", response_model=TemplateSummary)
async def get_template_detail(name: str):
    tmpl = get_template(name)
    if not tmpl:
        raise HTTPException(status_code=404, detail=f"Template '{name}' not found")
    return TemplateSummary(
        name=tmpl.name,
        description=tmpl.description,
        category=tmpl.category,
        duration=tmpl.total_duration,
        scene_count=len(tmpl.scenes),
        requires_media=tmpl.requires_media,
        music_mood=tmpl.music_mood,
    )


# --- Media Library ---

@app.get("/api/media/stats", response_model=MediaStatsResponse)
async def media_stats():
    stats = library.get_stats()
    return MediaStatsResponse(
        total_files=stats["total_files"],
        corrupt_files=stats["corrupt_files"],
        total_size_mb=stats["total_size_mb"],
        categories=stats["categories"],
        rights_statuses=stats["rights_statuses"],
    )


@app.get("/api/media/search", response_model=list[MediaAssetResponse])
async def media_search(
    query: str = Query("", description="Search term"),
    category: str = Query("", description="Filter by category"),
    min_duration: float = Query(0.0, description="Minimum duration in seconds"),
    max_duration: float = Query(float("inf"), description="Maximum duration in seconds"),
    rights_status: str = Query("", description="Filter by rights status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    results = library.search(
        query=query or "",
        category=category or "",
        min_duration=min_duration,
        max_duration=max_duration,
        rights_status=rights_status or "",
        limit=limit,
        offset=offset,
    )
    return [
        MediaAssetResponse(
            file_path=a.file_path,
            file_name=a.file_name,
            file_size=a.file_size,
            duration_seconds=a.duration_seconds,
            width=a.width,
            height=a.height,
            fps=a.fps,
            codec=a.codec,
            tags=list(a.tags),
            category=a.category,
            rights_status=a.rights_status,
            thumbnail_path=a.thumbnail_path,
            is_corrupt=a.is_corrupt,
        )
        for a in results
    ]


@app.post("/api/media/index", response_model=IndexProgressResponse)
async def index_media(request: IndexRequest):
    directory = Path(request.directory)
    if not directory.exists():
        raise HTTPException(status_code=400, detail=f"Directory not found: {request.directory}")

    progress = await library.index_directory(directory, recursive=request.recursive)
    return IndexProgressResponse(
        total_files=progress.total_files,
        scanned=progress.scanned,
        indexed=progress.indexed,
        skipped_duplicate=progress.skipped_duplicate,
        skipped_corrupt=progress.skipped_corrupt,
        errors=progress.errors,
        percent=round(progress.percent, 1),
        elapsed_seconds=round(progress.elapsed, 1),
        summary=progress.summary(),
    )


@app.get("/api/media/verify")
async def verify_media():
    return library.verify_files_exist()


@app.get("/api/filesystem/browse")
async def browse_directory(path: str = Query("/", description="Directory path to list")):
    """List subdirectories and video files for pack selection."""
    dir_path = Path(path)
    if not dir_path.exists():
        raise HTTPException(status_code=400, detail=f"Path not found: {path}")
    if not dir_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {path}")

    try:
        entries = []
        for item in sorted(dir_path.iterdir()):
            is_dir = item.is_dir()
            is_video = not is_dir and item.suffix.lower() in VIDEO_EXTENSIONS
            if is_dir or is_video:
                entry = {
                    "name": item.name,
                    "path": str(item),
                    "is_dir": is_dir,
                    "is_video": is_video,
                    "size_mb": round(item.stat().st_size / (1024 * 1024), 1) if not is_dir else None,
                }
                if is_dir:
                    # Non-recursive count to avoid slow rglob on large directories
                    video_count = sum(
                        1 for child in item.iterdir()
                        if child.is_file() and child.suffix.lower() in VIDEO_EXTENSIONS
                    )
                    entry["video_count"] = video_count
                entries.append(entry)

        return {
            "current_path": str(dir_path),
            "parent_path": str(dir_path.parent) if dir_path.parent != dir_path else None,
            "entries": entries[:200],
        }
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {path}")


@app.put("/api/media/{file_path:path}/tags")
async def update_tags(file_path: str, tags: list[str]):
    success = library.update_tags(file_path, tags)
    if not success:
        raise HTTPException(status_code=404, detail="File not found in library")
    return {"status": "updated", "tags": tags}


@app.put("/api/media/{file_path:path}/category")
async def update_category(file_path: str, category: str):
    success = library.update_category(file_path, category)
    if not success:
        raise HTTPException(status_code=404, detail="File not found in library")
    return {"status": "updated", "category": category}


@app.put("/api/media/{file_path:path}/rights")
async def update_rights(file_path: str, rights_status: str):
    try:
        success = library.update_rights_status(file_path, rights_status)
        if not success:
            raise HTTPException(status_code=404, detail="File not found in library")
        return {"status": "updated", "rights_status": rights_status}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/media/thumbnail/{filename}")
async def serve_thumbnail(filename: str):
    thumb_path = THUMBS_DIR / filename
    if not thumb_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(str(thumb_path), media_type="image/jpeg")


# --- Research & Editorial ---

@app.get("/api/research/trends/{profile_id}", response_model=list[TopicResponse])
async def get_trends(profile_id: str, limit: int = Query(10, ge=1, le=50)):
    try:
        profile = get_profile(profile_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")

    hunter = TrendHunter(profile)
    trends = await hunter.discover_trends()

    return [
        TopicResponse(
            title=t.title,
            source_url=getattr(t, "url", ""),
            source_name=getattr(t, "source", "Unknown"),
            category=getattr(t, "category", "news"),
            relevance_score=getattr(t, "relevance_score", 0.5),
            freshness_hours=getattr(t, "freshness_hours", 24.0),
            editorial_score=0.0,
            selected=False,
            rejection_reason="",
        )
        for t in trends[:limit]
    ]


@app.post("/api/editorial/select/{profile_id}", response_model=list[TopicResponse])
async def select_topics(profile_id: str, max_topics: int = Query(5, ge=1, le=10)):
    try:
        profile = get_profile(profile_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")

    hunter = TrendHunter(profile)
    trends = await hunter.discover_trends()

    import hashlib
    selector = TopicSelector(DATA_ROOT, profile_id)
    candidates = []
    for t in trends[:20]:
        content_hash = hashlib.sha256(t.title.encode()).hexdigest()[:16]
        candidates.append(TopicCandidate(
            title=t.title,
            source_url=getattr(t, "url", ""),
            source_name=getattr(t, "source", "Unknown"),
            published_date="2026-11-14",
            category=getattr(t, "category", "news"),
            relevance_score=getattr(t, "relevance_score", 0.5),
            freshness_hours=getattr(t, "freshness_hours", 24.0),
            content_hash=content_hash,
        ))

    queue = selector.select_daily_topics(candidates, max_topics=max_topics)
    return [
        TopicResponse(
            title=t.title,
            source_url=t.source_url,
            source_name=t.source_name,
            category=t.category,
            relevance_score=t.relevance_score,
            freshness_hours=t.freshness_hours,
            editorial_score=round(t.editorial_score, 3),
            selected=t.selected,
            rejection_reason=t.rejection_reason,
        )
        for t in queue.topics
    ]


# --- Production ---

@app.post("/api/production/batch/{profile_id}", response_model=BatchSummaryResponse)
async def create_batch(profile_id: str, max_topics: int = Query(3, ge=1, le=5)):
    try:
        get_profile(profile_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")

    # Get selected topics from editorial queue
    selector = TopicSelector(DATA_ROOT, profile_id)
    queue = selector.load_queue()

    if not queue or not queue.topics:
        # Auto-select if no queue exists
        hunter = TrendHunter(get_profile(profile_id))
        trends = await hunter.discover_trends()
        import hashlib
        candidates = []
        for t in trends[:20]:
            content_hash = hashlib.sha256(t.title.encode()).hexdigest()[:16]
            candidates.append(TopicCandidate(
                title=t.title,
                source_url=getattr(t, "url", ""),
                source_name=getattr(t, "source", "Unknown"),
                published_date="2026-11-14",
                category=getattr(t, "category", "news"),
                relevance_score=getattr(t, "relevance_score", 0.5),
                freshness_hours=getattr(t, "freshness_hours", 24.0),
                content_hash=content_hash,
            ))
        queue = selector.select_daily_topics(candidates, max_topics=max_topics)

    topics = [
        {
            "title": t.title,
            "source_url": t.source_url,
            "source_name": t.source_name,
            "category": t.category,
        }
        for t in queue.topics
    ]

    director = MediaDirector(DATA_ROOT, profile_id)
    batch = director.create_batch(topics)

    summary = director.get_batch_summary()
    return BatchSummaryResponse(
        batch_id=summary.get("batch_id"),
        profile_id=profile_id,
        total_jobs=summary.get("total_jobs", 0),
        state_counts=summary.get("state_counts", {}),
        created_at=summary.get("created_at"),
    )


@app.get("/api/production/batch/{profile_id}", response_model=BatchSummaryResponse)
async def get_batch_status(profile_id: str):
    director = MediaDirector(DATA_ROOT, profile_id)
    summary = director.get_batch_summary()
    if "error" in summary:
        raise HTTPException(status_code=404, detail=summary["error"])
    return BatchSummaryResponse(
        batch_id=summary.get("batch_id"),
        profile_id=profile_id,
        total_jobs=summary.get("total_jobs", 0),
        state_counts=summary.get("state_counts", {}),
        created_at=summary.get("created_at"),
    )


# --- Video Selection ---

@app.post("/api/media/select-for-script")
async def select_clips_for_script(
    script_text: str,
    require_authorized: bool = Query(False),
):
    selector = SmartVideoSelector(library)
    result = selector.select_for_script(
        script_text,
        require_authorized=require_authorized,
    )
    return {
        "clips_count": len(result.clips),
        "scenes_without_media": result.scenes_without_media,
        "coverage_ratio": round(result.coverage_ratio, 2),
        "unique_assets": result.unique_assets,
        "total_duration": round(result.total_duration, 1),
        "warnings": result.warnings,
        "clips": [
            {
                "file_name": c.asset.file_name,
                "file_path": c.asset.file_path,
                "scene_index": c.scene_index,
                "relevance_score": round(c.relevance_score, 3),
                "start_time": round(c.start_time, 1),
                "end_time": round(c.end_time, 1) if c.end_time else None,
                "duration": round(c.duration, 1),
                "segment_reason": c.segment_reason,
            }
            for c in result.clips
        ],
    }


# --- Quality Reports ---

@app.get("/api/quality/reports/{profile_id}")
async def get_quality_reports(profile_id: str):
    quality_dir = DATA_ROOT / profile_id / "quality"
    if not quality_dir.exists():
        return []

    reports = []
    for f in sorted(quality_dir.glob("*.json"), reverse=True)[:20]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            reports.append(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
    return reports


# --- Output Files ---

@app.get("/api/output/{profile_id}/{filename}")
async def serve_output(profile_id: str, filename: str):
    output_path = DATA_ROOT / profile_id / "output" / filename
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(output_path), media_type="video/mp4")


# --- Scheduler & Automation ---

@app.get("/api/scheduler/status")
async def get_scheduler_status():
    """Get overall scheduler status with quotas and daily stats for all active profiles."""
    from src.automation.scheduler import ProductionScheduler
    scheduler = ProductionScheduler(DATA_ROOT)
    return scheduler.get_scheduler_status()


@app.get("/api/scheduler/quota/{profile_id}")
async def get_quota(profile_id: str):
    """Get production quota for a specific profile."""
    from src.automation.scheduler import ProductionScheduler
    scheduler = ProductionScheduler(DATA_ROOT)
    quota = scheduler.get_quota(profile_id)
    return quota.to_dict()


@app.put("/api/scheduler/quota/{profile_id}")
async def update_quota(
    profile_id: str,
    max_candidates_per_day: int = Query(5, ge=1, le=20),
    max_approved_per_day: int = Query(3, ge=1, le=10),
    enabled: bool = Query(True),
):
    """Update production quota for a profile."""
    from src.automation.scheduler import ProductionScheduler, DailyQuota
    scheduler = ProductionScheduler(DATA_ROOT)
    current = scheduler.get_quota(profile_id)
    updated = DailyQuota(
        profile_id=profile_id,
        max_candidates_per_day=max_candidates_per_day,
        max_approved_per_day=max_approved_per_day,
        min_quality_score=current.min_quality_score,
        require_authorized_media=current.require_authorized_media,
        enabled=enabled,
    )
    scheduler.update_quota(updated)
    return updated.to_dict()


@app.get("/api/scheduler/calendar/{profile_id}")
async def get_calendar(
    profile_id: str,
    start_date: str = Query(None, description="YYYY-MM-DD"),
    end_date: str = Query(None, description="YYYY-MM-DD"),
):
    """Get calendar entries for a profile within a date range."""
    from src.automation.scheduler import ProductionScheduler
    from datetime import date, timedelta
    scheduler = ProductionScheduler(DATA_ROOT)
    if not start_date:
        start_date = date.today().isoformat()
    if not end_date:
        end_date = (date.today() + timedelta(days=30)).isoformat()
    entries = scheduler.get_calendar_entries(profile_id, start_date, end_date)
    return [e.to_dict() for e in entries]


@app.get("/api/scheduler/can-produce/{profile_id}")
async def can_produce(profile_id: str):
    """Check if a profile can produce more content today."""
    from src.automation.scheduler import ProductionScheduler
    scheduler = ProductionScheduler(DATA_ROOT)
    can, reason = scheduler.can_produce_today(profile_id)
    return {"can_produce": can, "reason": reason}