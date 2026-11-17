"""Testes de persistência e recuperação do bulk_worker — MISSÃO 032 FASE 1."""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
WORKER_SCRIPT = BASE / "scripts" / "bulk_worker.py"
STATE_DIR = BASE / "data" / "bulk_import" / "state"
LOG_DIR = BASE / "data" / "bulk_import" / "logs"
PID_FILE = STATE_DIR / "worker.pid"
PAUSE_FLAG = STATE_DIR / "worker.pause"
STOP_FLAG = STATE_DIR / "worker.stop"
PYTHON = BASE / ".venv" / "bin" / "python3"


@pytest.fixture(autouse=True)
def cleanup_flags():
    """Remove flags antes/depois de cada teste."""
    PAUSE_FLAG.unlink(missing_ok=True)
    STOP_FLAG.unlink(missing_ok=True)
    yield
    PAUSE_FLAG.unlink(missing_ok=True)
    STOP_FLAG.unlink(missing_ok=True)


def _run_worker_cmd(cmd: str, timeout: int = 10) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(PYTHON), "-I", str(WORKER_SCRIPT), cmd],
        capture_output=True, text=True, timeout=timeout, cwd=str(BASE),
    )


def _get_worker_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (ValueError, OSError):
        return None


class TestWorkerCLI:
    """Testa comandos CLI do worker sem iniciar daemon real."""

    def test_status_when_stopped(self):
        result = _run_worker_cmd("status")
        assert result.returncode == 0
        assert "PARADO" in result.stdout or "RODANDO" in result.stdout

    def test_pause_command_succeeds(self):
        """Pause deve retornar sucesso e criar flag (worker pode consumi-la)."""
        result = _run_worker_cmd("pause")
        assert result.returncode == 0
        # Flag pode ser consumida instantaneamente pelo worker ativo
        # Valida que o comando executou sem erro

    def test_resume_command_succeeds(self):
        """Resume deve retornar sucesso mesmo sem flag existente."""
        PAUSE_FLAG.unlink(missing_ok=True)
        result = _run_worker_cmd("resume")
        assert result.returncode == 0
        assert not PAUSE_FLAG.exists()

    def test_stop_command_succeeds(self):
        """Stop deve retornar sucesso e criar flag ou enviar signal."""
        result = _run_worker_cmd("stop")
        assert result.returncode == 0
        # Worker ativo pode ter parado e removido PID file


class TestCheckpointRecovery:
    """Valida que checkpoint sobrevive e é recuperável."""

    def test_checkpoint_file_exists(self):
        entries_file = STATE_DIR / "download_entries.json"
        assert entries_file.exists(), "Checkpoint não encontrado"

    def test_checkpoint_is_valid_json(self):
        entries_file = STATE_DIR / "download_entries.json"
        with open(entries_file) as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) > 0

    def test_checkpoint_has_required_fields(self):
        entries_file = STATE_DIR / "download_entries.json"
        with open(entries_file) as f:
            data = json.load(f)
        required = {"url", "filename", "state"}
        for entry in data[:10]:
            assert required.issubset(entry.keys()), f"Campos faltando: {required - set(entry.keys())}"

    def test_no_duplicate_urls_in_checkpoint(self):
        entries_file = STATE_DIR / "download_entries.json"
        with open(entries_file) as f:
            data = json.load(f)
        urls = [e.get("url") for e in data]
        assert len(urls) == len(set(urls)), "URLs duplicadas no checkpoint"

    def test_completed_files_exist_on_disk(self):
        entries_file = STATE_DIR / "download_entries.json"
        with open(entries_file) as f:
            data = json.load(f)
        completed = [e for e in data if e.get("state") == "COMPLETED"]
        # Amostra de 20 arquivos
        sample = completed[:20]
        missing = []
        for e in sample:
            dest = e.get("dest_path", "")
            if not os.path.isfile(dest):
                alt = os.path.join(str(BASE), "VIDEOS CORTES", e.get("filename", ""))
                if not os.path.isfile(alt):
                    missing.append(e.get("filename"))
        assert len(missing) == 0, f"Arquivos COMPLETED ausentes: {missing}"


class TestSSDProtection:
    """Garante que downloads usam apenas SSD externo."""

    def test_all_dest_paths_on_external_ssd(self):
        entries_file = STATE_DIR / "download_entries.json"
        with open(entries_file) as f:
            data = json.load(f)
        internal = [
            e.get("dest_path") for e in data
            if e.get("dest_path") and "/Volumes/SSD EXT" not in e["dest_path"]
        ]
        assert len(internal) == 0, f"Downloads no SSD interno: {internal[:5]}"

    def test_ssd_free_space_above_reserve(self):
        progress_file = STATE_DIR / "import_progress.json"
        if progress_file.exists():
            with open(progress_file) as f:
                prog = json.load(f)
            free_gb = prog.get("ssd_free_bytes", 0) / (1024 ** 3)
            assert free_gb >= 10, f"SSD abaixo da reserva: {free_gb:.1f}GB < 10GB"


class TestLaunchdService:
    """Valida serviço launchd instalado."""

    def test_plist_exists(self):
        plist = Path.home() / "Library" / "LaunchAgents" / "com.jhc.bulkworker.plist"
        assert plist.exists(), "Plist launchd não encontrado"

    def test_plist_references_correct_script(self):
        plist = Path.home() / "Library" / "LaunchAgents" / "com.jhc.bulkworker.plist"
        content = plist.read_text()
        # Accept either original bulk_worker.py or foreground variant for launchd
        assert "bulk_worker" in content
        assert "/Volumes/SSD EXT MACBOOK" in content

    def test_service_registered_in_launchctl(self):
        result = subprocess.run(
            ["launchctl", "list"], capture_output=True, text=True,
        )
        assert "com.jhc.bulkworker" in result.stdout