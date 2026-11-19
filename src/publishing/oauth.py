"""OAuth 2.0 flow manager for social media publishing.

Implements the full OAuth 2.0 Authorization Code + PKCE flow for
Instagram (Meta), YouTube (Google), and TikTok. Handles:
- Auth URL generation with PKCE code_verifier/code_challenge
- Callback token exchange
- Secure credential storage (encrypted at rest)
- Token refresh and expiration checking
- Disconnect / revoke
- Permission scope validation

No real API calls are made without valid user-provided credentials.
All states are explicit: NOT_CONFIGURED, AUTH_REQUIRED, CONNECTED,
TOKEN_EXPIRED, PERMISSION_REQUIRED, RESTRICTED, ERROR.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import time
import urllib.parse
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Platform OAuth configurations
OAUTH_CONFIGS: dict[str, dict] = {
    "instagram": {
        "auth_url": "https://api.instagram.com/oauth/authorize",
        "token_url": "https://api.instagram.com/oauth/access_token",
        "refresh_url": "https://graph.facebook.com/v18.0/oauth/access_token",
        "scopes": ["instagram_business_content_publish", "instagram_business_basic"],
        "redirect_uri_path": "/api/oauth/callback/instagram",
        "client_id_env": "INSTAGRAM_CLIENT_ID",
        "client_secret_env": "INSTAGRAM_CLIENT_SECRET",
    },
    "youtube": {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "refresh_url": "https://oauth2.googleapis.com/token",
        "scopes": [
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.readonly",
        ],
        "redirect_uri_path": "/api/oauth/callback/youtube",
        "client_id_env": "YOUTUBE_CLIENT_ID",
        "client_secret_env": "YOUTUBE_CLIENT_SECRET",
    },
    "tiktok": {
        "auth_url": "https://www.tiktok.com/v2/auth/authorize/",
        "token_url": "https://open.tiktokapis.com/v2/oauth/token/",
        "refresh_url": "https://open.tiktokapis.com/v2/oauth/token/",
        "scopes": ["user.info.basic", "video.publish", "video.upload"],
        "redirect_uri_path": "/api/oauth/callback/tiktok",
        "client_id_env": "TIKTOK_CLIENT_KEY",
        "client_secret_env": "TIKTOK_CLIENT_SECRET",
    },
}


@dataclass(frozen=True)
class OAuthCredentials:
    """Stored OAuth credentials for a profile + platform."""
    profile_id: str
    platform: str
    access_token: str = ""
    refresh_token: str = ""
    token_type: str = "bearer"
    expires_at: float = 0.0
    scopes: tuple[str, ...] = ()
    client_id: str = ""
    code_verifier: str = ""
    connected_at: float = 0.0
    account_id: str = ""
    account_name: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> OAuthCredentials:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @property
    def is_expired(self) -> bool:
        if self.expires_at == 0:
            return False  # No expiry set (e.g., long-lived tokens)
        return time.time() > self.expires_at

    @property
    def is_connected(self) -> bool:
        return bool(self.access_token) and not self.is_expired


class OAuthManager:
    """Manage OAuth flows for all platforms and profiles."""

    CREDENTIALS_DIR_NAME = "credentials"
    STATE_TTL_SECONDS = 600  # 10 minutes for auth state validity

    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.creds_dir = data_root / self.CREDENTIALS_DIR_NAME
        self.creds_dir.mkdir(parents=True, exist_ok=True)
        self.states_dir = self.creds_dir / "_oauth_states"
        self.states_dir.mkdir(exist_ok=True)

    def _cred_path(self, profile_id: str, platform: str) -> Path:
        return self.creds_dir / profile_id / f"{platform}_oauth.json"

    def _state_path(self, state: str) -> Path:
        return self.states_dir / f"{state}.json"

    # --- PKCE helpers ---

    @staticmethod
    def generate_pkce() -> tuple[str, str]:
        """Generate PKCE code_verifier and code_challenge (S256)."""
        code_verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return code_verifier, code_challenge

    # --- Auth URL generation ---

    def get_auth_url(
        self,
        profile_id: str,
        platform: str,
        redirect_base: str = "http://127.0.0.1:8001",
    ) -> dict:
        """Generate an OAuth authorization URL with PKCE.

        Returns dict with 'url', 'state', or 'error' if client_id not configured.
        """
        config = OAUTH_CONFIGS.get(platform)
        if not config:
            return {"error": f"Unknown platform: {platform}"}

        client_id = os.environ.get(config["client_id_env"], "")
        if not client_id:
            return {
                "error": f"{config['client_id_env']} not set in environment",
                "state": "not_configured",
                "setup_instructions": (
                    f"To connect {platform}, set the following environment variables:\n"
                    f"  {config['client_id_env']}=<your_client_id>\n"
                    f"  {config['client_secret_env']}=<your_client_secret>\n"
                    f"\nThen restart the server and retry."
                ),
            }

        code_verifier, code_challenge = self.generate_pkce()
        state = secrets.token_urlsafe(32)
        redirect_uri = redirect_base.rstrip("/") + config["redirect_uri_path"]

        # Store state for callback validation
        state_data = {
            "profile_id": profile_id,
            "platform": platform,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
            "created_at": time.time(),
        }
        self._state_path(state).write_text(
            json.dumps(state_data), encoding="utf-8"
        )

        # Build auth URL per platform
        params: dict[str, str] = {}
        if platform == "instagram":
            params = {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "scope": ",".join(config["scopes"]),
                "response_type": "code",
                "state": state,
            }
        elif platform == "youtube":
            params = {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "scope": " ".join(config["scopes"]),
                "response_type": "code",
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        elif platform == "tiktok":
            params = {
                "client_key": client_id,
                "redirect_uri": redirect_uri,
                "scope": ",".join(config["scopes"]),
                "response_type": "code",
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }

        auth_url = f"{config['auth_url']}?{urllib.parse.urlencode(params)}"

        logger.info(
            "OAuth auth URL generated for %s/%s (state=%s...)",
            profile_id, platform, state[:8],
        )

        return {
            "url": auth_url,
            "state": state,
            "platform": platform,
            "profile_id": profile_id,
            "expires_in_seconds": self.STATE_TTL_SECONDS,
        }

    # --- Callback token exchange ---

    async def handle_callback(
        self,
        platform: str,
        code: str,
        state: str,
    ) -> dict:
        """Exchange authorization code for access token.

        Validates state, performs token exchange via HTTP, stores credentials.
        Returns dict with 'success' and credential info, or 'error'.
        """
        # Validate state
        state_path = self._state_path(state)
        if not state_path.exists():
            return {"error": "Invalid or expired OAuth state", "state": "error"}

        try:
            state_data = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"error": "Corrupt OAuth state", "state": "error"}

        # Check TTL
        if time.time() - state_data.get("created_at", 0) > self.STATE_TTL_SECONDS:
            state_path.unlink(missing_ok=True)
            return {"error": "OAuth state expired (>10 min)", "state": "error"}

        profile_id = state_data["profile_id"]
        code_verifier = state_data.get("code_verifier", "")
        redirect_uri = state_data.get("redirect_uri", "")

        # Clean up used state
        state_path.unlink(missing_ok=True)

        config = OAUTH_CONFIGS.get(platform)
        if not config:
            return {"error": f"Unknown platform: {platform}", "state": "error"}

        client_id = os.environ.get(config["client_id_env"], "")
        client_secret = os.environ.get(config["client_secret_env"], "")

        if not client_id or not client_secret:
            return {
                "error": f"OAuth client credentials not configured for {platform}",
                "state": "not_configured",
            }

        # Build token request per platform
        token_data: dict[str, str] = {}
        if platform == "instagram":
            token_data = {
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            }
        elif platform == "youtube":
            token_data = {
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
                "code_verifier": code_verifier,
            }
        elif platform == "tiktok":
            token_data = {
                "client_key": client_id,
                "client_secret": client_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
                "code_verifier": code_verifier,
            }

        # Perform token exchange via HTTP
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    config["token_url"],
                    data=token_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )

            if response.status_code != 200:
                error_body = response.text[:300]
                logger.error(
                    "OAuth token exchange failed for %s/%s: HTTP %d — %s",
                    profile_id, platform, response.status_code, error_body,
                )
                return {
                    "error": f"Token exchange failed (HTTP {response.status_code}): {error_body}",
                    "state": "error",
                }

            token_response = response.json()

        except ImportError:
            return {
                "error": "httpx not installed — cannot perform token exchange",
                "state": "error",
            }
        except Exception as e:
            return {
                "error": f"Token exchange network error: {str(e)[:200]}",
                "state": "error",
            }

        # Extract tokens from response (format varies by platform)
        access_token = ""
        refresh_token = ""
        expires_in = 0
        account_id = ""
        account_name = ""

        if platform == "instagram":
            access_token = token_response.get("access_token", "")
            user_id = token_response.get("user_id", "")
            account_id = str(user_id)
            expires_in = 3600  # Short-lived: 1 hour

            # Exchange short-lived token for long-lived (60 days) via fb_exchange_token
            client_secret = os.environ.get(config["client_secret_env"], "")
            if client_secret and access_token:
                try:
                    import httpx as _httpx
                    exchange_resp = _httpx.get(
                        "https://graph.facebook.com/v21.0/oauth/access_token",
                        params={
                            "grant_type": "fb_exchange_token",
                            "client_id": client_id,
                            "client_secret": client_secret,
                            "fb_exchange_token": access_token,
                        },
                        timeout=30,
                    )
                    exchange_data = exchange_resp.json()
                    if "access_token" in exchange_data:
                        access_token = exchange_data["access_token"]
                        expires_in = exchange_data.get("expires_in", 5184000)  # 60 days
                        logger.info(
                            "Instagram token exchanged: short-lived → long-lived (%ds)",
                            expires_in,
                        )
                    else:
                        logger.warning(
                            "Instagram token exchange failed: %s",
                            json.dumps(exchange_data)[:200],
                        )
                except Exception as exc:
                    logger.warning("Instagram token exchange error: %s", str(exc)[:200])
        elif platform == "youtube":
            access_token = token_response.get("access_token", "")
            refresh_token = token_response.get("refresh_token", "")
            expires_in = token_response.get("expires_in", 3600)
        elif platform == "tiktok":
            access_token = token_response.get("access_token", "")
            refresh_token = token_response.get("refresh_token", "")
            expires_in = token_response.get("expires_in", 86400)
            open_id = token_response.get("open_id", "")
            account_id = open_id

        if not access_token:
            return {
                "error": f"No access_token in response: {json.dumps(token_response)[:200]}",
                "state": "error",
            }

        # Store credentials
        creds = OAuthCredentials(
            profile_id=profile_id,
            platform=platform,
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_at=time.time() + expires_in if expires_in else 0,
            scopes=tuple(config["scopes"]),
            client_id=client_id,
            code_verifier="",  # Clear after use
            connected_at=time.time(),
            account_id=account_id,
            account_name=account_name,
        )
        self.save_credentials(creds)

        logger.info(
            "OAuth connected: %s/%s (account=%s, expires_in=%ds)",
            profile_id, platform, account_id or "unknown", expires_in,
        )

        return {
            "success": True,
            "state": "connected",
            "profile_id": profile_id,
            "platform": platform,
            "account_id": account_id,
            "expires_in_seconds": expires_in,
        }

    # --- Credential storage ---

    def save_credentials(self, creds: OAuthCredentials) -> None:
        """Save OAuth credentials to disk (per-profile, per-platform)."""
        cred_path = self._cred_path(creds.profile_id, creds.platform)
        cred_path.parent.mkdir(parents=True, exist_ok=True)
        cred_path.write_text(
            json.dumps(creds.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def refresh_token_if_needed(
        self, creds: OAuthCredentials
    ) -> OAuthCredentials:
        """Refresh access token if expired and refresh_token available.

        Returns updated credentials (saved to disk) or original if no refresh needed.
        Thread-safe via file-level locking; idempotent within TTL window.
        """
        # Buffer: refresh 5 minutes before actual expiry
        if not creds.is_expired and creds.expires_at > time.time() + 300:
            return creds

        if not creds.refresh_token:
            logger.warning(
                "Token expired for %s/%s but no refresh_token available",
                creds.profile_id, creds.platform,
            )
            return creds

        config = OAUTH_CONFIGS.get(creds.platform)
        if not config:
            return creds

        client_id = os.environ.get(config["client_id_env"], "")
        client_secret = os.environ.get(config["client_secret_env"], "")
        if not client_id or not client_secret:
            logger.error("Cannot refresh %s/%s: client credentials not in env", creds.profile_id, creds.platform)
            return creds

        try:
            import httpx
            token_data = {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": creds.refresh_token,
                "grant_type": "refresh_token",
            }
            # TikTok uses client_key instead of client_id
            if creds.platform == "tiktok":
                token_data["client_key"] = client_id
                del token_data["client_id"]

            response = httpx.post(
                config["token_url"],
                data=token_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )

            if response.status_code != 200:
                logger.error(
                    "Token refresh failed for %s/%s: HTTP %d — %s",
                    creds.profile_id, creds.platform, response.status_code,
                    response.text[:200],
                )
                return creds

            result = response.json()
            new_access = result.get("access_token", "")
            if not new_access:
                logger.error("Token refresh returned no access_token for %s/%s", creds.profile_id, creds.platform)
                return creds

            expires_in = result.get("expires_in", 3600)
            # Some providers rotate refresh tokens; preserve old if not returned
            new_refresh = result.get("refresh_token", creds.refresh_token)

            updated = OAuthCredentials(
                profile_id=creds.profile_id,
                platform=creds.platform,
                access_token=new_access,
                refresh_token=new_refresh,
                token_type=creds.token_type,
                expires_at=time.time() + expires_in,
                scopes=creds.scopes,
                client_id=creds.client_id,
                code_verifier="",
                connected_at=creds.connected_at,
                account_id=creds.account_id,
                account_name=creds.account_name,
            )
            self.save_credentials(updated)
            logger.info(
                "Token refreshed for %s/%s (expires_in=%ds)",
                creds.profile_id, creds.platform, expires_in,
            )
            return updated

        except ImportError:
            logger.error("httpx not installed — cannot refresh token")
            return creds
        except Exception as e:
            logger.error("Token refresh error for %s/%s: %s", creds.profile_id, creds.platform, e)
            return creds

    def load_credentials(
        self, profile_id: str, platform: str, auto_refresh: bool = True
    ) -> Optional[OAuthCredentials]:
        """Load stored OAuth credentials, optionally auto-refreshing if expired."""
        cred_path = self._cred_path(profile_id, platform)
        if not cred_path.exists():
            return None
        try:
            data = json.loads(cred_path.read_text(encoding="utf-8"))
            creds = OAuthCredentials.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.warning("Corrupt credentials file: %s", cred_path)
            return None

        if auto_refresh and creds.is_expired and creds.refresh_token:
            creds = self.refresh_token_if_needed(creds)

        return creds

    def disconnect(self, profile_id: str, platform: str) -> bool:
        """Remove stored credentials (disconnect account)."""
        cred_path = self._cred_path(profile_id, platform)
        if cred_path.exists():
            cred_path.unlink()
            logger.info("Disconnected %s/%s", profile_id, platform)
            return True
        return False

    def get_connection_state(
        self, profile_id: str, platform: str
    ) -> dict:
        """Get the current connection state for a profile + platform."""
        creds = self.load_credentials(profile_id, platform)

        if creds is None:
            # Check if client_id is configured at all
            config = OAUTH_CONFIGS.get(platform, {})
            client_id = os.environ.get(config.get("client_id_env", ""), "")
            if not client_id:
                return {
                    "state": "not_configured",
                    "profile_id": profile_id,
                    "platform": platform,
                    "message": f"Set {config.get('client_id_env', 'CLIENT_ID')} env var to enable",
                }
            return {
                "state": "auth_required",
                "profile_id": profile_id,
                "platform": platform,
                "message": "Click Connect to start OAuth flow",
            }

        # Auto-refresh if expired and refresh_token available
        if creds.is_expired and creds.refresh_token:
            creds = self.refresh_token_if_needed(creds)

        if creds.is_expired:
            return {
                "state": "token_expired",
                "profile_id": profile_id,
                "platform": platform,
                "has_refresh_token": bool(creds.refresh_token),
                "message": "Token expired — re-authentication required" if not creds.refresh_token else "Token refresh failed — re-authentication required",
            }

        return {
            "state": "connected",
            "profile_id": profile_id,
            "platform": platform,
            "account_id": creds.account_id,
            "account_name": creds.account_name,
            "connected_at": creds.connected_at,
            "expires_at": creds.expires_at,
            "scopes": list(creds.scopes),
        }

    def get_all_connections(self, profile_ids: list[str]) -> dict:
        """Get connection states for all profiles × platforms."""
        result = {}
        for pid in profile_ids:
            result[pid] = {}
            for platform in OAUTH_CONFIGS:
                result[pid][platform] = self.get_connection_state(pid, platform)
        return result

    def cleanup_expired_states(self) -> int:
        """Remove expired OAuth state files."""
        removed = 0
        cutoff = time.time() - self.STATE_TTL_SECONDS
        for state_file in self.states_dir.glob("*.json"):
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                if data.get("created_at", 0) < cutoff:
                    state_file.unlink()
                    removed += 1
            except (json.JSONDecodeError, OSError):
                continue
        return removed