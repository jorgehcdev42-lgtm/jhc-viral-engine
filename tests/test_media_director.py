"""Tests for JHC Autonomous Media Director — scheduler and job management."""

from __future__ import annotations

import json
import time
import pytest
from pathlib import Path

from src.automation.media_director import (
    MediaDirector,
    ProductionJob,
    ProductionBatch,
    JobState,
)


@pytest.fixture
def director(tmp_path: Path) -> MediaDirector:
    return MediaDirector(tmp_path, "test_profile")


def _make_topics(n: int = 3) -> list[dict]:
    return [
        {
            "title": f"Topic {i}",
            "source_url": f"https://example.com/{i}",
            "source_name": "Eurogamer",
            "category": "news",
        }
        for i in range(n)
    ]


class TestProductionJob:
    """Test immutable job transitions and serialization."""

    def test_transition_preserves_id(self) -> None:
        job = ProductionJob(
            job_id="j1", profile_id="p1", topic="Test",
            source_url="", source_name="", category="news",
            created_at=time.time(),
        )
        updated = job.transition(JobState.SCRIPTING, script_path="/tmp/s.txt")
        assert updated.job_id == "j1"
        assert updated.state == JobState.SCRIPTING
        assert updated.script_path == "/tmp/s.txt"
        assert job.state == JobState.PENDING  # Original unchanged

    def test_transition_to_all_states(self) -> None:
        job = ProductionJob(
            job_id="j2", profile_id="p1", topic="Test",
            source_url="", source_name="", category="news",
            created_at=time.time(),
        )
        for state in JobState:
            updated = job.transition(state)
            assert updated.state == state

    def test_failed_increments_retry(self) -> None:
        job = ProductionJob(
            job_id="j3", profile_id="p1", topic="Test",
            source_url="", source_name="", category="news",
            created_at=time.time(), retry_count=0,
        )
        failed = job.transition(JobState.FAILED, error="timeout", retry_count=1)
        assert failed.retry_count == 1
        assert failed.error == "timeout"

    def test_to_dict_from_dict_roundtrip(self) -> None:
        job = ProductionJob(
            job_id="j4", profile_id="p1", topic="Roundtrip test",
            source_url="https://x.com/1", source_name="VGC",
            category="rumor", state=JobState.APPROVED,
            script_path="/s.txt", video_path="/v.mp4",
            quality_score=0.92, quality_status="READY_FOR_PUBLICATION",
            created_at=1000.0, updated_at=2000.0, retry_count=1,
        )
        restored = ProductionJob.from_dict(job.to_dict())
        assert restored.job_id == job.job_id
        assert restored.state == job.state
        assert restored.quality_score == job.quality_score
        assert restored.retry_count == job.retry_count


class TestProductionBatch:
    """Test batch creation, filtering, and serialization."""

    def test_pending_jobs_filter(self) -> None:
        jobs = (
            ProductionJob(job_id="a", profile_id="p", topic="T", source_url="", source_name="", category="news", state=JobState.PENDING),
            ProductionJob(job_id="b", profile_id="p", topic="T", source_url="", source_name="", category="news", state=JobState.APPROVED),
            ProductionJob(job_id="c", profile_id="p", topic="T", source_url="", source_name="", category="news", state=JobState.PENDING),
        )
        batch = ProductionBatch(batch_id="b1", profile_id="p", jobs=jobs, created_at=time.time())
        assert len(batch.pending_jobs()) == 2
        assert len(batch.completed_jobs()) == 1

    def test_failed_jobs_filter(self) -> None:
        jobs = (
            ProductionJob(job_id="a", profile_id="p", topic="T", source_url="", source_name="", category="news", state=JobState.FAILED),
            ProductionJob(job_id="b", profile_id="p", topic="T", source_url="", source_name="", category="news", state=JobState.REJECTED),
        )
        batch = ProductionBatch(batch_id="b2", profile_id="p", jobs=jobs, created_at=time.time())
        assert len(batch.failed_jobs()) == 1
        assert len(batch.completed_jobs()) == 1  # REJECTED counts as completed

    def test_batch_roundtrip(self) -> None:
        jobs = (
            ProductionJob(job_id="x", profile_id="p", topic="RT", source_url="", source_name="", category="news"),
        )
        batch = ProductionBatch(batch_id="brt", profile_id="p", jobs=jobs, created_at=999.0)
        restored = ProductionBatch.from_dict(batch.to_dict())
        assert restored.batch_id == "brt"
        assert len(restored.jobs) == 1
        assert restored.jobs[0].job_id == "x"


class TestMediaDirectorPersistence:
    """Test batch persistence, checkpoint/resume, and logging."""

    def test_create_batch_persists_to_disk(self, director: MediaDirector, tmp_path: Path) -> None:
        batch = director.create_batch(_make_topics(3))
        batch_file = tmp_path / "test_profile" / "batches" / "production_batch.json"
        assert batch_file.exists()
        data = json.loads(batch_file.read_text(encoding="utf-8"))
        assert len(data["jobs"]) == 3

    def test_load_batch_returns_saved(self, director: MediaDirector) -> None:
        original = director.create_batch(_make_topics(2))
        loaded = director.load_batch()
        assert loaded is not None
        assert loaded.batch_id == original.batch_id
        assert len(loaded.jobs) == 2

    def test_load_batch_returns_none_when_missing(self, tmp_path: Path) -> None:
        d = MediaDirector(tmp_path, "nonexistent")
        assert d.load_batch() is None

    def test_checkpoint_survives_reload(self, director: MediaDirector) -> None:
        batch = director.create_batch(_make_topics(3))
        # Simulate state change by saving modified batch
        updated_jobs = tuple(
            j.transition(JobState.APPROVED) if j.job_id == batch.jobs[0].job_id else j
            for j in batch.jobs
        )
        updated_batch = ProductionBatch(
            batch_id=batch.batch_id, profile_id=batch.profile_id,
            jobs=updated_jobs, created_at=batch.created_at,
        )
        director._save_batch(updated_batch)

        # Reload and verify checkpoint
        reloaded = director.load_batch()
        assert reloaded.jobs[0].state == JobState.APPROVED
        assert reloaded.jobs[1].state == JobState.PENDING

    def test_structured_log_created(self, director: MediaDirector, tmp_path: Path) -> None:
        director.create_batch(_make_topics(1))
        log_file = tmp_path / "test_profile" / "batches" / "production_log.jsonl"
        assert log_file.exists()
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) >= 1
        entry = json.loads(lines[0])
        assert entry["event"] == "batch_created"
        assert "timestamp" in entry

    def test_get_batch_summary(self, director: MediaDirector) -> None:
        director.create_batch(_make_topics(4))
        summary = director.get_batch_summary()
        assert summary["total_jobs"] == 4
        assert summary["state_counts"]["pending"] == 4

    def test_get_batch_summary_no_batch(self, tmp_path: Path) -> None:
        d = MediaDirector(tmp_path, "empty")
        summary = d.get_batch_summary()
        assert "error" in summary


class TestMediaDirectorIdempotency:
    """Test that operations are safe to repeat."""

    def test_create_batch_overwrites_previous(self, director: MediaDirector) -> None:
        b1 = director.create_batch(_make_topics(2))
        b2 = director.create_batch(_make_topics(5))
        loaded = director.load_batch()
        assert loaded.batch_id == b2.batch_id
        assert len(loaded.jobs) == 5

    def test_job_transition_is_immutable(self) -> None:
        job = ProductionJob(
            job_id="imm", profile_id="p", topic="T",
            source_url="", source_name="", category="news",
            created_at=time.time(),
        )
        t1 = job.transition(JobState.SCRIPTING)
        t2 = job.transition(JobState.NARRATING)
        assert t1.state == JobState.SCRIPTING
        assert t2.state == JobState.NARRATING
        assert job.state == JobState.PENDING  # Original never mutated