"""Persistent production scheduler for JHC Viral Engine.

Manages daily production quotas, calendar-based scheduling, and
resource-aware job execution. Designed for MacBook M2 8GB: sequential
processing with configurable limits per profile.

Integrates with MediaDirector for batch management and TopicSelector
for editorial queue population.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class DailyQuota:
 """Production quota configuration for a profile."""
 profile_id: str
 max_candidates_per_day: int = 5
 max_approved_per_day: int = 3
 min_quality_score: float = 0.7
 require_authorized_media: bool = False
 enabled: bool = True

 @classmethod
 def from_dict(cls, data: dict) -> DailyQuota:
 return cls(
 profile_id=data["profile_id"],
 max_candidates_per_day=data.get("max_candidates_per_day", 5),
 max_approved_per_day=data.get("max_approved_per_day", 3),
 min_quality_score=data.get("min_quality_score", 0.7),
 require_authorized_media=data.get("require_authorized_media", False),
 enabled=data.get("enabled", True),
 )

 def to_dict(self) -> dict:
 return {
 "profile_id": self.profile_id,
 "max_candidates_per_day": self.max_candidates_per_day,
 "max_approved_per_day": self.max_approved_per_day,
 "min_quality_score": self.min_quality_score,
 "require_authorized_media": self.require_authorized_media,
 "enabled": self.enabled,
 }

@dataclass(frozen=True)
class CalendarEntry:
 """A scheduled production slot in the editorial calendar."""
 date: str # YYYY-MM-DD
 profile_id: str
 topic: str
 source_url: str
 template_name: str
 status: str = "planned" # planned, producing, completed, skipped, failed
 created_at: float = 0.0
 completed_at: Optional[float] = None
 quality_score: Optional[float] = None
 output_path: Optional[str] = None
 notes: str = ""

 @classmethod
 def from_dict(cls, data: dict) -> CalendarEntry:
 return cls(
 date=data["date"],
 profile_id=data["profile_id"],
 topic=data["topic"],
 source_url=data.get("source_url", ""),
 template_name=data.get("template_name", "news_summary"),
 status=data.get("status", "planned"),
 created_at=data.get("created_at", 0.0),
 completed_at=data.get("completed_at"),
 quality_score=data.get("quality_score"),
 output_path=data.get("output_path"),
 notes=data.get("notes", ""),
 )

 def to_dict(self) -> dict:
 return {
 "date": self.date,
 "profile_id": self.profile_id,
 "topic": self.topic,
 "source_url": self.source_url,
 "template_name": self.template_name,
 "status": self.status,
 "created_at": self.created_at,
 "completed_at": self.completed_at,
 "quality_score": self.quality_score,
 "output_path": self.output_path,
 "notes": self.notes,
 }

class ProductionScheduler:
 """Manage production quotas, calendar, and resource limits."""

 QUOTAS_FILE = "quotas.json"
 CALENDAR_FILE = "calendar.json"
 DAILY_STATS_FILE = "daily_stats.json"

 DEFAULT_QUOTAS = {
 "gta6-br": DailyQuota(profile_id="gta6-br", max_candidates_per_day=5),
 "gta6-global": DailyQuota(profile_id="gta6-global", max_candidates_per_day=5),
 "gta6": DailyQuota(profile_id="gta6", max_candidates_per_day=5, enabled=False),
 }

 def __init__(self, data_root: Path) -> None:
 self.data_root = data_root
 self.scheduler_dir = data_root / "scheduler"
 self.scheduler_dir.mkdir(parents=True, exist_ok=True)
 self._quotas: dict[str, DailyQuota] = {}
 self._load_quotas()

 def _load_quotas(self) -> None:
 """Load quota configurations from disk."""
 quotas_path = self.scheduler_dir / self.QUOTAS_FILE
 if quotas_path.exists():
 try:
 data = json.loads(quotas_path.read_text(encoding="utf-8"))
 self._quotas = {k: DailyQuota.from_dict(v) for k, v in data.items()}
 except (json.JSONDecodeError, KeyError):
 logger.warning("Could not load quotas; using defaults")
 self._quotas = dict(self.DEFAULT_QUOTAS)
 else:
 self._quotas = dict(self.DEFAULT_QUOTAS)
 self._save_quotas()

 def _save_quotas(self) -> None:
 """Persist quota configurations."""
 quotas_path = self.scheduler_dir / self.QUOTAS_FILE
 data = {k: v.to_dict() for k, v in self._quotas.items()}
 quotas_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

 def get_quota(self, profile_id: str) -> DailyQuota:
 """Get quota for a profile, creating default if missing."""
 if profile_id not in self._quotas:
 self._quotas[profile_id] = DailyQuota(profile_id=profile_id)
 self._save_quotas()
 return self._quotas[profile_id]

 def update_quota(self, quota: DailyQuota) -> None:
 """Update quota for a profile."""
 self._quotas[quota.profile_id] = quota
 self._save_quotas()

 def get_today_str(self) -> str:
 """Get today's date string in YYYY-MM-DD format."""
 from datetime import date
 return date.today().isoformat()

 def get_daily_stats(self, profile_id: str, date_str: Optional[str] = None) -> dict:
 """Get production statistics for a specific day."""
 if date_str is None:
 date_str = self.get_today_str()

 stats_path = self.scheduler_dir / self.DAILY_STATS_FILE
 if not stats_path.exists():
 return {"date": date_str, "profile_id": profile_id, "candidates": 0, "approved": 0, "failed": 0}

 try:
 all_stats = json.loads(stats_path.read_text(encoding="utf-8"))
 key = f"{profile_id}:{date_str}"
 if key in all_stats:
 return all_stats[key]
 except (json.JSONDecodeError, KeyError):
 pass

 return {"date": date_str, "profile_id": profile_id, "candidates": 0, "approved": 0, "failed": 0}

 def record_production(self, profile_id: str, status: str, quality_score: float = 0.0) -> dict:
 """Record a production result for today's stats."""
 date_str = self.get_today_str()
 stats = self.get_daily_stats(profile_id, date_str)

 if status == "approved":
 stats["approved"] = stats.get("approved", 0) + 1
 elif status == "failed" or status == "rejected":
 stats["failed"] = stats.get("failed", 0) + 1
 stats["candidates"] = stats.get("candidates", 0) + 1

 if quality_score > 0:
 scores = stats.setdefault("quality_scores", [])
 scores.append(quality_score)

 stats_path = self.scheduler_dir / self.DAILY_STATS_FILE
 all_stats = {}
 if stats_path.exists():
 try:
 all_stats = json.loads(stats_path.read_text(encoding="utf-8"))
 except json.JSONDecodeError:
 pass

 key = f"{profile_id}:{date_str}"
 all_stats[key] = stats
 stats_path.write_text(json.dumps(all_stats, ensure_ascii=False, indent=2), encoding="utf-8")

 return stats

 def can_produce_today(self, profile_id: str) -> tuple[bool, str]:
 """Check if profile can produce more content today."""
 quota = self.get_quota(profile_id)
 if not quota.enabled:
 return False, f"Profile {profile_id} is disabled"

 stats = self.get_daily_stats(profile_id)
 candidates = stats.get("candidates", 0)
 approved = stats.get("approved", 0)

 if candidates >= quota.max_candidates_per_day:
 return False, f"Daily candidate limit reached ({candidates}/{quota.max_candidates_per_day})"
 if approved >= quota.max_approved_per_day:
 return False, f"Daily approved limit reached ({approved}/{quota.max_approved_per_day})"

 remaining_candidates = quota.max_candidates_per_day - candidates
 remaining_approved = quota.max_approved_per_day - approved
 return True, f"Can produce: {remaining_candidates} candidates, {remaining_approved} approved remaining"

 def add_calendar_entry(self, entry: CalendarEntry) -> None:
 """Add an entry to the editorial calendar."""
 calendar_path = self.scheduler_dir / self.CALENDAR_FILE
 entries: list[dict] = []
 if calendar_path.exists():
 try:
 entries = json.loads(calendar_path.read_text(encoding="utf-8"))
 except json.JSONDecodeError:
 entries = []

 new_entry = entry.to_dict()
 new_entry["created_at"] = time.time()
 entries.append(new_entry)

 # Keep last 90 days of entries
 cutoff = time.time() - (90 * 86400)
 entries = [e for e in entries if e.get("created_at", 0) > cutoff]

 calendar_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
 logger.info("Calendar entry added: %s on %s for %s", entry.topic[:40], entry.date, entry.profile_id)

 def get_calendar_entries(
 self, profile_id: str, start_date: str, end_date: str
 ) -> list[CalendarEntry]:
 """Get calendar entries for a date range."""
 calendar_path = self.scheduler_dir / self.CALENDAR_FILE
 if not calendar_path.exists():
 return []

 try:
 entries = json.loads(calendar_path.read_text(encoding="utf-8"))
 except json.JSONDecodeError:
 return []

 results = []
 for e in entries:
 if e["profile_id"] != profile_id:
 continue
 if start_date <= e["date"] <= end_date:
 results.append(CalendarEntry.from_dict(e))

 results.sort(key=lambda x: x.date)
 return results

 def update_calendar_entry_status(
 self, profile_id: str, date: str, topic: str, status: str,
 quality_score: Optional[float] = None, output_path: Optional[str] = None,
 ) -> bool:
 """Update status of a calendar entry."""
 calendar_path = self.scheduler_dir / self.CALENDAR_FILE
 if not calendar_path.exists():
 return False

 try:
 entries = json.loads(calendar_path.read_text(encoding="utf-8"))
 except json.JSONDecodeError:
 return False

 updated = False
 for e in entries:
 if e["profile_id"] == profile_id and e["date"] == date and e["topic"] == topic:
 e["status"] = status
 if quality_score is not None:
 e["quality_score"] = quality_score
 if output_path is not None:
 e["output_path"] = output_path
 if status in ("completed", "failed", "skipped"):
 e["completed_at"] = time.time()
 updated = True
 break

 if updated:
 calendar_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")

 return updated

 def get_scheduler_status(self) -> dict:
 """Get overall scheduler status for dashboard."""
 today = self.get_today_str()
 statuses = {}

 for pid, quota in self._quotas.items():
 if not quota.enabled:
 continue
 stats = self.get_daily_stats(pid, today)
 can_produce, reason = self.can_produce_today(pid)
 statuses[pid] = {
 "quota": quota.to_dict(),
 "today_stats": stats,
 "can_produce": can_produce,
 "reason": reason,
 }

 return {
 "date": today,
 "profiles": statuses,
 "total_active_profiles": sum(1 for q in self._quotas.values() if q.enabled),
 }