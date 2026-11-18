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
from src.api.auth import create_jwt, verify_jwt, get_jwt_secret, validate_dashboard_credentials

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
# Auth routes that do NOT require prior authentication (login/logout are self-validating)
OPEN_AUTH_PATHS = {"/api/auth/login"}
# Auth routes that DO require a valid JWT session (me, logout need authenticated user)
SESSION_AUTH_PATHS = {"/api/auth/me", "/api/auth/logout"}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Global middleware: accepts JWT Bearer token OR API key for /api/* routes."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip auth for public routes and non-API paths
        if path in PUBLIC_PATHS or not path.startswith("/api/"):
            return await call_next(request)

        # Open auth endpoints (login) — no prior auth needed
        if path in OPEN_AUTH_PATHS:
            return await call_next(request)

        # Session auth endpoints (/api/auth/me, /api/auth/logout) — MUST validate JWT
        if path in SESSION_AUTH_PATHS:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
                payload = verify_jwt(token, get_jwt_secret())
                if payload:
                    request.state.user = payload
                    return await call_next(request)
            # Also check httpOnly cookie as fallback
            cookie_token = request.cookies.get("jhc_session")
            if cookie_token:
                payload = verify_jwt(cookie_token, get_jwt_secret())
                if payload:
                    request.state.user = payload
                    return await call_next(request)
            return JSONResponse(
                status_code=401,
                content={"detail": "Session expired or invalid. Please login again."},
            )

        # Skip auth entirely if no key configured (local dev mode)
        if not API_KEY:
            return await call_next(request)

        # 1. Try JWT Bearer token first (dashboard sessions)
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            payload = verify_jwt(token, get_jwt_secret())
            if payload:
                request.state.user = payload
                return await call_next(request)

        # Also check httpOnly cookie for regular API routes
        cookie_token = request.cookies.get("jhc_session")
        if cookie_token:
            payload = verify_jwt(cookie_token, get_jwt_secret())
            if payload:
                request.state.user = payload
                return await call_next(request)

        # 2. Fall back to API key header (programmatic access)
        provided = request.headers.get("X-API-Key")
        if os.environ.get("JHC_ENV") != "production":
            provided = provided or request.query_params.get("api_key")
        if provided and secrets.compare_digest(provided, API_KEY):
            return await call_next(request)

        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required. Login via /api/auth/login or provide X-API-Key header."},
        )


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


# --- AutoPublish Queue Control ---

@app.get("/api/queue/status")
async def get_queue_status():
    """Get autopublish queue control status."""
    from src.automation.autopublish_scheduler import AutoPublishScheduler
    s = AutoPublishScheduler(DATA_ROOT)
    return s.get_queue_status()

@app.post("/api/queue/start")
async def start_queue():
    """Start the autopublish queue."""
    from src.automation.autopublish_scheduler import AutoPublishScheduler
    s = AutoPublishScheduler(DATA_ROOT)
    return s.start_queue()

@app.post("/api/queue/pause")
async def pause_queue():
    """Pause the autopublish queue."""
    from src.automation.autopublish_scheduler import AutoPublishScheduler
    s = AutoPublishScheduler(DATA_ROOT)
    return s.pause_queue()

@app.post("/api/queue/resume")
async def resume_queue():
    """Resume a paused autopublish queue."""
    from src.automation.autopublish_scheduler import AutoPublishScheduler
    s = AutoPublishScheduler(DATA_ROOT)
    return s.resume_queue()

@app.post("/api/queue/stop")
async def stop_queue():
    """Stop the autopublish queue."""
    from src.automation.autopublish_scheduler import AutoPublishScheduler
    s = AutoPublishScheduler(DATA_ROOT)
    return s.stop_queue()


# --- Radar Monitor Control ---

RADAR_STATE_FILE = DATA_ROOT / "scheduler" / "radar_monitor_state.json"
RADAR_RESULTS_FILE = DATA_ROOT / "radar" / "latest_youtube_results.json"

@app.get("/api/radar-monitor/status")
async def get_radar_monitor_status():
    """Get radar monitor state and latest results."""
    state = {"enabled": False, "last_run": None, "interval": 1800, "total_runs": 0}
    if RADAR_STATE_FILE.exists():
        try:
            state = json.loads(RADAR_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    results = {"count": 0, "timestamp": None, "results": []}
    if RADAR_RESULTS_FILE.exists():
        try:
            results = json.loads(RADAR_RESULTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"state": state, "latest_results": results}

@app.post("/api/radar-monitor/run")
async def run_radar_monitor():
    """Trigger a single radar search cycle now."""
    import subprocess
    venv_python = "/Volumes/SSD EXT MACBOOK/JHC-PROJETOS/JHC VIRAL ENGINE/GTA 6/.venv/bin/python3"
    script = "/Volumes/SSD EXT MACBOOK/JHC-PROJETOS/JHC VIRAL ENGINE/GTA 6/scripts/radar_monitor.py"
    project_cwd = "/Volumes/SSD EXT MACBOOK/JHC-PROJETOS/JHC VIRAL ENGINE/GTA 6"
    try:
        result = subprocess.run(
            [venv_python, "-I", script],
            capture_output=True, text=True, timeout=60,
            cwd=project_cwd,
        )
        if result.returncode == 0:
            output = json.loads(result.stdout) if result.stdout.strip() else {}
            return {"ok": True, "results": output.get("results", 0)}
        return {"ok": False, "error": result.stderr[:200]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Timeout (60s)"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

@app.post("/api/radar-monitor/enable")
async def enable_radar_monitor(request: Request):
    """Enable or disable periodic radar monitoring."""
    body = await request.json()
    enabled = body.get("enabled", True)
    interval = body.get("interval", 1800)
    state = {"enabled": False, "last_run": None, "interval": 1800, "total_runs": 0}
    if RADAR_STATE_FILE.exists():
        try:
            state = json.loads(RADAR_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    state["enabled"] = enabled
    state["interval"] = interval
    RADAR_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    RADAR_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    status_label = "ativado" if enabled else "desativado"
    return {"ok": True, "enabled": enabled, "interval": interval, "message": f"Monitor {status_label}"}


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

# =============================================================================
# MISSÃO 016 — Story Studio (Histórias Animadas)
# =============================================================================

@app.post("/api/stories/create")
async def create_story(request: Request):
    """Cria e renderiza uma história animada a partir de roteiro JSON."""
    from src.production.story_studio import StoryStudio
    body = await request.json()
    studio = StoryStudio(DATA_ROOT)
    try:
        story = studio.create_story(script=body.get("script"))
        if body.get("save_script"):
            studio.save_script(story, body.get("name"))
        result = studio.render(
            story,
            platform=body.get("platform", "reels"),
            output_name=body.get("name"),
        )
        from dataclasses import asdict
        return asdict(result)
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Erro: {str(e)}"})

@app.get("/api/stories/list")
async def list_stories():
    """Lista todas as histórias renderizadas."""
    from src.production.story_studio import StoryStudio
    studio = StoryStudio(DATA_ROOT)
    return studio.list_stories()

@app.get("/api/stories/scripts")
async def list_scripts():
    """Lista todos os roteiros salvos."""
    from src.production.story_studio import StoryStudio
    studio = StoryStudio(DATA_ROOT)
    return studio.list_scripts()

# =============================================================================
# MISSÃO 017 — Integração Audiovisual
# =============================================================================

@app.post("/api/audio/mix")
async def mix_audio(request: Request):
    """Mixa música e/ou narração com o áudio original do vídeo."""
    from src.production.audiovisual_sync import AudioVisualSync
    body = await request.json()
    video_path = body.get("video_path", "")
    if not video_path:
        return JSONResponse(status_code=400, content={"detail": "video_path é obrigatório"})
    sync = AudioVisualSync(DATA_ROOT)
    try:
        result = sync.mix_audio(
            video_path,
            music_path=body.get("music_path"),
            narration_path=body.get("narration_path"),
            music_volume=body.get("music_volume", 0.3),
            narration_volume=body.get("narration_volume", 1.0),
            ducking=body.get("ducking", True),
            output_name=body.get("output_name"),
        )
        from dataclasses import asdict
        return asdict(result)
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={"detail": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Erro na mixagem: {str(e)}"})

@app.post("/api/subtitles/generate")
async def generate_subtitles(request: Request):
    """Gera arquivo de legenda (SRT/VTT/ASS) a partir de segmentos temporizados."""
    from src.production.audiovisual_sync import AudioVisualSync
    body = await request.json()
    segments = body.get("segments", [])
    output_name = body.get("output_name", "subtitles")
    if not segments:
        return JSONResponse(status_code=400, content={"detail": "segments é obrigatório"})
    sync = AudioVisualSync(DATA_ROOT)
    try:
        result = sync.generate_subtitles(
            segments,
            output_name=output_name,
            fmt=body.get("format", "srt"),
            language=body.get("language", "pt-BR"),
        )
        from dataclasses import asdict
        return asdict(result)
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Erro: {str(e)}"})

@app.get("/api/audio/list")
async def list_mixed_audio():
    """Lista todos os arquivos de áudio mixados."""
    from src.production.audiovisual_sync import AudioVisualSync
    sync = AudioVisualSync(DATA_ROOT)
    return sync.list_mixed()

@app.get("/api/subtitles/list")
async def list_subtitles():
    """Lista todos os arquivos de legenda."""
    from src.production.audiovisual_sync import AudioVisualSync
    sync = AudioVisualSync(DATA_ROOT)
    return sync.list_subtitles()

# =============================================================================
# MISSÃO 018 — Importador de Redes Sociais
# =============================================================================

@app.post("/api/import/video")
async def import_social_video(request: Request):
    """Importa vídeo de Instagram/YouTube/TikTok por URL."""
    from src.media.social_importer import SocialImporter
    body = await request.json()
    url = body.get("url", "")
    if not url:
        return JSONResponse(status_code=400, content={"detail": "url é obrigatória"})
    importer = SocialImporter(DATA_ROOT)
    try:
        result = importer.import_video(
            url,
            quality=body.get("quality", "best"),
            use_cache=body.get("use_cache", True),
        )
        from dataclasses import asdict
        return asdict(result)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Erro na importação: {str(e)}"})

@app.post("/api/import/batch")
async def import_batch_videos(request: Request):
    """Importa múltiplos vídeos em lote."""
    from src.media.social_importer import SocialImporter
    body = await request.json()
    urls = body.get("urls", [])
    if not urls:
        return JSONResponse(status_code=400, content={"detail": "urls é obrigatório"})
    importer = SocialImporter(DATA_ROOT)
    return importer.import_batch(
        urls,
        quality=body.get("quality", "best"),
        use_cache=body.get("use_cache", True),
    )

@app.get("/api/import/list")
async def list_imports():
    """Lista todos os vídeos importados."""
    from src.media.social_importer import SocialImporter
    importer = SocialImporter(DATA_ROOT)
    return importer.list_imports()

@app.get("/api/import/stats")
async def import_stats():
    """Estatísticas dos imports."""
    from src.media.social_importer import SocialImporter
    importer = SocialImporter(DATA_ROOT)
    return importer.get_import_stats()

# =============================================================================
# MISSÃO 019 — Browser Publisher (Publicação Automatizada)
# =============================================================================

@app.post("/api/publish/browser")
async def browser_publish(request: Request):
    """Publica vídeo em plataforma social via Playwright."""
    from src.publishing.browser_publisher import BrowserPublisher, PublishRequest
    body = await request.json()
    video_path = body.get("video_path", "")
    platform = body.get("platform", "")
    if not video_path or not platform:
        return JSONResponse(status_code=400, content={"detail": "video_path e platform são obrigatórios"})
    publisher = BrowserPublisher(DATA_ROOT)
    try:
        req = PublishRequest(
            platform=platform,
            video_path=video_path,
            title=body.get("title", ""),
            description=body.get("description", ""),
            tags=body.get("tags", []),
            thumbnail_path=body.get("thumbnail_path", ""),
            schedule_time=body.get("schedule_time", ""),
            content_type=body.get("content_type", "reel"),
            privacy=body.get("privacy", "public"),
        )
        result = await publisher.publish(req, max_retries=body.get("max_retries", 3))
        from dataclasses import asdict
        return asdict(result)
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Erro na publicação: {str(e)}"})

@app.get("/api/publish/session/{platform}")
async def check_publish_session(platform: str):
    """Verifica se existe sessão ativa para a plataforma."""
    from src.publishing.browser_publisher import BrowserPublisher
    publisher = BrowserPublisher(DATA_ROOT)
    return await publisher.check_session(platform)

@app.get("/api/publish/history")
async def publish_history(limit: int = Query(50, ge=1, le=200)):
    """Retorna histórico de publicações."""
    from src.publishing.browser_publisher import BrowserPublisher
    publisher = BrowserPublisher(DATA_ROOT)
    return publisher.get_history(limit=limit)

@app.get("/api/publish/stats")
async def publish_stats():
    """Estatísticas de publicação."""
    from src.publishing.browser_publisher import BrowserPublisher
    publisher = BrowserPublisher(DATA_ROOT)
    return publisher.get_stats()

# =============================================================================
# MISSÃO 020 — Thumbnail Factory Integrada
# =============================================================================

@app.post("/api/thumbnails/auto-generate")
async def auto_generate_thumbnail(request: Request):
    """Gera thumbnails automaticamente para um vídeo (integração com publicação)."""
    from src.production.thumbnail_engine import ThumbnailEngine, ThumbnailRequest
    body = await request.json()
    video_path = body.get("video_path", "")
    profile_id = body.get("profile_id", "")
    if not video_path:
        return JSONResponse(status_code=400, content={"detail": "video_path é obrigatório"})
    engine = ThumbnailEngine(DATA_ROOT)
    try:
        req = ThumbnailRequest(
            profile_id=profile_id or "default",
            platform=body.get("platform", "instagram"),
            format_type=body.get("format_type", "reel"),
            title=body.get("title", ""),
            source_video_path=video_path,
            template=body.get("template", "auto"),
        )
        results = await engine.generate_variants(req)
        return {
            "generated": len(results),
            "thumbnails": [r.to_dict() for r in results],
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Erro: {str(e)}"})

# =============================================================================
# MISSÃO 021 — Distribuição Multiformato
# =============================================================================

@app.post("/api/export/multiformat")
async def export_multiformat(request: Request):
    """Exporta vídeo em múltiplos formatos para diferentes plataformas."""
    from src.production.multiformat_exporter import MultiFormatExporter
    body = await request.json()
    video_path = body.get("video_path", "")
    if not video_path:
        return JSONResponse(status_code=400, content={"detail": "video_path é obrigatório"})
    exporter = MultiFormatExporter(DATA_ROOT)
    try:
        result = exporter.export_all(
            video_path,
            platforms=body.get("platforms"),
            profiles=body.get("profiles"),
            watermark_text=body.get("watermark_text", ""),
            subtitle_path=body.get("subtitle_path"),
            output_prefix=body.get("output_prefix", ""),
        )
        from dataclasses import asdict
        return asdict(result)
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={"detail": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Erro na exportação: {str(e)}"})

@app.get("/api/export/list")
async def list_exports():
    """Lista todas as exportações existentes."""
    from src.production.multiformat_exporter import MultiFormatExporter
    exporter = MultiFormatExporter(DATA_ROOT)
    return exporter.list_exports()

@app.get("/api/export/profiles")
async def get_export_profiles():
    """Retorna todos os perfis de formato disponíveis."""
    from src.production.multiformat_exporter import MultiFormatExporter
    exporter = MultiFormatExporter(DATA_ROOT)
    return exporter.get_available_profiles()

# =============================================================================
# MISSÃO 023 — Autenticação Dashboard + Upload de Mídia
# =============================================================================

@app.post("/api/auth/login")
async def dashboard_login(request: Request):
    """Login seguro do proprietário. Retorna JWT em httpOnly cookie + body."""
    from src.api.auth import create_jwt, get_jwt_secret, validate_dashboard_credentials
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"detail": "JSON inválido"})

    username = body.get("username", "")
    password = body.get("password", "")

    if not username or not password:
        return JSONResponse(status_code=400, content={"detail": "username e password obrigatórios"})

    if not validate_dashboard_credentials(username, password):
        return JSONResponse(status_code=401, content={"detail": "Credenciais inválidas"})

    secret = get_jwt_secret()
    token = create_jwt({"sub": username, "role": "owner"}, secret, expires_in=86400)

    response = JSONResponse(content={
        "token": token,
        "expires_in": 86400,
        "user": username,
    })
    response.set_cookie(
        key="jhc_session",
        value=token,
        httponly=True,
        secure=os.environ.get("JHC_ENV") == "production",
        samesite="lax",
        max_age=86400,
        path="/",
    )
    return response


@app.get("/api/auth/me")
async def auth_me(request: Request):
    """Retorna informações do usuário autenticado."""
    user = getattr(request.state, "user", None)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Não autenticado"})
    return {"user": user.get("sub"), "role": user.get("role"), "exp": user.get("exp")}


@app.post("/api/auth/logout")
async def dashboard_logout():
    """Limpa sessão do proprietário."""
    response = JSONResponse(content={"detail": "Logout realizado"})
    response.delete_cookie("jhc_session", path="/")
    return response


@app.post("/api/upload")
async def upload_media(request: Request):
    """Upload de arquivo de mídia via multipart/form-data.

    Recebe o arquivo, salva em DATA_ROOT/uploads/ e retorna o caminho
    para uso nos endpoints de processamento (clipper, stories, export, etc.).
    """
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        return JSONResponse(
            status_code=400,
            content={"detail": "Content-Type deve ser multipart/form-data"},
        )

    form = await request.form()
    file = form.get("file")
    if not file or not hasattr(file, "filename"):
        return JSONResponse(status_code=400, content={"detail": "Campo 'file' obrigatório"})

    uploads_dir = DATA_ROOT / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    # Sanitiza nome do arquivo
    import re
    safe_name = re.sub(r'[^\w\-.]', '_', file.filename)
    timestamp = int(time.time())
    dest = uploads_dir / f"{timestamp}_{safe_name}"

    # Evita sobrescrita
    counter = 0
    while dest.exists():
        counter += 1
        stem = dest.stem.rsplit("_", 1)[0] if "_" in dest.stem else dest.stem
        dest = uploads_dir / f"{stem}_{counter}{dest.suffix}"

    content = await file.read()
    max_size = 500 * 1024 * 1024  # 500MB
    if len(content) > max_size:
        return JSONResponse(
            status_code=413,
            content={"detail": f"Arquivo muito grande ({len(content)//1024//1024}MB). Máximo: 500MB"},
        )

    dest.write_bytes(content)

    return {
        "path": str(dest),
        "filename": dest.name,
        "size_mb": round(len(content) / (1024 * 1024), 2),
        "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


# =============================================================================
# AUTOREEL STUDIO — Pipeline automático de produção de vídeos virais
# =============================================================================

@app.post("/api/autoreel/produce")
async def autoreel_produce(request: Request):
    """Produz um reel viral automaticamente a partir de vídeo fonte."""
    from src.production.auto_reel import AutoReelStudio, ReelRequest

    body = await request.json()
    video_path = body.get("video_path", "")
    if not video_path:
        return JSONResponse(status_code=400, content={"detail": "video_path obrigatório"})

    reel_request = ReelRequest(
        video_path=video_path,
        market=body.get("market", "br"),
        platform=body.get("platform", "reels"),
        editorial_model=body.get("editorial_model", "viral_hook"),
        include_narration=body.get("include_narration", False),
        include_music=body.get("include_music", True),
        custom_title=body.get("custom_title"),
        subtitle_text=body.get("subtitle_text"),
        logo_path=body.get("logo_path"),
    )

    studio = AutoReelStudio(data_root=str(DATA_ROOT))
    result = studio.produce(reel_request)
    return result.to_dict()


@app.get("/api/autoreel/outputs")
async def autoreel_outputs():
    """Lista produções concluídas do AutoReel."""
    from src.production.auto_reel import AutoReelStudio

    studio = AutoReelStudio(data_root=str(DATA_ROOT))
    return studio.list_outputs()


@app.get("/api/autoreel/status/{job_id}")
async def autoreel_status(job_id: str):
    """Busca status de um job AutoReel por ID."""
    from src.production.auto_reel import AutoReelStudio

    studio = AutoReelStudio(data_root=str(DATA_ROOT))
    result = studio.get_status(job_id)
    if not result:
        return JSONResponse(status_code=404, content={"detail": "Job não encontrado"})
    return result


@app.get("/api/autoreel/configs")
async def autoreel_configs():
    """Retorna configurações disponíveis de market e plataforma."""
    from src.production.auto_reel import PLATFORM_CONFIGS, MARKET_CONFIGS

    return {
        "platforms": {k.value: v for k, v in PLATFORM_CONFIGS.items()},
        "markets": {k.value: v for k, v in MARKET_CONFIGS.items()},
    }

# =============================================================================
# SSD LIBRARY — Worker local seguro para indexação de vídeos no SSD
# =============================================================================

@app.post("/api/ssd/validate")
async def ssd_validate(request: Request):
    """Valida se o caminho SSD existe e é acessível."""
    from src.media.ssd_library import SSDLibraryWorker

    body = await request.json()
    ssd_path = body.get("path", "")
    if not ssd_path:
        return JSONResponse(status_code=400, content={"detail": "path obrigatório"})

    worker = SSDLibraryWorker(ssd_root=ssd_path, data_root=str(DATA_ROOT))
    return worker.validate_ssd_path()


@app.post("/api/ssd/scan")
async def ssd_scan(request: Request):
    """Inicia indexação incremental de vídeos no SSD."""
    from src.media.ssd_library import SSDLibraryWorker

    body = await request.json()
    ssd_path = body.get("path", "")
    max_files = body.get("max_files", 50)

    if not ssd_path:
        return JSONResponse(status_code=400, content={"detail": "path obrigatório"})

    worker = SSDLibraryWorker(ssd_root=ssd_path, data_root=str(DATA_ROOT))
    result = worker.scan(max_files=max_files)
    return result


@app.get("/api/ssd/search")
async def ssd_search(
    q: str = "", tags: str = "", category: str = "",
    min_dur: float = 0, max_dur: float = 0, limit: int = 50
):
    """Busca vídeos indexados com filtros editoriais."""
    from src.media.ssd_library import SSDLibraryWorker

    # Usa último path validado ou padrão
    ssd_path = os.environ.get("JHC_SSD_PATH", "/Volumes/SSD EXT MACBOOK")
    worker = SSDLibraryWorker(ssd_root=ssd_path, data_root=str(DATA_ROOT))
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    results = worker.search(
        query=q, tags=tag_list, category=category,
        min_duration=min_dur, max_duration=max_dur, limit=limit
    )
    return results


@app.get("/api/ssd/stats")
async def ssd_stats():
    """Estatísticas da biblioteca SSD."""
    from src.media.ssd_library import SSDLibraryWorker

    ssd_path = os.environ.get("JHC_SSD_PATH", "/Volumes/SSD EXT MACBOOK")
    worker = SSDLibraryWorker(ssd_root=ssd_path, data_root=str(DATA_ROOT))
    return worker.get_stats()


@app.put("/api/ssd/tags")
async def ssd_update_tags(request: Request):
    """Atualiza tags de um vídeo indexado."""
    from src.media.ssd_library import SSDLibraryWorker

    body = await request.json()
    path = body.get("path", "")
    tags = body.get("tags", [])
    if not path:
        return JSONResponse(status_code=400, content={"detail": "path obrigatório"})

    ssd_path = os.environ.get("JHC_SSD_PATH", "/Volumes/SSD EXT MACBOOK")
    worker = SSDLibraryWorker(ssd_root=ssd_path, data_root=str(DATA_ROOT))
    ok = worker.update_tags(path, tags)
    if not ok:
        return JSONResponse(status_code=404, content={"detail": "Vídeo não encontrado no índice"})
    return {"status": "ok", "tags": tags}


@app.put("/api/ssd/category")
async def ssd_update_category(request: Request):
    """Atualiza categoria de um vídeo indexado."""
    from src.media.ssd_library import SSDLibraryWorker

    body = await request.json()
    path = body.get("path", "")
    category = body.get("category", "")
    if not path or not category:
        return JSONResponse(status_code=400, content={"detail": "path e category obrigatórios"})

    ssd_path = os.environ.get("JHC_SSD_PATH", "/Volumes/SSD EXT MACBOOK")
    worker = SSDLibraryWorker(ssd_root=ssd_path, data_root=str(DATA_ROOT))
    ok = worker.update_category(path, category)
    if not ok:
        return JSONResponse(status_code=404, content={"detail": "Vídeo não encontrado no índice"})
    return {"status": "ok", "category": category}

# =============================================================================
# DUAL MARKET — Geração simultânea BR + Global com identidade própria
# =============================================================================

@app.post("/api/dual-market/produce")
async def dual_market_produce(request: Request):
    """Produz versões BR e Global do mesmo vídeo fonte."""
    from src.production.dual_market import DualMarketEngine

    body = await request.json()
    video_path = body.get("video_path", "")
    topic = body.get("topic", "")
    platform = body.get("platform", "reels")
    base_subtitle = body.get("base_subtitle", "")

    if not video_path or not topic:
        return JSONResponse(status_code=400, content={"detail": "video_path e topic obrigatórios"})

    engine = DualMarketEngine(data_root=str(DATA_ROOT))
    result = engine.produce_dual(video_path, topic, platform, base_subtitle)
    return result

@app.get("/api/dual-market/jobs")
async def dual_market_jobs():
    """Lista jobs dual market anteriores."""
    from src.production.dual_market import DualMarketEngine

    engine = DualMarketEngine(data_root=str(DATA_ROOT))
    return engine.list_jobs()

@app.get("/api/dual-market/identity/{market}")
async def dual_market_identity(market: str):
    """Retorna configuração de identidade de um mercado."""
    from src.production.dual_market import DualMarketEngine

    engine = DualMarketEngine(data_root=str(DATA_ROOT))
    return engine.get_identity(market)

# =============================================================================
# THUMBNAIL FACTORY 2.0 — 3 alternativas por vídeo com identidade BR/Global
# =============================================================================

@app.post("/api/thumbnails/generate")
async def thumbnail_generate(request: Request):
    """Gera 3 variantes de thumbnail para um vídeo."""
    from src.production.thumbnail_factory import ThumbnailFactory

    body = await request.json()
    video_path = body.get("video_path", "")
    if not video_path:
        return JSONResponse(status_code=400, content={"detail": "video_path obrigatório"})

    factory = ThumbnailFactory(data_root=str(DATA_ROOT))
    job = factory.generate_variants(
        video_path=video_path,
        market=body.get("market", "br"),
        title=body.get("title", ""),
        associated_job_id=body.get("associated_job_id", ""),
    )
    return job.to_dict()

@app.get("/api/thumbnails/jobs")
async def thumbnail_jobs(limit: int = 20):
    """Lista jobs de thumbnail recentes."""
    from src.production.thumbnail_factory import ThumbnailFactory

    factory = ThumbnailFactory(data_root=str(DATA_ROOT))
    return factory.list_jobs(limit=limit)

@app.get("/api/thumbnails/job/{job_id}")
async def thumbnail_job_detail(job_id: str):
    """Detalhes completos de um job de thumbnail."""
    from src.production.thumbnail_factory import ThumbnailFactory

    factory = ThumbnailFactory(data_root=str(DATA_ROOT))
    result = factory.get_job(job_id)
    if not result:
        return JSONResponse(status_code=404, content={"detail": "Job não encontrado"})
    return result

@app.post("/api/thumbnails/select/{job_id}/{variant_id}")
async def thumbnail_select_variant(job_id: str, variant_id: str):
    """Seleciona qual variante usar como capa."""
    from src.production.thumbnail_factory import ThumbnailFactory

    factory = ThumbnailFactory(data_root=str(DATA_ROOT))
    ok = factory.select_variant(job_id, variant_id)
    if not ok:
        return JSONResponse(status_code=404, content={"detail": "Job ou variante não encontrada"})
    return {"status": "ok", "selected": variant_id}

@app.post("/api/thumbnails/export/{job_id}")
async def thumbnail_export(job_id: str):
    """Exporta a variante selecionada em formato compatível."""
    from src.production.thumbnail_factory import ThumbnailFactory

    factory = ThumbnailFactory(data_root=str(DATA_ROOT))
    path = factory.export_selected(job_id)
    if not path:
        return JSONResponse(status_code=400, content={"detail": "Nenhuma variante selecionada ou job não encontrado"})
    return {"status": "ok", "exported_path": path}

@app.put("/api/thumbnails/title/{job_id}")
async def thumbnail_update_title(job_id: str, request: Request):
    """Atualiza título e regenera variante editorial."""
    from src.production.thumbnail_factory import ThumbnailFactory

    body = await request.json()
    title = body.get("title", "")
    if not title:
        return JSONResponse(status_code=400, content={"detail": "title obrigatório"})

    factory = ThumbnailFactory(data_root=str(DATA_ROOT))
    ok = factory.update_title(job_id, title)
    if not ok:
        return JSONResponse(status_code=404, content={"detail": "Job não encontrado"})
    return {"status": "ok", "title": title}

@app.post("/api/thumbnails/associate/{job_id}/{publish_job_id}")
async def thumbnail_associate(job_id: str, publish_job_id: str):
    """Associa thumbnail a um job de publicação."""
    from src.production.thumbnail_factory import ThumbnailFactory

    factory = ThumbnailFactory(data_root=str(DATA_ROOT))
    ok = factory.associate_with_job(job_id, publish_job_id)
    if not ok:
        return JSONResponse(status_code=404, content={"detail": "Job não encontrado"})
    return {"status": "ok", "associated": publish_job_id}

# =============================================================================
# ADVANCED ANALYZER — Análise profunda de ritmo, narrativa e destaques (MISSÃO F)
# =============================================================================

@app.post("/api/analyze/advanced")
async def advanced_analyze(request: Request):
    """Análise avançada de vídeo: ritmo, narrativa, destaques, legendas, formatos."""
    from src.research.advanced_analyzer import AdvancedVideoAnalyzer

    body = await request.json()
    video_path = body.get("video_path", "")
    if not video_path:
        return JSONResponse(status_code=400, content={"detail": "video_path obrigatório"})

    analyzer = AdvancedVideoAnalyzer(data_root=str(DATA_ROOT))
    result = analyzer.analyze(video_path)
    return result.to_dict()

# =============================================================================
# PUBLISH STATE MACHINE — Verifiable job states (MISSÃO G)
# =============================================================================

@app.post("/api/publish-pipeline/create")
async def publish_pipeline_create(request: Request):
    """Create new publish pipeline job in PREPARING state."""
    from src.publishing.publish_state_machine import PublishStateMachine

    body = await request.json()
    market = body.get("market", "br")
    platform = body.get("platform", "")
    if not platform:
        return JSONResponse(status_code=400, content={"detail": "platform obrigatório"})

    sm = PublishStateMachine(data_root=str(DATA_ROOT))
    job = sm.create_job(
        market=market,
        platform=platform,
        video_path=body.get("video_path", ""),
        title=body.get("title", ""),
        autoreel_job_id=body.get("autoreel_job_id", ""),
        thumbnail_job_id=body.get("thumbnail_job_id", ""),
    )
    return job.to_dict()

@app.post("/api/publish-pipeline/transition/{job_id}/{new_state}")
async def publish_pipeline_transition(job_id: str, new_state: str, request: Request):
    """Transition job state with validation. PUBLISHED requires confirmation."""
    from src.publishing.publish_state_machine import PublishStateMachine

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    reason = body.get("reason", "")

    sm = PublishStateMachine(data_root=str(DATA_ROOT))
    result = sm.transition(job_id, new_state, reason)
    if "error" in result:
        return JSONResponse(status_code=400, content=result)
    return result

@app.post("/api/publish-pipeline/confirm/{job_id}")
async def publish_pipeline_confirm(job_id: str, request: Request):
    """Record verifiable platform confirmation. Required before PUBLISHED."""
    from src.publishing.publish_state_machine import PublishStateMachine

    body = await request.json()
    post_id = body.get("post_id", "")
    if not post_id:
        return JSONResponse(status_code=400, content={"detail": "post_id obrigatório para confirmação verificável"})

    sm = PublishStateMachine(data_root=str(DATA_ROOT))
    result = sm.confirm_publish(
        job_id=job_id,
        post_id=post_id,
        permalink=body.get("permalink", ""),
        verification_method=body.get("verification_method", "api_response"),
        metadata=body.get("metadata", {}),
    )
    if "error" in result:
        return JSONResponse(status_code=400, content=result)
    return result

@app.get("/api/publish-pipeline/jobs")
async def publish_pipeline_jobs(market: str = "", state: str = "", limit: int = 50):
    """List pipeline jobs with optional filters."""
    from src.publishing.publish_state_machine import PublishStateMachine

    sm = PublishStateMachine(data_root=str(DATA_ROOT))
    return sm.list_jobs(market=market, state=state, limit=limit)

@app.get("/api/publish-pipeline/job/{job_id}")
async def publish_pipeline_job_detail(job_id: str):
    """Get full pipeline job details including state history."""
    from src.publishing.publish_state_machine import PublishStateMachine

    sm = PublishStateMachine(data_root=str(DATA_ROOT))
    result = sm.get_job(job_id)
    if not result:
        return JSONResponse(status_code=404, content={"detail": "Job não encontrado"})
    return result

@app.get("/api/publish-pipeline/stats")
async def publish_pipeline_stats():
    """Pipeline stats by state and market."""
    from src.publishing.publish_state_machine import PublishStateMachine

    sm = PublishStateMachine(data_root=str(DATA_ROOT))
    return sm.get_stats()

@app.get("/api/publish-pipeline/valid-transitions/{state}")
async def publish_pipeline_valid_transitions(state: str):
    """Return valid next states for a given state."""
    from src.publishing.publish_state_machine import PublishStateMachine

    return {"state": state, "valid_next": PublishStateMachine.get_valid_transitions(state)}

# =============================================================================
# PACK BULK IMPORTER — Importação massiva de packs de vídeos (MISSÃO 026)
# =============================================================================

@app.post("/api/import/pack/discover")
async def pack_discover(request: Request):
    """Descobre arquivos de um pack via HTML da plataforma."""
    from src.media.pack_bulk_importer import PackBulkImporter

    body = await request.json()
    html = body.get("html", "")
    if not html:
        return JSONResponse(status_code=400, content={"detail": "html obrigatório"})

    ssd_path = os.environ.get("JHC_SSD_PATH", "/Volumes/SSD EXT MACBOOK")
    importer = PackBulkImporter(ssd_root=ssd_path, data_root=str(DATA_ROOT))
    entries = importer.parse_monetizegta6_catalog(html)
    result = importer.add_entries(entries)
    return {"discovered": len(entries), **result}

@app.post("/api/import/pack/add")
async def pack_add_entries(request: Request):
    """Adiciona entradas de download manualmente."""
    from src.media.pack_bulk_importer import PackBulkImporter

    body = await request.json()
    entries = body.get("entries", [])
    if not entries:
        return JSONResponse(status_code=400, content={"detail": "entries obrigatório"})

    ssd_path = os.environ.get("JHC_SSD_PATH", "/Volumes/SSD EXT MACBOOK")
    importer = PackBulkImporter(ssd_root=ssd_path, data_root=str(DATA_ROOT))
    return importer.add_entries(entries)

@app.post("/api/import/pack/process")
async def pack_process_batch(request: Request):
    """Processa lote de downloads pendentes."""
    from src.media.pack_bulk_importer import PackBulkImporter

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    batch_size = body.get("batch_size", 3)

    ssd_path = os.environ.get("JHC_SSD_PATH", "/Volumes/SSD EXT MACBOOK")
    importer = PackBulkImporter(ssd_root=ssd_path, data_root=str(DATA_ROOT))
    results = importer.process_batch(batch_size=batch_size)
    return {"processed": len(results), "results": results}

@app.post("/api/import/pack/retry")
async def pack_retry_failed():
    """Reenfileira downloads falhados."""
    from src.media.pack_bulk_importer import PackBulkImporter

    ssd_path = os.environ.get("JHC_SSD_PATH", "/Volumes/SSD EXT MACBOOK")
    importer = PackBulkImporter(ssd_root=ssd_path, data_root=str(DATA_ROOT))
    count = importer.retry_failed()
    return {"retried": count}

@app.get("/api/import/pack/progress")
async def pack_progress():
    """Progresso atual da importação."""
    from src.media.pack_bulk_importer import PackBulkImporter

    ssd_path = os.environ.get("JHC_SSD_PATH", "/Volumes/SSD EXT MACBOOK")
    importer = PackBulkImporter(ssd_root=ssd_path, data_root=str(DATA_ROOT))
    return importer.get_progress()

@app.get("/api/import/pack/dashboard")
async def pack_dashboard():
    """Dashboard completo do acervo — MISSÃO 032 FASE 2.

    Retorna dados reais: breakdown por tipo, velocidade, worker status,
    histórico de downloads, últimos erros. Nunca valores simulados.
    """
    from src.media.pack_bulk_importer import PackBulkImporter

    ssd_path = os.environ.get("JHC_SSD_PATH", "/Volumes/SSD EXT MACBOOK")
    importer = PackBulkImporter(ssd_root=ssd_path, data_root=str(DATA_ROOT))
    return importer.get_dashboard_data()


_PROJECT_ROOT = Path(__file__).resolve().parent.parent

@app.post("/api/import/pack/worker/start")
async def worker_start():
    """Inicia worker persistente em background — MISSÃO 032 FASE 3."""
    import subprocess
    result = subprocess.run(
        [str(_PROJECT_ROOT.parent / ".venv" / "bin" / "python3"), "-I",
         str(_PROJECT_ROOT / "scripts" / "bulk_worker.py"), "start"],
        capture_output=True, text=True, cwd=str(_PROJECT_ROOT),
    )
    return {"stdout": result.stdout.strip(), "stderr": result.stderr.strip(), "returncode": result.returncode}


@app.post("/api/import/pack/worker/stop")
async def worker_stop():
    """Para worker persistente gracefulmente."""
    import subprocess
    result = subprocess.run(
        [str(_PROJECT_ROOT.parent / ".venv" / "bin" / "python3"), "-I",
         str(_PROJECT_ROOT / "scripts" / "bulk_worker.py"), "stop"],
        capture_output=True, text=True, cwd=str(_PROJECT_ROOT),
    )
    return {"stdout": result.stdout.strip(), "stderr": result.stderr.strip(), "returncode": result.returncode}


@app.post("/api/import/pack/worker/pause")
async def worker_pause():
    """Pausa worker após lote atual."""
    import subprocess
    result = subprocess.run(
        [str(_PROJECT_ROOT.parent / ".venv" / "bin" / "python3"), "-I",
         str(_PROJECT_ROOT / "scripts" / "bulk_worker.py"), "pause"],
        capture_output=True, text=True, cwd=str(_PROJECT_ROOT),
    )
    return {"stdout": result.stdout.strip(), "stderr": result.stderr.strip(), "returncode": result.returncode}


@app.post("/api/import/pack/worker/resume")
async def worker_resume():
    """Retoma worker pausado."""
    import subprocess
    result = subprocess.run(
        [str(_PROJECT_ROOT.parent / ".venv" / "bin" / "python3"), "-I",
         str(_PROJECT_ROOT / "scripts" / "bulk_worker.py"), "resume"],
        capture_output=True, text=True, cwd=str(_PROJECT_ROOT),
    )
    return {"stdout": result.stdout.strip(), "stderr": result.stderr.strip(), "returncode": result.returncode}


@app.get("/api/import/pack/worker/status")
async def worker_status():
    """Status do worker persistente."""
    import subprocess
    result = subprocess.run(
        [str(_PROJECT_ROOT.parent / ".venv" / "bin" / "python3"), "-I",
         str(_PROJECT_ROOT / "scripts" / "bulk_worker.py"), "status"],
        capture_output=True, text=True, cwd=str(_PROJECT_ROOT),
    )
    return {"output": result.stdout.strip(), "returncode": result.returncode}


@app.post("/api/import/pack/retry-failed")
async def pack_retry_failed():
    """Reenfileira entradas FAILED para nova tentativa."""
    from src.media.pack_bulk_importer import PackBulkImporter

    ssd_path = os.environ.get("JHC_SSD_PATH", "/Volumes/SSD EXT MACBOOK")
    importer = PackBulkImporter(ssd_root=ssd_path, data_root=str(DATA_ROOT))
    retried = importer.retry_failed()
    return {"retried": retried}


@app.get("/api/import/pack/entries")
async def pack_entries(state: str = "", limit: int = 100):
    """Lista entradas de download filtradas por estado."""
    from src.media.pack_bulk_importer import PackBulkImporter

    ssd_path = os.environ.get("JHC_SSD_PATH", "/Volumes/SSD EXT MACBOOK")
    importer = PackBulkImporter(ssd_root=ssd_path, data_root=str(DATA_ROOT))
    return importer.get_entries(state=state, limit=limit)

@app.post("/api/import/pack/fetch-catalog")
async def pack_fetch_catalog(request: Request):
    """Busca catálogo autenticado da plataforma monetizegta6 via cookies de sessão."""
    from src.media.pack_bulk_importer import PackBulkImporter

    body = await request.json()
    cookies = body.get("cookies", "")
    url = body.get("url", "https://monetizegta6.vercel.app/membros/pro/")

    if not cookies:
        return JSONResponse(status_code=400, content={"detail": "cookies obrigatório (header Cookie completo da sessão autenticada)"})

    ssd_path = os.environ.get("JHC_SSD_PATH", "/Volumes/SSD EXT MACBOOK")
    importer = PackBulkImporter(ssd_root=ssd_path, data_root=str(DATA_ROOT), cookies=cookies)
    result = importer.fetch_authenticated_catalog(url=url)

    if result.get("error"):
        return JSONResponse(status_code=400, content=result)

    # Auto-add discovered entries
    if result["entries"]:
        add_result = importer.add_entries(result["entries"])
        result["add_result"] = add_result

    # Don't return raw HTML in response (too large)
    result.pop("html", None)
    return result


@app.post("/api/import/pack/load-catalog")
async def pack_load_catalog(request: Request):
    """Carrega catálogo JSON local (pro_catalog.json) na fila do PackBulkImporter.

    Body: {"catalog_path": "data/auth/pro_catalog.json", "target_dir": "VIDEOS CORTES", "max_entries": 0}
    max_entries=0 carrega todas as entradas. Use valor pequeno para teste inicial.
    """
    body = await request.json()
    catalog_path = body.get("catalog_path", "data/auth/pro_catalog.json")
    target_dir = body.get("target_dir", "VIDEOS CORTES")
    max_entries = body.get("max_entries", 0)

    ssd_path = os.environ.get("JHC_SSD_PATH", "/Volumes/SSD EXT MACBOOK")
    importer = PackBulkImporter(ssd_root=ssd_path, data_root=str(DATA_ROOT))
    result = importer.load_catalog_from_file(
        catalog_path=catalog_path,
        target_dir=target_dir,
        max_entries=max_entries,
    )

    if result.get("error"):
        return JSONResponse(status_code=400, content=result)

    return result


@app.post("/api/auth/session/login")
async def auth_session_login(request: Request):
    """Inicia login interativo via Playwright para monetizegta6.

    Abre navegador visível, aguarda usuário fazer login (até 5 min),
    salva storage_state e cookies localmente. Nunca expõe credenciais.
    """
    import asyncio
    from src.media.auth_session import AuthSession

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    headless = body.get("headless", False)

    session = AuthSession(headless=headless)
    try:
        result = await session.ensure_authenticated(interactive=True)
        return result
    finally:
        await session.close()


@app.get("/api/auth/session/status")
async def auth_session_status():
    """Verifica status da sessão autenticada sem abrir navegador."""
    import asyncio
    from src.media.auth_session import AuthSession

    session = AuthSession(headless=True)
    try:
        if not session.has_saved_state():
            return {"authenticated": False, "method": "none", "error": "Nenhuma sessão salva"}

        await session._start_browser()
        valid = await session._is_session_valid()
        cookies = await session._context.cookies() if session._context else []
        await session.close()

        return {
            "authenticated": valid,
            "method": "saved_state" if valid else "expired",
            "cookies_count": len(cookies),
            "has_saved_state": True,
        }
    except Exception as e:
        return {"authenticated": False, "error": str(e)}


@app.post("/api/auth/session/discover")
async def auth_session_discover(request: Request):
    """Descobre catálogo completo usando sessão autenticada via Playwright."""
    import asyncio
    from src.media.auth_session import AuthSession

    session = AuthSession(headless=True)
    try:
        auth_result = await session.ensure_authenticated(interactive=False)
        if not auth_result["authenticated"]:
            return JSONResponse(
                status_code=401,
                content={"detail": "Sessão não autenticada. Use /api/auth/session/login primeiro.", **auth_result}
            )

        catalog = await session.discover_catalog()
        return catalog
    finally:
        await session.close()


# --- Analytics / Inteligência de Crescimento ---

@app.get("/api/analytics/dashboard")
async def get_dashboard_analytics():
    """Analytics agregados para o painel do dashboard — não depende de src.analytics."""
    import os
    result = {"catalog": {}, "pipeline": {}, "queue": {}, "radar": {}, "accounts": {}}

    # Catalog stats
    try:
        from src.catalog.smart_catalog import SmartCatalog
        cat = SmartCatalog(data_root=DATA_ROOT)
        stats = cat.get_stats() if hasattr(cat, "get_stats") else {}
        result["catalog"] = stats if isinstance(stats, dict) else {}
    except Exception:
        # Fallback: count files directly
        output_dir = DATA_ROOT / "autoreel" / "output"
        mp4_count = len(list(output_dir.glob("*.mp4"))) if output_dir.exists() else 0
        total_mb = sum(f.stat().st_size for f in output_dir.glob("*.mp4")) / 1_048_576 if output_dir.exists() else 0
        result["catalog"] = {"total_videos": mp4_count, "total_mb": round(total_mb, 1)}

    # Pipeline stats
    try:
        jobs_file = DATA_ROOT / "production_pipeline" / "production_jobs.json"
        if jobs_file.exists():
            jobs_data = json.loads(jobs_file.read_text(encoding="utf-8"))
            by_status = {}
            for j in jobs_data.values():
                s = j.get("status", "unknown")
                by_status[s] = by_status.get(s, 0) + 1
            result["pipeline"] = {"total_jobs": len(jobs_data), "by_status": by_status}
    except Exception:
        pass

    # Queue status
    try:
        from src.automation.autopublish_scheduler import AutoPublishScheduler
        sched = AutoPublishScheduler(DATA_ROOT)
        qs = sched.get_queue_status()
        result["queue"] = {"status": qs.get("queue_status"), "active_jobs": qs.get("active_jobs"), "eligible_now": qs.get("eligible_now")}
    except Exception:
        pass

    # Radar monitor
    radar_state_file = DATA_ROOT / "scheduler" / "radar_monitor_state.json"
    radar_results_file = DATA_ROOT / "radar" / "latest_youtube_results.json"
    try:
        if radar_state_file.exists():
            rs = json.loads(radar_state_file.read_text(encoding="utf-8"))
            result["radar"]["enabled"] = rs.get("enabled", False)
            result["radar"]["total_runs"] = rs.get("total_runs", 0)
        if radar_results_file.exists():
            rr = json.loads(radar_results_file.read_text(encoding="utf-8"))
            result["radar"]["latest_count"] = rr.get("count", 0)
    except Exception:
        pass

    # Accounts
    accounts_file = DATA_ROOT / "publishing" / "credentials" / "accounts.json"
    try:
        if accounts_file.exists():
            acc = json.loads(accounts_file.read_text(encoding="utf-8"))
            for platform in ["instagram", "tiktok", "youtube"]:
                info = acc.get("accounts", {}).get(platform, {})
                result["accounts"][platform] = {"handle": info.get("handle", "?"), "status": info.get("status", "?")}
    except Exception:
        pass

    return result


@app.get("/api/analytics/report")
async def get_analytics_report():
    """Relatório consolidado de analytics multiplataforma."""
    from src.analytics import generate_report
    report = generate_report(data_root="data")
    return report.to_dict()


@app.get("/api/analytics/platforms")
async def get_platform_stats():
    """Estatísticas por plataforma (TikTok, Instagram, YouTube)."""
    from src.analytics import collect_platform_stats
    stats = collect_platform_stats(data_root="data")
    return {k: v.to_dict() for k, v in stats.items()}


@app.get("/api/analytics/suggestions")
async def get_optimization_suggestions():
    """Sugestões fundamentadas de otimização baseadas em métricas."""
    from src.analytics import generate_report
    report = generate_report(data_root="data")
    return {"suggestions": report.suggestions}


# ===== SMART CATALOG — FÁBRICA INTELIGENTE DE AUTOREELS =====

@app.get("/api/catalog/stats")
async def get_catalog_stats():
    """Estatísticas do catálogo inteligente de materiais."""
    from src.production.smart_catalog import SmartCatalog
    catalog = SmartCatalog(data_root="data")
    catalog.load()
    return catalog.get_stats()


@app.get("/api/catalog/select")
async def select_materials(
    theme: str = "",
    max_results: int = 10,
    prefer_vertical: bool = True,
    min_duration: float = 5.0,
    max_duration: float = 120.0,
    min_width: int = 720,
):
    """Seleção inteligente de materiais para produção AutoReel."""
    from src.production.smart_catalog import SmartCatalog, SelectionCriteria
    catalog = SmartCatalog(data_root="data")
    catalog.load()
    criteria = SelectionCriteria(
        theme=theme,
        max_results=max_results,
        prefer_vertical=prefer_vertical,
        min_duration=min_duration,
        max_duration=max_duration,
        min_width=min_width,
    )
    selected = catalog.select_materials(criteria)
    return {
        "count": len(selected),
        "criteria": {
            "theme": theme,
            "prefer_vertical": prefer_vertical,
            "min_duration": min_duration,
            "max_duration": max_duration,
            "min_width": min_width,
        },
        "materials": [
            {
                "filename": e.filename,
                "path": e.path,
                "width": e.width,
                "height": e.height,
                "duration": round(e.duration, 1),
                "codec": e.codec,
                "quality_score": e.quality_score(),
                "is_vertical": e.is_vertical(),
                "used_count": e.used_count,
            }
            for e in selected
        ],
    }


@app.post("/api/catalog/record-usage")
async def record_material_usage(body: dict):
    """Registra uso de materiais em produção AutoReel."""
    from src.production.smart_catalog import SmartCatalog
    filenames = body.get("filenames", [])
    reel_id = body.get("reel_id", "")
    if not filenames:
        return {"error": "filenames required"}
    catalog = SmartCatalog(data_root="data")
    catalog.load()
    catalog.record_usage(filenames, reel_id)
    return {"recorded": len(filenames), "reel_id": reel_id}


@app.get("/api/catalog/select-fresh")
async def select_fresh_materials(
    theme: str = "",
    max_results: int = 10,
    prefer_vertical: bool = True,
    min_duration: float = 5.0,
    max_duration: float = 120.0,
    min_width: int = 720,
):
    """Seleção inteligente que exclui conteúdo desatualizado automaticamente."""
    from src.production.smart_catalog import SmartCatalog, SelectionCriteria
    catalog = SmartCatalog(data_root="data")
    catalog.load()
    criteria = SelectionCriteria(
        theme=theme,
        max_results=max_results,
        prefer_vertical=prefer_vertical,
        min_duration=min_duration,
        max_duration=max_duration,
        min_width=min_width,
    )
    selected = catalog.select_fresh_materials(criteria)
    return {
        "count": len(selected),
        "filtered_stale": True,
        "materials": [
            {
                "filename": e.filename,
                "path": e.path,
                "width": e.width,
                "height": e.height,
                "duration": round(e.duration, 1),
                "quality_score": e.quality_score(),
                "is_vertical": e.is_vertical(),
            }
            for e in selected
        ],
    }


ACCOUNTS_FILE = Path("data/publishing/credentials/accounts.json")


@app.get("/api/accounts")
async def get_accounts():
    """Retorna configuração persistente das contas conectadas."""
    if ACCOUNTS_FILE.exists():
        try:
            data = json.loads(ACCOUNTS_FILE.read_text())
            return data.get("accounts", {})
        except Exception:
            pass
    # Fallback: retorna estrutura padrão com handles corretos
    return {
        "instagram": {"handle": "@leonidagta6flashbr", "status": "configured", "auth_method": "manual"},
        "tiktok": {"handle": "@leonidagta6flashbr", "status": "configured", "auth_method": "manual"},
        "youtube": {"handle": "@leonidagta6flashbr", "status": "configured", "auth_method": "manual"},
    }


@app.post("/api/accounts/update")
async def update_accounts(request: Request):
    """Atualiza configuração de uma conta específica."""
    body = await request.json()
    platform = body.get("platform", "")
    updates = body.get("updates", {})
    if not platform or platform not in ("instagram", "tiktok", "youtube"):
        return JSONResponse(status_code=400, content={"detail": "Plataforma inválida"})

    accounts = {}
    if ACCOUNTS_FILE.exists():
        try:
            accounts = json.loads(ACCOUNTS_FILE.read_text()).get("accounts", {})
        except Exception:
            pass

    if platform not in accounts:
        accounts[platform] = {"handle": "", "status": "not_configured", "auth_method": "manual"}

    accounts[platform].update(updates)
    import datetime
    payload = {"accounts": accounts, "updated_at": datetime.datetime.utcnow().isoformat() + "Z"}
    ACCOUNTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACCOUNTS_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return {"ok": True, "platform": platform, "account": accounts[platform]}


@app.get("/api/auth/platforms/status")
async def get_auth_platforms_status():
    """Status das sessões autenticadas por plataforma social."""
    from pathlib import Path
    import json, time
    sessions_dir = Path("data/browser_sessions")
    result = {}
    for platform in ("tiktok", "instagram", "youtube"):
        cookie_file = sessions_dir / f"{platform}_cookies.json"
        state_file = sessions_dir / f"{platform}_state.json"
        profile_dir = sessions_dir / f"{platform}_profile"
        if cookie_file.exists() and state_file.exists():
            try:
                cookies = json.loads(cookie_file.read_text())
                age_h = (time.time() - cookie_file.stat().st_mtime) / 3600
                result[platform] = {
                    "authenticated": True,
                    "cookie_count": len(cookies),
                    "saved_hours_ago": round(age_h, 1),
                }
            except Exception:
                result[platform] = {"authenticated": False, "error": "cookie_read_failed"}
        elif profile_dir.exists() and any(profile_dir.iterdir()):
            result[platform] = {"authenticated": False, "has_profile": True}
        else:
            result[platform] = {"authenticated": False}
    return result

# ===== PRODUCTION PIPELINE — FÁBRICA AUTÔNOMA =====

@app.post("/api/pipeline/create")
async def pipeline_create_job(body: dict):
    """Cria job de produção com auto-seleção do catálogo."""
    from src.production.pipeline import ProductionPipeline
    pipeline = ProductionPipeline(data_root="data")
    job = pipeline.create_job(
        video_path=body.get("video_path", ""),
        platform=body.get("platform", "tiktok"),
        market=body.get("market", "br"),
        title=body.get("title", ""),
        subtitle_text=body.get("subtitle_text", ""),
        auto_select=body.get("auto_select", False),
    )
    return job.to_dict()

@app.post("/api/pipeline/execute/{job_id}")
async def pipeline_execute_job(job_id: str):
    """Executa job de produção (com semáforo de render)."""
    from src.production.pipeline import ProductionPipeline
    pipeline = ProductionPipeline(data_root="data")
    try:
        job = pipeline.execute_job(job_id)
        return job.to_dict()
    except ValueError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})

@app.post("/api/pipeline/schedule/{job_id}")
async def pipeline_schedule_job(job_id: str, body: dict = None):
    """Agenda job concluído para publicação interna."""
    from src.production.pipeline import ProductionPipeline
    pipeline = ProductionPipeline(data_root="data")
    scheduled_at = (body or {}).get("scheduled_at")
    return pipeline.schedule_job(job_id, scheduled_at)

@app.get("/api/pipeline/jobs")
async def pipeline_list_jobs(limit: int = 50):
    """Lista jobs de produção."""
    from src.production.pipeline import ProductionPipeline
    pipeline = ProductionPipeline(data_root="data")
    return {"jobs": pipeline.list_jobs(limit=limit)}

@app.get("/api/pipeline/job/{job_id}")
async def pipeline_get_job(job_id: str):
    """Detalhes de um job específico."""
    from src.production.pipeline import ProductionPipeline
    pipeline = ProductionPipeline(data_root="data")
    job = pipeline.get_job(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"error": "Job não encontrado"})
    return job

@app.get("/api/pipeline/job/{job_id}/video")
async def pipeline_job_video(job_id: str):
    """Stream de vídeo de um job da pipeline para preview inline."""
    from src.production.pipeline import ProductionPipeline
    pipeline = ProductionPipeline(data_root="data")
    job = pipeline.get_job(job_id)
    if not job or not job.get("output_path"):
        raise HTTPException(status_code=404, detail="Job ou vídeo não encontrado")
    video_path = Path(job["output_path"])
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Arquivo de vídeo não existe")
    return FileResponse(str(video_path), media_type="video/mp4")


@app.get("/api/pipeline/stats")
async def pipeline_stats():
    """Estatísticas da pipeline de produção."""
    from src.production.pipeline import ProductionPipeline
    pipeline = ProductionPipeline(data_root="data")
    return pipeline.get_stats()


# =============================================================================
# MISSÃO 040 FASE 1 — Importação por URL (yt-dlp)
# =============================================================================

@app.post("/api/import/url/metadata")
async def import_url_metadata(request: Request):
    """Busca metadados de um vídeo por URL sem baixar."""
    from src.media.url_importer import UrlImporter
    body = await request.json()
    url = body.get("url", "").strip()
    if not url:
        return JSONResponse(status_code=400, content={"detail": "url obrigatória"})
    importer = UrlImporter()
    meta = importer.fetch_metadata(url)
    meta["is_duplicate"] = importer.is_duplicate(url)
    return meta


@app.post("/api/import/url/download")
async def import_url_download(request: Request):
    """Inicia download de vídeo por URL. Retorna imediatamente com status."""
    import threading
    from src.media.url_importer import UrlImporter

    body = await request.json()
    url = body.get("url", "").strip()
    if not url:
        return JSONResponse(status_code=400, content={"detail": "url obrigatória"})

    importer = UrlImporter()

    if importer.is_duplicate(url):
        return {"status": "duplicate", "message": "URL já importada anteriormente"}

    # Download em background para não bloquear a resposta
    def _do_download():
        try:
            importer.download_video(url)
        except Exception as e:
            logger.error(f"Background download failed for {url}: {e}")

    thread = threading.Thread(target=_do_download, daemon=True)
    thread.start()

    return {"status": "downloading", "message": "Download iniciado em background"}


@app.get("/api/import/url/history")
async def import_url_history(limit: int = 50, status: str = ""):
    """Histórico de importações por URL."""
    from src.media.url_importer import UrlImporter
    importer = UrlImporter()
    return importer.get_history(limit=limit, status_filter=status)


@app.get("/api/import/url/stats")
async def import_url_stats():
    """Estatísticas de importação por URL."""
    from src.media.url_importer import UrlImporter
    importer = UrlImporter()
    return importer.get_stats()


@app.delete("/api/import/url/entry")
async def import_url_delete(request: Request):
    """Remove entrada do histórico e arquivo associado."""
    from src.media.url_importer import UrlImporter
    body = await request.json()
    url = body.get("url", "").strip()
    if not url:
        return JSONResponse(status_code=400, content={"detail": "url obrigatória"})
    importer = UrlImporter()
    deleted = importer.delete_entry(url)
    return {"deleted": deleted}


# =============================================================================
# MISSÃO 040 FASE 2 — Radar GTA VI (Busca YouTube)
# =============================================================================

@app.get("/api/radar/search")
async def radar_search(
    query: str = "",
    max_results: int = 10,
    date_filter: str = "7d",
):
    """Busca vídeos sobre GTA VI no YouTube via yt-dlp (assíncrono)."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from src.research.youtube_radar import YouTubeRadar

    def _do_search():
        radar = YouTubeRadar()
        results = radar.search(query=query, max_results=max_results, date_filter=date_filter)
        results = radar.check_already_imported(results)
        return results

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as executor:
        results = await loop.run_in_executor(executor, _do_search)
    return {"results": results, "count": len(results), "query": query, "date_filter": date_filter}


@app.get("/api/radar/discover")
async def radar_discover(max_per_term: int = 5, date_filter: str = "7d"):
    """Busca automática usando todos os termos pré-definidos (assíncrono)."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from src.research.youtube_radar import YouTubeRadar

    def _do_discover():
        radar = YouTubeRadar()
        results = radar.search_all_terms(max_per_term=max_per_term, date_filter=date_filter)
        results = radar.check_already_imported(results)
        radar.save_to_cache(results)
        return results

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as executor:
        results = await loop.run_in_executor(executor, _do_discover)
    return {"results": results, "count": len(results), "terms_used": 12}


@app.get("/api/radar/cache")
async def radar_cache(max_age_hours: int = 24):
    """Retorna resultados em cache se ainda válidos."""
    from src.research.youtube_radar import YouTubeRadar
    radar = YouTubeRadar()
    results = radar.get_cached_results(max_age_hours=max_age_hours)
    return {"results": results, "count": len(results), "cached": len(results) > 0}


# =============================================================================
# MISSÃO 040 FASE 3 — Catalog Bridge (Import → SmartCatalog → Pipeline)
# =============================================================================

@app.post("/api/catalog/bridge/register")
async def catalog_bridge_register(request: Request):
    """Registra vídeo importado no SmartCatalog e opcionalmente cria job de produção."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from src.media.catalog_bridge import CatalogBridge

    body = await request.json()
    file_path = body.get("file_path", "").strip()
    if not file_path:
        return JSONResponse(status_code=400, content={"detail": "file_path obrigatório"})

    def _do_register():
        bridge = CatalogBridge()
        return bridge.auto_process_import(
            file_path=file_path,
            source_url=body.get("source_url", ""),
            title=body.get("title", ""),
            author=body.get("author", ""),
            platform=body.get("platform", "youtube"),
            auto_produce=body.get("auto_produce", True),
        )

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = await loop.run_in_executor(executor, _do_register)
    return result


@app.get("/api/catalog/bridge/pending")
async def catalog_bridge_pending():
    """Lista vídeos importados ainda não registrados no catálogo."""
    from src.media.catalog_bridge import CatalogBridge
    bridge = CatalogBridge()
    pending = bridge.get_pending_imports()
    return {"pending": pending, "count": len(pending)}


# =============================================================================
# MISSÃO 040.1 ETAPA 2 — Publicação Assistida Operacional
# =============================================================================

PLATFORM_UPLOAD_URLS = {
    "tiktok": "https://www.tiktok.com/upload",
    "instagram": "https://www.instagram.com/",
    "youtube": "https://studio.youtube.com/channel/UC/upload",
}


@app.post("/api/publish/assisted-prepare")
async def publish_assisted_prepare(request: Request):
    """Prepara metadados e abre página de upload no Safari para publicação assistida.

    Retorna: título, descrição, hashtags, URL de upload, caminho do vídeo.
    O frontend usa window.open() para abrir a URL e navigator.clipboard para copiar metadados.
    """
    body = await request.json()
    job_id = body.get("job_id", "").strip()
    platform = body.get("platform", "tiktok").strip().lower()

    if not job_id:
        return JSONResponse(status_code=400, content={"detail": "job_id obrigatório"})
    if platform not in PLATFORM_UPLOAD_URLS:
        return JSONResponse(status_code=400, content={"detail": f"Plataforma inválida: {platform}. Use: tiktok, instagram, youtube"})

    # Buscar job na pipeline
    from src.production.pipeline import ProductionPipeline
    pipeline = ProductionPipeline(data_root="data")
    job = pipeline.get_job(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"detail": f"Job não encontrado: {job_id}"})

    video_path = job.get("output_path", "") or job.get("video_path", "")
    if not video_path or not Path(video_path).exists():
        return JSONResponse(status_code=404, content={"detail": "Arquivo de vídeo não encontrado"})

    title = job.get("title", f"GTA VI Reel {job_id}")
    description = job.get("description", "") or f"GTA VI conteúdo exclusivo! 🎮 #GTA6 #GTAVI #LeonidaFlashBR"
    hashtags = job.get("hashtags", ["#GTA6", "#GTAVI", "#RockstarGames", "#LeonidaFlashBR", "#Gaming"])

    # Contas por plataforma
    accounts = {
        "tiktok": "@leonidagta6flashbr",
        "instagram": "@leonidagta6flashbr",
        "youtube": "@leonidagta6flashbr",
    }

    upload_url = PLATFORM_UPLOAD_URLS[platform]
    account = accounts.get(platform, "")

    # Copiar metadados para clipboard via osascript (macOS)
    clipboard_text = f"{title}\n\n{description}\n\n{' '.join(hashtags)}"
    try:
        subprocess.run(
            ["osascript", "-e", f'set the clipboard to "{clipboard_text.replace(chr(34), chr(92)+chr(34))}"'],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass  # Clipboard é best-effort; frontend tem fallback

    return {
        "job_id": job_id,
        "platform": platform,
        "account": account,
        "title": title,
        "description": description,
        "hashtags": hashtags,
        "upload_url": upload_url,
        "video_path": video_path,
        "video_filename": Path(video_path).name,
        "clipboard_ready": True,
        "instructions": f"1. Arraste '{Path(video_path).name}' para a página de upload\n2. Cole título/descrição (Ctrl+V)\n3. Confirme a publicação\n4. Volte ao dashboard e clique 'Confirmar Publicação'",
    }


@app.post("/api/publish/assisted-confirm")
async def publish_assisted_confirm(request: Request):
    """Confirma publicação assistida após usuário completar upload manualmente."""
    body = await request.json()
    job_id = body.get("job_id", "").strip()
    platform = body.get("platform", "").strip()
    published_url = body.get("published_url", "").strip()

    if not job_id:
        return JSONResponse(status_code=400, content={"detail": "job_id obrigatório"})

    # Registrar no scheduler como publicado
    sched_file = Path("data/scheduler/autopublish_jobs.json")
    jobs = []
    if sched_file.exists():
        try:
            jobs = json.loads(sched_file.read_text())
        except (json.JSONDecodeError, OSError):
            jobs = []

    entry = {
        "job_id": job_id,
        "platform": platform,
        "status": "published",
        "approval_status": "approved",
        "published_url": published_url,
        "published_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "method": "assisted",
    }

    # Atualizar ou adicionar
    found = False
    for i, j in enumerate(jobs):
        if j.get("job_id") == job_id and j.get("platform") == platform:
            jobs[i] = entry
            found = True
            break
    if not found:
        jobs.append(entry)

    sched_file.parent.mkdir(parents=True, exist_ok=True)
    sched_file.write_text(json.dumps(jobs, indent=2, ensure_ascii=False))

    return {"confirmed": True, "job_id": job_id, "platform": platform, "status": "published"}


@app.get("/api/publish/ready-jobs")
async def publish_ready_jobs():
    """Lista jobs prontos para publicação (completed na pipeline, com vídeo válido)."""
    from src.production.pipeline import ProductionPipeline
    pipeline = ProductionPipeline(data_root="data")
    ready = []
    for jid, job in pipeline._jobs.items():
        if job.status == "completed":
            video_path = job.output_path or job.video_path
            if video_path and Path(video_path).exists():
                ready.append({
                    "job_id": jid,
                    "title": job.title,
                    "platform": job.platform,
                    "video_path": video_path,
                    "video_filename": Path(video_path).name,
                    "created_at": job.created_at,
                })
    ready.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    return {"jobs": ready, "count": len(ready)}


# =============================================================================
# MISSÃO 040.1 ETAPA 2+3 — Publicação Assistida + Auto-Publish Connectors
# =============================================================================

PLATFORM_UPLOAD_URLS = {
    "tiktok": "https://www.tiktok.com/upload",
    "instagram": "https://www.instagram.com/",
    "youtube": "https://studio.youtube.com/channel/UC/upload",
}


@app.post("/api/publish/assisted-prepare")
async def publish_assisted_prepare(request: Request):
    """Prepara metadados e abre página de upload no Safari para publicação assistida."""
    body = await request.json()
    job_id = body.get("job_id", "").strip()
    platform = body.get("platform", "tiktok").strip().lower()

    if not job_id:
        return JSONResponse(status_code=400, content={"detail": "job_id obrigatório"})
    if platform not in PLATFORM_UPLOAD_URLS:
        return JSONResponse(status_code=400, content={"detail": f"Plataforma inválida: {platform}"})

    from src.production.pipeline import ProductionPipeline
    pipeline = ProductionPipeline(data_root="data")
    job = pipeline.get_job(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"detail": f"Job não encontrado: {job_id}"})

    video_path = job.get("output_path", "") or job.get("video_path", "")
    if not video_path or not Path(video_path).exists():
        return JSONResponse(status_code=404, content={"detail": "Arquivo de vídeo não encontrado"})

    title = job.get("title", f"GTA VI Reel {job_id}")
    description = job.get("description", "") or f"GTA VI conteúdo exclusivo! 🎮 #GTA6 #GTAVI #LeonidaFlashBR"
    hashtags = job.get("hashtags", ["#GTA6", "#GTAVI", "#RockstarGames", "#LeonidaFlashBR", "#Gaming"])

    accounts = {
        "tiktok": "@leonidagta6flashbr",
        "instagram": "@leonidagta6flashbr",
        "youtube": "@leonidagta6flashbr",
    }

    upload_url = PLATFORM_UPLOAD_URLS[platform]
    account = accounts.get(platform, "")

    clipboard_text = f"{title}\n\n{description}\n\n{' '.join(hashtags)}"
    try:
        subprocess.run(
            ["osascript", "-e", f'set the clipboard to "{clipboard_text.replace(chr(34), chr(92)+chr(34))}"'],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass

    return {
        "job_id": job_id,
        "platform": platform,
        "account": account,
        "title": title,
        "description": description,
        "hashtags": hashtags,
        "upload_url": upload_url,
        "video_path": video_path,
        "video_filename": Path(video_path).name,
        "clipboard_ready": True,
        "instructions": f"1. Arraste '{Path(video_path).name}' para a página de upload\n2. Cole título/descrição (Ctrl+V)\n3. Confirme a publicação\n4. Volte ao dashboard e clique 'Confirmar Publicação'",
    }


@app.post("/api/publish/assisted-confirm")
async def publish_assisted_confirm(request: Request):
    """Confirma publicação assistida após usuário completar upload manualmente."""
    body = await request.json()
    job_id = body.get("job_id", "").strip()
    platform = body.get("platform", "").strip()
    published_url = body.get("published_url", "").strip()

    if not job_id:
        return JSONResponse(status_code=400, content={"detail": "job_id obrigatório"})

    sched_file = Path("data/scheduler/autopublish_jobs.json")
    jobs = []
    if sched_file.exists():
        try:
            jobs = json.loads(sched_file.read_text())
        except (json.JSONDecodeError, OSError):
            jobs = []

    entry = {
        "job_id": job_id,
        "platform": platform,
        "status": "published",
        "approval_status": "approved",
        "published_url": published_url,
        "published_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "method": "assisted",
    }

    found = False
    for i, j in enumerate(jobs):
        if j.get("job_id") == job_id and j.get("platform") == platform:
            jobs[i] = entry
            found = True
            break
    if not found:
        jobs.append(entry)

    sched_file.parent.mkdir(parents=True, exist_ok=True)
    sched_file.write_text(json.dumps(jobs, indent=2, ensure_ascii=False))

    return {"confirmed": True, "job_id": job_id, "platform": platform, "status": "published"}


@app.get("/api/publish/ready-jobs")
async def publish_ready_jobs():
    """Lista jobs prontos para publicação (completed na pipeline, com vídeo válido)."""
    from src.production.pipeline import ProductionPipeline
    pipeline = ProductionPipeline(data_root="data")
    ready = []
    for jid, job in pipeline._jobs.items():
        if job.status == "completed":
            video_path = job.output_path or job.video_path
            if video_path and Path(video_path).exists():
                ready.append({
                    "job_id": jid,
                    "title": job.title,
                    "platform": job.platform,
                    "video_path": video_path,
                    "video_filename": Path(video_path).name,
                    "created_at": job.created_at,
                })
    ready.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    return {"jobs": ready, "count": len(ready)}


@app.get("/api/auto-publish/status")
async def auto_publish_status():
    """Status dos conectores de publicação automática."""
    from src.publishing.auto_publisher import AutoPublisher
    publisher = AutoPublisher()
    return publisher.get_status()


@app.post("/api/auto-publish/publish")
async def auto_publish_execute(request: Request):
    """Publica vídeo via API automática (simulado sem credenciais, real com OAuth)."""
    from src.publishing.auto_publisher import AutoPublisher
    body = await request.json()
    platform = body.get("platform", "").strip().lower()
    job_id = body.get("job_id", "").strip()
    video_path = body.get("video_path", "").strip()
    title = body.get("title", "")
    description = body.get("description", "")
    tags = body.get("tags", [])

    if not platform or not video_path:
        return JSONResponse(status_code=400, content={"detail": "platform e video_path obrigatórios"})

    publisher = AutoPublisher()
    result = publisher.publish(
        platform=platform,
        video_path=video_path,
        title=title,
        description=description,
        tags=tags,
        job_id=job_id,
    )
    return result.to_dict()


@app.post("/api/auto-publish/publish-all")
async def auto_publish_all(request: Request):
    """Publica em todas as plataformas configuradas."""
    from src.publishing.auto_publisher import AutoPublisher
    body = await request.json()
    job_id = body.get("job_id", "").strip()
    video_path = body.get("video_path", "").strip()
    title = body.get("title", "")
    description = body.get("description", "")
    tags = body.get("tags", [])
    platforms = body.get("platforms", None)

    if not video_path:
        return JSONResponse(status_code=400, content={"detail": "video_path obrigatório"})

    publisher = AutoPublisher()
    results = publisher.publish_all(
        video_path=video_path,
        title=title,
        description=description,
        tags=tags,
        job_id=job_id,
        platforms=platforms,
    )
    return {"results": [r.to_dict() for r in results], "count": len(results)}


@app.get("/api/auto-publish/history")
async def auto_publish_history(limit: int = 50):
    """Histórico de publicações automáticas."""
    from src.publishing.auto_publisher import AutoPublisher
    publisher = AutoPublisher()
    return {"history": publisher.get_publish_history(limit=limit)}


# =============================================================================
# MISSAO 040.2 -- Radar Viral Instagram
# =============================================================================

@app.get("/api/instagram-radar/search")
async def instagram_radar_search(profile: str = "", hashtag: str = "", max_results: int = 10):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from src.research.instagram_radar import InstagramRadar
    def _do():
        radar = InstagramRadar()
        if profile:
            return radar.search_profile(profile, max_results)
        elif hashtag:
            return radar.search_hashtag(hashtag, max_results)
        else:
            return radar.search_all(max_per_source=max_results)
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as ex:
        results = await loop.run_in_executor(ex, _do)
    results = InstagramRadar().check_already_imported(results)
    return {"results": results, "count": len(results)}

@app.get("/api/instagram-radar/discover")
async def instagram_radar_discover(max_per_source: int = 5):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from src.research.instagram_radar import InstagramRadar
    def _do():
        radar = InstagramRadar()
        r = radar.search_all(max_per_source=max_per_source)
        r = radar.check_already_imported(r)
        radar.save_cache(r, "latest")
        return r
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as ex:
        results = await loop.run_in_executor(ex, _do)
    return {"results": results, "count": len(results)}

@app.get("/api/instagram-radar/cache")
async def instagram_radar_cache(max_age_hours: int = 24):
    from src.research.instagram_radar import InstagramRadar
    radar = InstagramRadar()
    results = radar.load_cache("latest", max_age_hours)
    return {"results": results, "count": len(results), "cached": len(results) > 0}

@app.get("/api/instagram-radar/filters")
async def instagram_radar_filters():
    from src.research.instagram_radar import InstagramRadar
    return InstagramRadar().get_filter_options()

@app.get("/api/instagram-radar/profiles")
async def instagram_radar_profiles():
    from src.research.instagram_radar import InstagramRadar
    return {"profiles": InstagramRadar()._monitored_profiles}

@app.post("/api/instagram-radar/profiles/add")
async def instagram_radar_add_profile(request: Request):
    from src.research.instagram_radar import InstagramRadar
    body = await request.json()
    profile = body.get("profile", "").strip()
    if not profile:
        return JSONResponse(status_code=400, content={"detail": "profile obrigatorio"})
    radar = InstagramRadar()
    return {"profiles": radar.add_monitored_profile(profile), "added": profile}

@app.post("/api/instagram-radar/profiles/remove")
async def instagram_radar_remove_profile(request: Request):
    from src.research.instagram_radar import InstagramRadar
    body = await request.json()
    profile = body.get("profile", "").strip()
    if not profile:
        return JSONResponse(status_code=400, content={"detail": "profile obrigatorio"})
    radar = InstagramRadar()
    return {"profiles": radar.remove_monitored_profile(profile), "removed": profile}
