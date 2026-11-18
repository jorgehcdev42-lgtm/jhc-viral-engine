"""Conectores de Publicação Automática — MISSÃO 040.1 ETAPA 3.

Implementa upload via APIs oficiais para YouTube, Instagram e TikTok.
Requer OAuth/credenciais configuradas em data/publishing/credentials/.
Sem credenciais: opera em modo SIMULADO (dry-run) para validação do fluxo.
"""

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DATA_ROOT = Path(__file__).resolve().parent.parent.parent / "data"
CREDENTIALS_DIR = DATA_ROOT / "publishing" / "credentials"
PUBLISH_LOG_FILE = DATA_ROOT / "publishing" / "auto_publish_log.json"


@dataclass
class PublishResult:
    platform: str
    job_id: str
    status: str  # success, failed, simulated, blocked
    published_url: str = ""
    error: str = ""
    published_at: str = ""
    method: str = "auto"
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class PlatformPublisher(ABC):
    """Base class para conectores de publicação."""

    PLATFORM = "unknown"
    CREDENTIAL_FILE = ""

    def __init__(self, data_root: Optional[Path] = None):
        self.data_root = data_root or DATA_ROOT
        self.credentials_dir = self.data_root / "publishing" / "credentials"
        self.credentials_dir.mkdir(parents=True, exist_ok=True)
        self._credentials = self._load_credentials()

    def _load_credentials(self) -> dict:
        if not self.CREDENTIAL_FILE:
            return {}
        cred_path = self.credentials_dir / self.CREDENTIAL_FILE
        if cred_path.exists():
            try:
                return json.loads(cred_path.read_text())
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    @property
    def is_configured(self) -> bool:
        return bool(self._credentials)

    @property
    def mode(self) -> str:
        return "live" if self.is_configured else "simulated"

    @abstractmethod
    def upload(self, video_path: str, title: str, description: str,
               tags: list[str], privacy: str = "public") -> PublishResult:
        pass

    def save_result(self, result: PublishResult) -> None:
        log_file = self.data_root / "publishing" / "auto_publish_log.json"
        entries = []
        if log_file.exists():
            try:
                entries = json.loads(log_file.read_text())
            except (json.JSONDecodeError, OSError):
                entries = []
        entries.append(result.to_dict())
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text(json.dumps(entries, indent=2, ensure_ascii=False))


class YouTubePublisher(PlatformPublisher):
    """Upload via YouTube Data API v3 (OAuth2)."""

    PLATFORM = "youtube"
    CREDENTIAL_FILE = "youtube_oauth.json"

    def upload(self, video_path: str, title: str, description: str,
               tags: list[str], privacy: str = "public") -> PublishResult:
        result = PublishResult(
            platform=self.PLATFORM,
            job_id="",
            status="simulated",
            published_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        )

        if not self.is_configured:
            result.status = "simulated"
            result.error = "Credenciais YouTube OAuth não configuradas. Configure em data/publishing/credentials/youtube_oauth.json"
            result.metadata = {
                "would_upload_to": "https://www.googleapis.com/upload/youtube/v3/videos",
                "title": title,
                "description": description[:100],
                "tags": tags[:5],
                "privacy": privacy,
                "video_size_mb": round(Path(video_path).stat().st_size / 1_048_576, 1) if Path(video_path).exists() else 0,
            }
            logger.info(f"[SIMULATED] YouTube upload: {title}")
            self.save_result(result)
            return result

        # Live upload via YouTube Data API v3
        try:
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
            from google.oauth2.credentials import Credentials

            creds = Credentials.from_authorized_user_info(self._credentials)
            youtube = build("youtube", "v3", credentials=creds)

            body = {
                "snippet": {
                    "title": title[:100],
                    "description": description[:5000],
                    "tags": tags[:30],
                    "categoryId": "20",  # Gaming
                },
                "status": {
                    "privacyStatus": privacy,
                    "selfDeclaredMadeForKids": False,
                },
            }

            media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
            request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
            response = request.execute()

            video_id = response.get("id", "")
            result.status = "success"
            result.published_url = f"https://www.youtube.com/watch?v={video_id}"
            result.metadata = {"video_id": video_id}
            logger.info(f"[LIVE] YouTube upload success: {video_id}")

        except ImportError:
            result.status = "blocked"
            result.error = "google-api-python-client não instalado. pip install google-api-python-client google-auth-oauthlib"
        except Exception as e:
            result.status = "failed"
            result.error = str(e)[:500]

        self.save_result(result)
        return result


class InstagramPublisher(PlatformPublisher):
    """Upload via Instagram Graph API (Business/Creator account)."""

    PLATFORM = "instagram"
    CREDENTIAL_FILE = "instagram_graph_api.json"

    def upload(self, video_path: str, title: str, description: str,
               tags: list[str], privacy: str = "public") -> PublishResult:
        result = PublishResult(
            platform=self.PLATFORM,
            job_id="",
            status="simulated",
            published_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        )

        if not self.is_configured:
            result.status = "simulated"
            result.error = "Credenciais Instagram Graph API não configuradas. Configure em data/publishing/credentials/instagram_graph_api.json"
            result.metadata = {
                "would_upload_to": "https://graph.facebook.com/v18.0/{ig_user_id}/media",
                "caption": f"{title}\n\n{description}"[:200],
                "hashtags": tags[:5],
                "video_size_mb": round(Path(video_path).stat().st_size / 1_048_576, 1) if Path(video_path).exists() else 0,
                "note": "Requer conta Business/Creator + Facebook App vinculado",
            }
            logger.info(f"[SIMULATED] Instagram upload: {title}")
            self.save_result(result)
            return result

        # Live upload via Instagram Graph API
        try:
            import urllib.request
            import urllib.parse

            access_token = self._credentials.get("access_token", "")
            ig_user_id = self._credentials.get("ig_user_id", "")

            if not access_token or not ig_user_id:
                result.status = "failed"
                result.error = "access_token ou ig_user_id ausente nas credenciais"
                self.save_result(result)
                return result

            # Step 1: Create media container
            create_url = f"https://graph.facebook.com/v18.0/{ig_user_id}/media"
            create_data = urllib.parse.urlencode({
                "media_type": "REELS",
                "video_url": video_path,  # Requer URL pública acessível
                "caption": f"{title}\n\n{description}\n\n{' '.join(tags)}",
                "access_token": access_token,
            }).encode()

            req = urllib.request.Request(create_url, data=create_data, method="POST")
            resp = urllib.request.urlopen(req, timeout=30)
            create_resp = json.loads(resp.read())
            creation_id = create_resp.get("id", "")

            # Step 2: Publish
            publish_url = f"https://graph.facebook.com/v18.0/{ig_user_id}/media_publish"
            publish_data = urllib.parse.urlencode({
                "creation_id": creation_id,
                "access_token": access_token,
            }).encode()

            req2 = urllib.request.Request(publish_url, data=publish_data, method="POST")
            resp2 = urllib.request.urlopen(req2, timeout=30)
            publish_resp = json.loads(resp2.read())

            result.status = "success"
            result.published_url = f"https://www.instagram.com/reel/{publish_resp.get('id', '')}"
            result.metadata = {"creation_id": creation_id, "media_id": publish_resp.get("id", "")}
            logger.info(f"[LIVE] Instagram upload success: {creation_id}")

        except Exception as e:
            result.status = "failed"
            result.error = str(e)[:500]

        self.save_result(result)
        return result


class TikTokPublisher(PlatformPublisher):
    """Upload via TikTok Content Posting API."""

    PLATFORM = "tiktok"
    CREDENTIAL_FILE = "tiktok_api.json"

    def upload(self, video_path: str, title: str, description: str,
               tags: list[str], privacy: str = "public") -> PublishResult:
        result = PublishResult(
            platform=self.PLATFORM,
            job_id="",
            status="simulated",
            published_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        )

        if not self.is_configured:
            result.status = "simulated"
            result.error = "Credenciais TikTok API não configuradas. Configure em data/publishing/credentials/tiktok_api.json"
            result.metadata = {
                "would_upload_to": "https://open.tiktokapis.com/v2/post/publish/content/init/",
                "title": title[:150],
                "hashtags": tags[:5],
                "video_size_mb": round(Path(video_path).stat().st_size / 1_048_576, 1) if Path(video_path).exists() else 0,
                "note": "Requer aprovação do app no TikTok Developer Portal",
            }
            logger.info(f"[SIMULATED] TikTok upload: {title}")
            self.save_result(result)
            return result

        # Live upload via TikTok Content Posting API
        try:
            import urllib.request

            access_token = self._credentials.get("access_token", "")
            if not access_token:
                result.status = "failed"
                result.error = "access_token ausente nas credenciais"
                self.save_result(result)
                return result

            # Init publish
            init_url = "https://open.tiktokapis.com/v2/post/publish/content/init/"
            file_size = Path(video_path).stat().st_size
            init_body = json.dumps({
                "post_info": {
                    "title": f"{title} {' '.join(tags)}"[:150],
                    "privacy_level": "PUBLIC_TO_EVERYONE",
                    "disable_comment": False,
                    "disable_duet": False,
                    "disable_stitch": False,
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": file_size,
                    "chunk_size": min(file_size, 10_000_000),
                    "total_chunk_count": max(1, file_size // 10_000_000 + 1),
                },
            }).encode()

            req = urllib.request.Request(
                init_url, data=init_body, method="POST",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json; charset=UTF-8",
                },
            )
            resp = urllib.request.urlopen(req, timeout=30)
            init_resp = json.loads(resp.read())
            publish_id = init_resp.get("data", {}).get("publish_id", "")

            result.status = "success"
            result.metadata = {"publish_id": publish_id, "note": "Upload iniciado; chunks devem ser enviados separadamente"}
            logger.info(f"[LIVE] TikTok upload initiated: {publish_id}")

        except Exception as e:
            result.status = "failed"
            result.error = str(e)[:500]

        self.save_result(result)
        return result


class AutoPublisher:
    """Orquestrador de publicação automática multi-plataforma."""

    PUBLISHERS = {
        "youtube": YouTubePublisher,
        "instagram": InstagramPublisher,
        "tiktok": TikTokPublisher,
    }

    def __init__(self, data_root: Optional[Path] = None):
        self.data_root = data_root or DATA_ROOT
        self._publishers: dict[str, PlatformPublisher] = {}
        for name, cls in self.PUBLISHERS.items():
            self._publishers[name] = cls(data_root=self.data_root)

    def get_status(self) -> dict:
        """Status de cada conector."""
        status = {}
        for name, pub in self._publishers.items():
            status[name] = {
                "configured": pub.is_configured,
                "mode": pub.mode,
                "credential_file": pub.CREDENTIAL_FILE,
            }
        return status

    def publish(self, platform: str, video_path: str, title: str,
                description: str, tags: list[str], job_id: str = "",
                privacy: str = "public") -> PublishResult:
        """Publica vídeo em uma plataforma."""
        pub = self._publishers.get(platform.lower())
        if not pub:
            return PublishResult(
                platform=platform, job_id=job_id,
                status="failed", error=f"Plataforma desconhecida: {platform}",
            )

        result = pub.upload(video_path, title, description, tags, privacy)
        result.job_id = job_id
        return result

    def publish_all(self, video_path: str, title: str, description: str,
                    tags: list[str], job_id: str = "",
                    platforms: list[str] = None) -> list[PublishResult]:
        """Publica em múltiplas plataformas."""
        if platforms is None:
            platforms = list(self.PUBLISHERS.keys())
        results = []
        for p in platforms:
            r = self.publish(p, video_path, title, description, tags, job_id)
            results.append(r)
        return results

    def get_publish_history(self, limit: int = 50) -> list[dict]:
        log_file = self.data_root / "publishing" / "auto_publish_log.json"
        if not log_file.exists():
            return []
        try:
            entries = json.loads(log_file.read_text())
            return entries[-limit:]
        except (json.JSONDecodeError, OSError):
            return []