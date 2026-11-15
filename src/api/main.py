"""JHC Viral Engine — FastAPI Backend.

REST API exposing all engine capabilities to the React frontend.
Endpoints consume real SQLite data, SmartMediaLibrary, TopicSelector,
MediaDirector, and ReelTemplates — no mocks or fake arrays.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

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

# --- Security: API Key Authentication Middleware ---
# Set JHC_API_KEY env var to enable auth. Without it, all routes are open (local dev).
# In production (Render), this MUST be set to prevent unauthorized access.
API_KEY = os.environ.get("JHC_API_KEY", "")

# Routes that never require authentication
PUBLIC_PATHS = {"/", "/api/health", "/docs", "/openapi.json", "/redoc"}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Global middleware: rejects unauthenticated requests to protected /api/* routes."""

    async def dispatch(self, request: Request, call_next):
        # Skip auth if no key configured (local dev mode)
        if not API_KEY:
            return await call_next(request)

        # Skip auth for public routes
        path = request.url.path
        if path in PUBLIC_PATHS or not path.startswith("/api/"):
            return await call_next(request)

        # Check X-API-Key header or ?api_key= query param
        provided = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        if not provided or not secrets.compare_digest(provided, API_KEY):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key. Set X-API-Key header."},
            )

        return await call_next(request)


app.add_middleware(ApiKeyMiddleware)

# Restrict CORS to Netlify domain in production; allow all in local dev
_allowed_origins = (
    ["https://jhc-viral-engine.netlify.app"]
    if os.environ.get("JHC_ENV") == "production"
    else ["*"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Shared State ---

DATA_ROOT = Path(os.environ.get("JHC_DATA_ROOT", "data"))
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


# --- Branding / Watermark Studio ---

@app.get("/api/branding/configs")
async def get_branding_configs():
    """Get watermark configurations for all profiles."""
    from src.production.watermark import WatermarkEngine
    engine = WatermarkEngine(DATA_ROOT)
    return engine.get_all_configs()


@app.get("/api/branding/config/{profile_id}")
async def get_branding_config(profile_id: str):
    """Get watermark configuration for a specific profile."""
    from src.production.watermark import WatermarkEngine
    engine = WatermarkEngine(DATA_ROOT)
    config = engine.get_config(profile_id)
    return config.to_dict()


@app.put("/api/branding/config/{profile_id}")
async def update_branding_config(
    profile_id: str,
    position: str = Query("bottom_right"),
    scale_percent: float = Query(12.0, ge=5.0, le=50.0),
    opacity: float = Query(0.9, ge=0.1, le=1.0),
    margin_px: int = Query(25, ge=0, le=100),
    platform_preset: str = Query("universal"),
    enabled: bool = Query(True),
):
    """Update watermark configuration for a profile."""
    from src.production.watermark import WatermarkEngine, WatermarkConfig
    engine = WatermarkEngine(DATA_ROOT)
    current = engine.get_config(profile_id)
    updated = WatermarkConfig(
        profile_id=profile_id,
        logo_path=current.logo_path,
        position=position,
        scale_percent=scale_percent,
        opacity=opacity,
        margin_px=margin_px,
        enabled=enabled,
        platform_preset=platform_preset,
    )
    engine.update_config(updated)
    return updated.to_dict()


@app.get("/api/branding/preview/{profile_id}")
async def preview_watermark_position(
    profile_id: str,
    video_width: int = Query(1080),
    video_height: int = Query(1920),
):
    """Get computed overlay coordinates for preview without rendering."""
    from src.production.watermark import WatermarkEngine
    engine = WatermarkEngine(DATA_ROOT)
    return engine.preview_position(profile_id, video_width, video_height)


@app.post("/api/branding/logo/{profile_id}")
async def upload_logo(profile_id: str, file_path: str = Query(..., description="Absolute path to logo file on server")):
    """Register a logo file for a profile (file must already exist on server)."""
    from src.production.watermark import WatermarkEngine
    engine = WatermarkEngine(DATA_ROOT)
    source = Path(file_path)
    if not source.exists():
        raise HTTPException(status_code=400, detail=f"File not found: {file_path}")
    try:
        dest = engine.save_logo(profile_id, source)
        return {"status": "saved", "logo_path": str(dest), "profile_id": profile_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/branding/apply/{profile_id}")
async def apply_watermark(
    profile_id: str,
    input_path: str = Query(..., description="Absolute path to input video"),
    force: bool = Query(False),
):
    """Apply watermark to a single video file."""
    from src.production.watermark import WatermarkEngine
    engine = WatermarkEngine(DATA_ROOT)
    inp = Path(input_path)
    if not inp.exists():
        raise HTTPException(status_code=400, detail=f"Input file not found: {input_path}")
    out_dir = engine.exports_dir / profile_id
    out_path = out_dir / f"{inp.stem}_branded{inp.suffix}"
    result = await engine.apply_watermark(inp, out_path, profile_id, force=force)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Unknown error"))
    return result


# --- Publishing / Central de Publicações ---

@app.get("/api/publishing/status")
async def get_publishing_status():
    """Get overall publishing queue summary and connection states."""
    from src.publishing.adapters import PublishQueue, get_adapter, ADAPTERS
    queue = PublishQueue(DATA_ROOT)
    summary = queue.get_queue_summary()

    # Check connection state for each platform × active profile
    connections = {}
    for pid in ["gta6-br", "gta6-global"]:
        connections[pid] = {}
        for platform in ADAPTERS:
            adapter = get_adapter(platform, DATA_ROOT, pid)
            state = await adapter.check_connection()
            connections[pid][platform] = state.value

    return {"queue": summary, "connections": connections}


@app.get("/api/publishing/jobs/{profile_id}")
async def list_publish_jobs(profile_id: str, limit: int = Query(30, ge=1, le=100)):
    """List recent publish jobs for a profile across all platforms."""
    from src.publishing.adapters import PublishQueue
    queue = PublishQueue(DATA_ROOT)
    pending = queue.get_pending_jobs(limit=limit)
    # Filter by profile_id
    profile_jobs = [j.to_dict() for j in pending if j.profile_id == profile_id]
    return profile_jobs


@app.post("/api/publishing/schedule")
async def schedule_publish(
    profile_id: str = Query(...),
    platform: str = Query(...),
    video_path: str = Query(...),
    title: str = Query(...),
    description: str = Query(""),
    hashtags: str = Query("", description="Comma-separated hashtags"),
    scheduled_at: Optional[float] = Query(None, description="Unix timestamp for scheduled publish"),
):
    """Schedule a video for publishing to a specific platform."""
    import uuid
    from src.publishing.adapters import PublishQueue, PublishJob, PublishState, ADAPTERS

    if platform not in ADAPTERS:
        raise HTTPException(status_code=400, detail=f"Unknown platform: {platform}. Available: {list(ADAPTERS.keys())}")

    if not Path(video_path).exists():
        raise HTTPException(status_code=400, detail=f"Video file not found: {video_path}")

    tags = tuple(h.strip() for h in hashtags.split(",") if h.strip()) if hashtags else ()

    job = PublishJob(
        job_id=str(uuid.uuid4())[:8],
        profile_id=profile_id,
        platform=platform,
        video_path=video_path,
        title=title,
        description=description,
        hashtags=tags,
        scheduled_at=scheduled_at,
        state=PublishState.NOT_CONFIGURED.value,
    )

    queue = PublishQueue(DATA_ROOT)
    queue.add_job(job)

    return {"status": "scheduled", "job_id": job.job_id, "job": job.to_dict()}


@app.get("/api/publishing/connection/{profile_id}/{platform}")
async def check_connection(profile_id: str, platform: str):
    """Check connection status for a specific profile + platform via OAuthManager."""
    from src.publishing.oauth import OAuthManager
    manager = OAuthManager(DATA_ROOT)
    return manager.get_connection_state(profile_id, platform)

# --- OAuth Flow Endpoints (PRIORIDADE 2) ---

@app.get("/api/oauth/start/{profile_id}/{platform}")
async def oauth_start(
    profile_id: str,
    platform: str,
    redirect_base: str = Query("http://127.0.0.1:8765"),
):
    """Generate OAuth authorization URL with PKCE for profile + platform."""
    from src.publishing.oauth import OAuthManager
    manager = OAuthManager(DATA_ROOT)
    result = manager.get_auth_url(profile_id, platform, redirect_base)
    if "error" in result and "url" not in result:
        raise HTTPException(status_code=400, detail=result.get("error", "OAuth setup error"))
    return result

@app.get("/api/oauth/callback/{platform}")
async def oauth_callback(
    platform: str,
    code: str = Query(..., description="Authorization code from provider"),
    state: str = Query(..., description="PKCE state token"),
):
    """Exchange authorization code for tokens and store credentials."""
    from src.publishing.oauth import OAuthManager
    manager = OAuthManager(DATA_ROOT)
    result = await manager.handle_callback(platform, code, state)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@app.post("/api/oauth/disconnect/{profile_id}/{platform}")
async def oauth_disconnect(profile_id: str, platform: str):
    """Remove stored OAuth credentials for profile + platform."""
    from src.publishing.oauth import OAuthManager
    manager = OAuthManager(DATA_ROOT)
    removed = manager.disconnect(profile_id, platform)
    if not removed:
        raise HTTPException(status_code=404, detail="No credentials found")
    return {"status": "disconnected", "profile_id": profile_id, "platform": platform}

@app.get("/api/oauth/connections")
async def get_all_oauth_connections():
    """Get connection states for all active profiles × all platforms."""
    from src.publishing.oauth import OAuthManager
    manager = OAuthManager(DATA_ROOT)
    return manager.get_all_connections(["gta6-br", "gta6-global"])

# --- AutoPublish Scheduler Endpoints (PRIORIDADE 3+4) ---

@app.get("/api/autopublish/status")
async def autopublish_status():
    """Get AutoPublishScheduler status summary."""
    from src.automation.autopublish_scheduler import AutoPublishScheduler
    scheduler = AutoPublishScheduler(DATA_ROOT)
    return scheduler.get_status_summary()

@app.post("/api/autopublish/submit")
async def autopublish_submit(
    profile_id: str = Query(...),
    platform: str = Query(...),
    video_path: str = Query(...),
    title: str = Query(...),
    description: str = Query(""),
    hashtags: str = Query(""),
    scheduled_at: Optional[float] = Query(None),
):
    """Submit a new auto-publish job with idempotency and dedup checks."""
    import uuid
    from src.automation.autopublish_scheduler import AutoPublishScheduler, AutoPublishJob
    scheduler = AutoPublishScheduler(DATA_ROOT)
    tags = tuple(h.strip() for h in hashtags.split(",") if h.strip()) if hashtags else ()
    job = AutoPublishJob(
        job_id=str(uuid.uuid4())[:8],
        profile_id=profile_id,
        platform=platform,
        video_path=video_path,
        title=title,
        description=description,
        hashtags=tags,
        scheduled_at=scheduled_at,
    )
    return scheduler.submit_job(job)

@app.get("/api/autopublish/jobs")
async def autopublish_list_jobs(
    profile_id: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List active auto-publish jobs with optional filters."""
    from src.automation.autopublish_scheduler import AutoPublishScheduler
    scheduler = AutoPublishScheduler(DATA_ROOT)
    return scheduler.list_jobs(profile_id=profile_id, state=state, limit=limit)

@app.get("/api/autopublish/history")
async def autopublish_history(
    profile_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """Get historical completed/failed/cancelled publish jobs."""
    from src.automation.autopublish_scheduler import AutoPublishScheduler
    scheduler = AutoPublishScheduler(DATA_ROOT)
    return scheduler.get_history(profile_id=profile_id, limit=limit)

@app.post("/api/autopublish/approve/{job_id}")
async def autopublish_approve(
    job_id: str,
    score: float = Query(0.0, ge=0.0, le=1.0),
):
    """Approve a job via QualityGate (required before publishing)."""
    from src.automation.autopublish_scheduler import AutoPublishScheduler
    scheduler = AutoPublishScheduler(DATA_ROOT)
    return scheduler.check_quality_gate(job_id, passed=True, score=score)

@app.post("/api/autopublish/reject/{job_id}")
async def autopublish_reject(
    job_id: str,
    score: float = Query(0.0, ge=0.0, le=1.0),
):
    """Reject a job via QualityGate."""
    from src.automation.autopublish_scheduler import AutoPublishScheduler
    scheduler = AutoPublishScheduler(DATA_ROOT)
    return scheduler.check_quality_gate(job_id, passed=False, score=score)

@app.post("/api/autopublish/auth-check/{job_id}")
async def autopublish_auth_check(
    job_id: str,
    auth_state: str = Query(..., description="connected|auth_required|token_expired"),
):
    """Update auth state for a job — blocks publishing if not connected."""
    from src.automation.autopublish_scheduler import AutoPublishScheduler
    scheduler = AutoPublishScheduler(DATA_ROOT)
    return scheduler.check_auth(job_id, auth_state)

@app.post("/api/autopublish/cancel/{job_id}")
async def autopublish_cancel(job_id: str):
    """Cancel a pending or approved publish job."""
    from src.automation.autopublish_scheduler import AutoPublishScheduler
    scheduler = AutoPublishScheduler(DATA_ROOT)
    return scheduler.cancel_job(job_id)

@app.post("/api/autopublish/reschedule/{job_id}")
async def autopublish_reschedule(
    job_id: str,
    scheduled_at: float = Query(..., description="New Unix timestamp"),
):
    """Reschedule a pending or approved publish job."""
    from src.automation.autopublish_scheduler import AutoPublishScheduler
    scheduler = AutoPublishScheduler(DATA_ROOT)
    return scheduler.reschedule_job(job_id, scheduled_at)

@app.get("/api/autopublish/eligible")
async def autopublish_eligible(limit: int = Query(10, ge=1, le=50)):
    """Get jobs eligible for publishing right now (approved + auth connected + scheduled)."""
    from src.automation.autopublish_scheduler import AutoPublishScheduler
    scheduler = AutoPublishScheduler(DATA_ROOT)
    jobs = scheduler.get_eligible_jobs(limit=limit)
    return [j.to_dict() for j in jobs]

@app.get("/api/autopublish/launchd")
async def autopublish_launchd_status():
    """Get launchd integration status (disabled by default)."""
    from src.automation.autopublish_scheduler import AutoPublishScheduler
    scheduler = AutoPublishScheduler(DATA_ROOT)
    return scheduler.get_launchd_status()

# --- Thumbnail Engine Endpoints (ONDA P0) ---

@app.get("/api/thumbnails/formats")
async def thumbnail_formats(platform: Optional[str] = Query(None)):
    """List available thumbnail formats, optionally filtered by platform."""
    from src.production.thumbnail_engine import ThumbnailEngine
    engine = ThumbnailEngine(DATA_ROOT)
    return engine.list_formats(platform)

@app.get("/api/thumbnails/templates")
async def thumbnail_templates():
    """List available thumbnail templates."""
    from src.production.thumbnail_engine import ThumbnailEngine
    engine = ThumbnailEngine(DATA_ROOT)
    return engine.list_templates()

@app.post("/api/thumbnails/generate")
async def generate_thumbnail(
    content_id: str = Query(...),
    profile_id: str = Query(...),
    platform: str = Query(...),
    format_type: str = Query(...),
    title: str = Query(...),
    source_video_path: Optional[str] = Query(None),
    source_image_path: Optional[str] = Query(None),
    template: str = Query("news_urgent"),
    variant: str = Query("A"),
    frame_timestamp: float = Query(0.0),
):
    """Generate a single thumbnail for a piece of content."""
    from src.production.thumbnail_engine import ThumbnailEngine, ThumbnailRequest
    engine = ThumbnailEngine(DATA_ROOT)
    request = ThumbnailRequest(
        content_id=content_id,
        profile_id=profile_id,
        platform=platform,
        format_type=format_type,
        title=title,
        source_video_path=source_video_path,
        source_image_path=source_image_path,
        template=template,
        variant=variant,
        frame_timestamp=frame_timestamp,
    )
    result = await engine.generate(request)
    if not result.valid and result.errors:
        raise HTTPException(status_code=500, detail=result.errors[0])
    return result.to_dict()

@app.post("/api/thumbnails/generate-variants")
async def generate_thumbnail_variants(
    content_id: str = Query(...),
    profile_id: str = Query(...),
    platform: str = Query(...),
    format_type: str = Query(...),
    title: str = Query(...),
    source_video_path: Optional[str] = Query(None),
    source_image_path: Optional[str] = Query(None),
    template: str = Query("news_urgent"),
    frame_timestamp: float = Query(0.0),
):
    """Generate up to 3 thumbnail variants (A/B/C) for the same content."""
    from src.production.thumbnail_engine import ThumbnailEngine, ThumbnailRequest
    engine = ThumbnailEngine(DATA_ROOT)
    request = ThumbnailRequest(
        content_id=content_id,
        profile_id=profile_id,
        platform=platform,
        format_type=format_type,
        title=title,
        source_video_path=source_video_path,
        source_image_path=source_image_path,
        template=template,
        frame_timestamp=frame_timestamp,
    )
    results = await engine.generate_variants(request)
    return [r.to_dict() for r in results]

@app.get("/api/thumbnails/history")
async def thumbnail_history(
    profile_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """Get thumbnail generation history."""
    from src.production.thumbnail_engine import ThumbnailEngine
    engine = ThumbnailEngine(DATA_ROOT)
    return engine.get_history(profile_id=profile_id, limit=limit)


# =============================================================================
# MISSÃO 014 — Laboratório de Referências
# =============================================================================

@app.post("/api/references/analyze")
async def analyze_reference_video(request: Request):
    """Analisa um vídeo de referência e extrai padrões visuais/temporais."""
    from src.research.reference_lab import ReferenceLab
    body = await request.json()
    video_path = body.get("video_path", "")
    if not video_path:
        return JSONResponse(status_code=400, content={"detail": "video_path é obrigatório"})
    lab = ReferenceLab(DATA_ROOT)
    try:
        analysis = lab.analyze_video(video_path)
        from dataclasses import asdict
        return asdict(analysis)
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={"detail": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Erro na análise: {str(e)}"})


@app.get("/api/references/list")
async def list_references():
    """Lista todas as análises de referência salvas."""
    from src.research.reference_lab import ReferenceLab
    lab = ReferenceLab(DATA_ROOT)
    return lab.list_analyses()


@app.get("/api/references/blueprint/{name}")
async def get_blueprint(name: str):
    """Retorna o blueprint de uma referência analisada."""
    from src.research.reference_lab import ReferenceLab
    lab = ReferenceLab(DATA_ROOT)
    bp_path = lab.blueprints_dir / f"{name}_blueprint.json"
    if not bp_path.exists():
        return JSONResponse(status_code=404, content={"detail": f"Blueprint '{name}' não encontrado"})
    import json as _json
    return _json.loads(bp_path.read_text(encoding="utf-8"))

# =============================================================================
# MISSÃO 015 — Smart Clipper
# =============================================================================

@app.post("/api/clips/extract")
async def extract_clips(request: Request):
    """Extrai clipes virais de um vídeo longo."""
    from src.media.smart_clipper import SmartClipper
    body = await request.json()
    video_path = body.get("video_path", "")
    if not video_path:
        return JSONResponse(status_code=400, content={"detail": "video_path é obrigatório"})
    clipper = SmartClipper(DATA_ROOT)
    try:
        result = clipper.extract_clips(
            video_path,
            target_duration=body.get("target_duration", 30),
            max_clips=body.get("max_clips", 5),
            platform=body.get("platform", "reels"),
            min_score=body.get("min_score", 0.3),
        )
        from dataclasses import asdict
        return asdict(result)
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={"detail": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Erro na extração: {str(e)}"})


@app.get("/api/clips/list")
async def list_clips():
    """Lista todos os clipes extraídos."""
    from src.media.smart_clipper import SmartClipper
    clipper = SmartClipper(DATA_ROOT)
    return clipper.list_clips()
