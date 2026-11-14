"""Storage abstraction layer for JHC Viral Engine.

Supports two backends:
- LocalFileSystem (default): reads/writes to DATA_ROOT on disk (dev/local)
- SupabaseStorage: reads/writes via Supabase PostgreSQL REST API (production)

Backend selection via JHC_STORAGE_BACKEND env var:
- "local" or unset → LocalFileSystem
- "supabase" → SupabaseStorage (requires SUPABASE_URL + SUPABASE_KEY)

All existing classes (AutoPublishScheduler, ProductionScheduler, etc.)
continue using DATA_ROOT paths unchanged. This module provides helpers
for future migration without breaking current code.
"""

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class StorageBackend(ABC):
    """Abstract storage interface."""

    @abstractmethod
    def read_json(self, path: str) -> dict | list | None:
        """Read JSON file/content. Returns None if not found."""
        ...

    @abstractmethod
    def write_json(self, path: str, data: dict | list) -> None:
        """Write JSON file/content."""
        ...

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Check if path/key exists."""
        ...

    @abstractmethod
    def read_text(self, path: str) -> str | None:
        """Read raw text. Returns None if not found."""
        ...

    @abstractmethod
    def write_text(self, path: str, content: str) -> None:
        """Write raw text."""
        ...


class LocalFileSystem(StorageBackend):
    """Filesystem-based storage (default for dev/local)."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        if p.is_absolute():
            return p
        return self.root / p

    def read_json(self, path: str) -> dict | list | None:
        resolved = self._resolve(path)
        if not resolved.exists():
            return None
        return json.loads(resolved.read_text(encoding="utf-8"))

    def write_json(self, path: str, data: dict | list) -> None:
        resolved = self._resolve(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    def read_text(self, path: str) -> str | None:
        resolved = self._resolve(path)
        if not resolved.exists():
            return None
        return resolved.read_text(encoding="utf-8")

    def write_text(self, path: str, content: str) -> None:
        resolved = self._resolve(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")


class SupabaseStorage(StorageBackend):
    """Supabase PostgreSQL-backed storage via REST API.

    Stores all data in a single `jhc_kv_store` table:
      - key TEXT PRIMARY KEY (normalized path)
      - value JSONB
      - updated_at TIMESTAMPTZ DEFAULT now()

    Requires: SUPABASE_URL, SUPABASE_KEY env vars.
    Table must be created via SQL migration (see docs/persistence.md).
    """

    def __init__(self):
        self.url = os.environ.get("SUPABASE_URL", "")
        self.key = os.environ.get("SUPABASE_KEY", "")
        if not self.url or not self.key:
            raise ValueError(
                "SupabaseStorage requires SUPABASE_URL and SUPABASE_KEY env vars"
            )
        self.table_url = f"{self.url}/rest/v1/jhc_kv_store"
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        }

    def _normalize_key(self, path: str) -> str:
        """Convert filesystem path to flat key: 'scheduler/jobs.json'."""
        return str(Path(path)).replace("\\", "/").strip("/")

    def _get(self, key: str) -> dict | None:
        import urllib.request
        url = f"{self.table_url}?key=eq.{key}&select=value"
        req = urllib.request.Request(url, headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                rows = json.loads(resp.read())
                if rows:
                    return rows[0].get("value")
        except Exception:
            pass
        return None

    def _upsert(self, key: str, value: Any) -> None:
        import urllib.request
        payload = json.dumps({"key": key, "value": value}).encode()
        req = urllib.request.Request(
            self.table_url,
            data=payload,
            headers={**self.headers, "Prefer": "resolution=merge-duplicates"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            print(f"[SupabaseStorage] upsert failed for {key}: {e}")

    def read_json(self, path: str) -> dict | list | None:
        return self._get(self._normalize_key(path))

    def write_json(self, path: str, data: dict | list) -> None:
        self._upsert(self._normalize_key(path), data)

    def exists(self, path: str) -> bool:
        return self._get(self._normalize_key(path)) is not None

    def read_text(self, path: str) -> str | None:
        val = self._get(self._normalize_key(path))
        if val is None:
            return None
        if isinstance(val, str):
            return val
        return json.dumps(val, ensure_ascii=False)

    def write_text(self, path: str, content: str) -> None:
        self._upsert(self._normalize_key(path), content)


def get_storage(data_root: Path | str | None = None) -> StorageBackend:
    """Factory: returns configured storage backend.

    JHC_STORAGE_BACKEND=supabase → SupabaseStorage
    Otherwise → LocalFileSystem(data_root or DATA_ROOT env or 'data')
    """
    backend = os.environ.get("JHC_STORAGE_BACKEND", "local").lower()
    if backend == "supabase":
        return SupabaseStorage()
    root = data_root or os.environ.get("JHC_DATA_ROOT", "data")
    return LocalFileSystem(root)