"""Testes E2E — MISSÃO 022.

Valida integração completa de todos os módulos implementados nas missões 014–021:
- ReferenceLab (análise de vídeo de referência)
- SmartClipper (extração de clipes)
- StoryStudio (histórias animadas)
- AudioVisualSync (mixagem e legendas)
- SocialImporter (importação de redes sociais)
- BrowserPublisher (publicação automatizada)
- ThumbnailFactory (geração automática)
- MultiFormatExporter (distribuição multiformato)

Todos os testes usam TestClient com auth middleware ativo.
"""

import json
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Configura API key para testes
os.environ["JHC_API_KEY"] = "test-e2e-key-2026"

from src.api.main import app

client = TestClient(app)
HEADERS = {"X-API-Key": "test-e2e-key-2026"}


class TestAuthMiddlewareE2E:
    """Valida que auth middleware protege todas as rotas novas."""

    def test_health_public(self):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_references_blocked_without_key(self):
        resp = client.get("/api/references/list")
        assert resp.status_code == 401

    def test_clips_blocked_without_key(self):
        resp = client.get("/api/clips/list")
        assert resp.status_code == 401

    def test_stories_blocked_without_key(self):
        resp = client.get("/api/stories/list")
        assert resp.status_code == 401

    def test_audio_blocked_without_key(self):
        resp = client.get("/api/audio/list")
        assert resp.status_code == 401

    def test_import_blocked_without_key(self):
        resp = client.get("/api/import/list")
        assert resp.status_code == 401

    def test_publish_blocked_without_key(self):
        resp = client.get("/api/publish/stats")
        assert resp.status_code == 401

    def test_export_blocked_without_key(self):
        resp = client.get("/api/export/profiles")
        assert resp.status_code == 401


class TestReferenceLabE2E:
    """MISSÃO 014 — Laboratório de Referências."""

    def test_list_references_empty(self):
        resp = client.get("/api/references/list", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_analyze_missing_video(self):
        resp = client.post(
            "/api/references/analyze",
            json={"video_path": "/nonexistent/video.mp4"},
            headers=HEADERS,
        )
        assert resp.status_code == 404

    def test_analyze_missing_path(self):
        resp = client.post(
            "/api/references/analyze",
            json={},
            headers=HEADERS,
        )
        assert resp.status_code == 400

    def test_blueprint_not_found(self):
        resp = client.get("/api/references/blueprint/nonexistent", headers=HEADERS)
        assert resp.status_code == 404


class TestSmartClipperE2E:
    """MISSÃO 015 — Smart Clipper."""

    def test_list_clips_empty(self):
        resp = client.get("/api/clips/list", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_extract_missing_video(self):
        resp = client.post(
            "/api/clips/extract",
            json={"video_path": "/nonexistent/video.mp4"},
            headers=HEADERS,
        )
        assert resp.status_code in (404, 500)

    def test_extract_missing_path(self):
        resp = client.post(
            "/api/clips/extract",
            json={},
            headers=HEADERS,
        )
        assert resp.status_code == 400


class TestStoryStudioE2E:
    """MISSÃO 016 — Story Studio."""

    def test_list_stories_empty(self):
        resp = client.get("/api/stories/list", headers=HEADERS)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_scripts_empty(self):
        resp = client.get("/api/stories/scripts", headers=HEADERS)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_create_story_invalid(self):
        resp = client.post(
            "/api/stories/create",
            json={},
            headers=HEADERS,
        )
        # Deve retornar erro pois não há script válido
        assert resp.status_code == 500


class TestAudioVisualSyncE2E:
    """MISSÃO 017 — Integração Audiovisual."""

    def test_list_mixed_audio(self):
        resp = client.get("/api/audio/list", headers=HEADERS)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_subtitles(self):
        resp = client.get("/api/subtitles/list", headers=HEADERS)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_mix_missing_video(self):
        resp = client.post(
            "/api/audio/mix",
            json={"video_path": "/nonexistent.mp4"},
            headers=HEADERS,
        )
        assert resp.status_code in (404, 500)

    def test_generate_subtitles(self):
        segments = [
            {"start_sec": 0.0, "end_sec": 2.0, "text": "Olá mundo"},
            {"start_sec": 2.0, "end_sec": 4.0, "text": "Segundo segmento"},
        ]
        resp = client.post(
            "/api/subtitles/generate",
            json={"segments": segments, "output_name": "test_e2e_subs", "format": "srt"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["segment_count"] == 2
        assert data["format"] == "srt"
        assert "subtitles" in data["path"].lower() or "test_e2e_subs" in data["path"]

    def test_generate_subtitles_vtt(self):
        segments = [{"start_sec": 0, "end_sec": 1, "text": "Test VTT"}]
        resp = client.post(
            "/api/subtitles/generate",
            json={"segments": segments, "output_name": "test_vtt", "format": "vtt"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["format"] == "vtt"

    def test_generate_subtitles_empty(self):
        resp = client.post(
            "/api/subtitles/generate",
            json={"segments": []},
            headers=HEADERS,
        )
        assert resp.status_code == 400


class TestSocialImporterE2E:
    """MISSÃO 018 — Importador de Redes Sociais."""

    def test_list_imports(self):
        resp = client.get("/api/import/list", headers=HEADERS)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_import_stats(self):
        resp = client.get("/api/import/stats", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_imports" in data
        assert "by_platform" in data

    def test_import_invalid_url(self):
        resp = client.post(
            "/api/import/video",
            json={"url": ""},
            headers=HEADERS,
        )
        assert resp.status_code in (400, 500)

    def test_import_missing_url(self):
        resp = client.post(
            "/api/import/video",
            json={},
            headers=HEADERS,
        )
        assert resp.status_code == 400

    def test_batch_import_empty(self):
        resp = client.post(
            "/api/import/batch",
            json={"urls": []},
            headers=HEADERS,
        )
        assert resp.status_code == 400


class TestBrowserPublisherE2E:
    """MISSÃO 019 — Browser Publisher."""

    def test_publish_stats(self):
        resp = client.get("/api/publish/stats", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_publications" in data
        assert "success_rate" in data

    def test_publish_history(self):
        resp = client.get("/api/publish/history", headers=HEADERS)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_check_session_unknown(self):
        resp = client.get("/api/publish/session/unknown_platform", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is False

    def test_publish_missing_params(self):
        resp = client.post(
            "/api/publish/browser",
            json={},
            headers=HEADERS,
        )
        assert resp.status_code == 400


class TestThumbnailFactoryE2E:
    """MISSÃO 020 — Thumbnail Factory Integrada."""

    def test_auto_generate_missing_video(self):
        resp = client.post(
            "/api/thumbnails/auto-generate",
            json={},
            headers=HEADERS,
        )
        assert resp.status_code == 400

    def test_thumbnail_history(self):
        resp = client.get("/api/thumbnails/history", headers=HEADERS)
        assert resp.status_code == 200


class TestMultiFormatExporterE2E:
    """MISSÃO 021 — Distribuição Multiformato."""

    def test_export_profiles(self):
        resp = client.get("/api/export/profiles", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 8  # Pelo menos 8 perfis definidos
        platforms = {p["platform"] for p in data}
        assert "instagram" in platforms
        assert "youtube" in platforms
        assert "tiktok" in platforms

    def test_export_list(self):
        resp = client.get("/api/export/list", headers=HEADERS)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_export_missing_video(self):
        resp = client.post(
            "/api/export/multiformat",
            json={"video_path": "/nonexistent.mp4"},
            headers=HEADERS,
        )
        assert resp.status_code in (404, 500)

    def test_export_missing_path(self):
        resp = client.post(
            "/api/export/multiformat",
            json={},
            headers=HEADERS,
        )
        assert resp.status_code == 400


class TestFullPipelineIntegration:
    """Testa fluxo completo: health → profiles → export profiles → subtitles."""

    def test_full_read_pipeline(self):
        # 1. Health check
        resp = client.get("/api/health")
        assert resp.status_code == 200
        health = resp.json()
        assert health["status"] == "operational"

        # 2. List profiles (com auth)
        resp = client.get("/api/profiles", headers=HEADERS)
        assert resp.status_code == 200

        # 3. Export profiles
        resp = client.get("/api/export/profiles", headers=HEADERS)
        assert resp.status_code == 200
        profiles = resp.json()
        assert len(profiles) > 0

        # 4. Generate subtitles
        resp = client.post(
            "/api/subtitles/generate",
            json={
                "segments": [
                    {"start_sec": 0, "end_sec": 3, "text": "Pipeline E2E OK"},
                ],
                "output_name": "pipeline_test",
                "format": "srt",
            },
            headers=HEADERS,
        )
        assert resp.status_code == 200

        # 5. Import stats
        resp = client.get("/api/import/stats", headers=HEADERS)
        assert resp.status_code == 200

        # 6. Publish stats
        resp = client.get("/api/publish/stats", headers=HEADERS)
        assert resp.status_code == 200

    def test_all_endpoints_respond(self):
        """Garante que todos os endpoints novos respondem (mesmo que com erro)."""
        endpoints = [
            ("GET", "/api/references/list"),
            ("GET", "/api/clips/list"),
            ("GET", "/api/stories/list"),
            ("GET", "/api/stories/scripts"),
            ("GET", "/api/audio/list"),
            ("GET", "/api/subtitles/list"),
            ("GET", "/api/import/list"),
            ("GET", "/api/import/stats"),
            ("GET", "/api/publish/stats"),
            ("GET", "/api/publish/history"),
            ("GET", "/api/export/list"),
            ("GET", "/api/export/profiles"),
            ("GET", "/api/thumbnails/history"),
        ]
        for method, path in endpoints:
            resp = client.request(method, path, headers=HEADERS)
            assert resp.status_code == 200, f"{method} {path} returned {resp.status_code}"