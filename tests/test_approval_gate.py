"""FASE 3 — Testes de aprovação manual obrigatória e gate de publicação."""
import json
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


@pytest.fixture
def tmp_data(tmp_path):
    """Cria estrutura de dados temporária para testes."""
    (tmp_path / "scheduler").mkdir()
    (tmp_path / "production_pipeline").mkdir()
    return tmp_path


@pytest.fixture
def sample_scheduler_jobs():
    """Jobs de exemplo no scheduler."""
    return [
        {"job_id": "sched-001", "state": "pending", "quality_gate_passed": False,
         "content_hash": "abc123", "idempotency_key": "idem-001"},
        {"job_id": "sched-002", "state": "approved", "quality_gate_passed": True,
         "content_hash": "def456", "idempotency_key": "idem-002"},
        {"job_id": "sched-003", "state": "failed", "quality_gate_passed": False,
         "content_hash": "ghi789", "idempotency_key": "idem-003"},
    ]


class TestApprovalGate:
    """Testa gate de aprovação no assisted_publish."""

    def test_is_approved_returns_true_for_approved_job(self, tmp_data, sample_scheduler_jobs):
        from scripts.assisted_publish import _is_approved, DATA_ROOT
        import scripts.assisted_publish as ap
        # Patch DATA_ROOT
        original = ap.DATA_ROOT
        ap.DATA_ROOT = tmp_data
        try:
            sched_file = tmp_data / "scheduler" / "autopublish_jobs.json"
            sched_file.write_text(json.dumps(sample_scheduler_jobs))
            job = {"scheduler_job_id": "sched-002"}
            assert _is_approved(job) is True
        finally:
            ap.DATA_ROOT = original

    def test_is_approved_returns_false_for_pending_job(self, tmp_data, sample_scheduler_jobs):
        from scripts.assisted_publish import _is_approved
        import scripts.assisted_publish as ap
        original = ap.DATA_ROOT
        ap.DATA_ROOT = tmp_data
        try:
            sched_file = tmp_data / "scheduler" / "autopublish_jobs.json"
            sched_file.write_text(json.dumps(sample_scheduler_jobs))
            job = {"scheduler_job_id": "sched-001"}
            assert _is_approved(job) is False
        finally:
            ap.DATA_ROOT = original

    def test_is_approved_returns_false_for_missing_scheduler_id(self, tmp_data, sample_scheduler_jobs):
        from scripts.assisted_publish import _is_approved
        import scripts.assisted_publish as ap
        original = ap.DATA_ROOT
        ap.DATA_ROOT = tmp_data
        try:
            sched_file = tmp_data / "scheduler" / "autopublish_jobs.json"
            sched_file.write_text(json.dumps(sample_scheduler_jobs))
            job = {}  # sem scheduler_job_id
            assert _is_approved(job) is False
        finally:
            ap.DATA_ROOT = original

    def test_is_approved_returns_false_when_scheduler_file_missing(self, tmp_data):
        from scripts.assisted_publish import _is_approved
        import scripts.assisted_publish as ap
        original = ap.DATA_ROOT
        ap.DATA_ROOT = tmp_data
        try:
            job = {"scheduler_job_id": "nonexistent"}
            assert _is_approved(job) is False
        finally:
            ap.DATA_ROOT = original

    def test_get_ready_jobs_requires_approval_by_default(self, tmp_data, sample_scheduler_jobs):
        from scripts.assisted_publish import get_ready_jobs
        import scripts.assisted_publish as ap
        original = ap.DATA_ROOT
        ap.DATA_ROOT = tmp_data
        try:
            # Criar pipeline jobs
            pipeline_jobs = {
                "pipe-001": {"status": "completed", "output_path": str(tmp_data / "video1.mp4"),
                             "scheduler_job_id": "sched-001", "created_at": time.time()},
                "pipe-002": {"status": "completed", "output_path": str(tmp_data / "video2.mp4"),
                             "scheduler_job_id": "sched-002", "created_at": time.time()},
            }
            (tmp_data / "production_pipeline" / "production_jobs.json").write_text(
                json.dumps(pipeline_jobs))
            # Criar arquivos de vídeo fake (>100KB)
            (tmp_data / "video1.mp4").write_bytes(b"x" * 200_000)
            (tmp_data / "video2.mp4").write_bytes(b"x" * 200_000)
            # Scheduler
            sched_file = tmp_data / "scheduler" / "autopublish_jobs.json"
            sched_file.write_text(json.dumps(sample_scheduler_jobs))

            # Com require_approval=True (default), só approved passa
            ready = get_ready_jobs(require_approval=True)
            assert len(ready) == 1
            assert ready[0]["scheduler_job_id"] == "sched-002"
        finally:
            ap.DATA_ROOT = original

    def test_get_ready_jobs_show_all_includes_unapproved(self, tmp_data, sample_scheduler_jobs):
        from scripts.assisted_publish import get_ready_jobs
        import scripts.assisted_publish as ap
        original = ap.DATA_ROOT
        ap.DATA_ROOT = tmp_data
        try:
            pipeline_jobs = {
                "pipe-001": {"status": "completed", "output_path": str(tmp_data / "video1.mp4"),
                             "scheduler_job_id": "sched-001", "created_at": time.time()},
                "pipe-002": {"status": "completed", "output_path": str(tmp_data / "video2.mp4"),
                             "scheduler_job_id": "sched-002", "created_at": time.time()},
            }
            (tmp_data / "production_pipeline" / "production_jobs.json").write_text(
                json.dumps(pipeline_jobs))
            (tmp_data / "video1.mp4").write_bytes(b"x" * 200_000)
            (tmp_data / "video2.mp4").write_bytes(b"x" * 200_000)
            sched_file = tmp_data / "scheduler" / "autopublish_jobs.json"
            sched_file.write_text(json.dumps(sample_scheduler_jobs))

            # Com require_approval=False, ambos aparecem
            all_jobs = get_ready_jobs(require_approval=False)
            assert len(all_jobs) == 2
        finally:
            ap.DATA_ROOT = original


class TestPublishStateMachineApproval:
    """Testa estados de aprovação na PublishStateMachine."""

    def test_valid_transitions_include_awaiting_auth_to_scheduled(self):
        from src.publishing.publish_state_machine import PublishState, VALID_TRANSITIONS
        assert PublishState.SCHEDULED in VALID_TRANSITIONS[PublishState.AWAITING_AUTH]

    def test_published_is_terminal_state(self):
        from src.publishing.publish_state_machine import PublishState, VALID_TRANSITIONS
        assert VALID_TRANSITIONS[PublishState.PUBLISHED] == []

    def test_failed_can_retry_to_preparing(self):
        from src.publishing.publish_state_machine import PublishState, VALID_TRANSITIONS
        assert PublishState.PREPARING in VALID_TRANSITIONS[PublishState.FAILED]


class TestAutoPublishSchedulerApproval:
    """Testa aprovação/rejeição via AutoPublishScheduler."""

    def test_check_quality_gate_approve_sets_state(self, tmp_data):
        from src.automation.autopublish_scheduler import AutoPublishScheduler, AutoPublishJob
        scheduler = AutoPublishScheduler(data_root=tmp_data)
        job = AutoPublishJob(
            job_id="test-approve",
            profile_id="br_tiktok",
            platform="tiktok",
            video_path="/fake/video.mp4",
            title="Test Approve",
        )
        scheduler.submit_job(job)
        result = scheduler.check_quality_gate("test-approve", passed=True, score=0.95)
        assert result["state"] == "approved"
        assert result["quality_gate_passed"] is True

    def test_check_quality_gate_reject_sets_failed(self, tmp_data):
        from src.automation.autopublish_scheduler import AutoPublishScheduler, AutoPublishJob
        scheduler = AutoPublishScheduler(data_root=tmp_data)
        job = AutoPublishJob(
            job_id="test-reject",
            profile_id="br_tiktok",
            platform="tiktok",
            video_path="/fake/video.mp4",
            title="Test Reject",
        )
        scheduler.submit_job(job)
        result = scheduler.check_quality_gate("test-reject", passed=False, score=0.3)
        assert result["state"] == "failed"
        assert result["quality_gate_passed"] is False

    def test_idempotency_prevents_duplicate_jobs(self, tmp_data):
        from src.automation.autopublish_scheduler import AutoPublishScheduler, AutoPublishJob
        scheduler = AutoPublishScheduler(data_root=tmp_data)
        job = AutoPublishJob(
            job_id="test-dup",
            profile_id="br_tiktok",
            platform="tiktok",
            video_path="/fake/video.mp4",
            title="Test Dup",
            idempotency_key="unique-key-123",
        )
        r1 = scheduler.submit_job(job)
        r2 = scheduler.submit_job(job)
        assert r1.get("status") == "submitted" or "job_id" in r1
        assert "already exists" in r2.get("message", "") or r2.get("status") != "submitted"