"""Authentication module for JHC Viral Engine Dashboard.

Implements secure JWT-based session authentication for the web dashboard,
separate from the API key used for programmatic access.

Flow:
1. User logs in with username + password via POST /api/auth/login
2. Server validates credentials against JHC_DASHBOARD_USER / JHC_DASHBOARD_PASS env vars
3. Server returns short-lived JWT (24h) in httpOnly cookie + response body
4. Frontend stores token in memory (NOT localStorage) and sends as Bearer header
5. AuthMiddleware validates JWT on all /api/* routes (except public + auth routes)
6. Logout clears the cookie

Security properties:
- Credentials never stored in frontend code
- JWT signed with HS256 using JHC_JWT_SECRET (falls back to JHC_API_KEY)
- httpOnly cookie prevents XSS token theft
- Token expiry enforced server-side
- No query string auth in production
"""

import os
import time
import hmac
import hashlib
import json
import base64
import secrets
from typing import Optional


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def create_jwt(payload: dict, secret: str, expires_in: int = 86400) -> str:
    """Create a JWT token with HS256 signing."""
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {**payload, "iat": now, "exp": now + expires_in}

    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}"

    signature = hmac.new(
        secret.encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    sig_b64 = _b64url_encode(signature)

    return f"{signing_input}.{sig_b64}"


def verify_jwt(token: str, secret: str) -> Optional[dict]:
    """Verify and decode a JWT token. Returns payload or None."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        header_b64, payload_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}"

        expected_sig = hmac.new(
            secret.encode("utf-8"),
            signing_input.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        actual_sig = _b64url_decode(sig_b64)

        if not hmac.compare_digest(expected_sig, actual_sig):
            return None

        payload = json.loads(_b64url_decode(payload_b64))

        # Check expiry
        exp = payload.get("exp", 0)
        if time.time() > exp:
            return None

        return payload
    except Exception:
        return None


def get_jwt_secret() -> str:
    """Get JWT signing secret from env vars."""
    secret = os.environ.get("JHC_JWT_SECRET", "")
    if not secret:
        secret = os.environ.get("JHC_API_KEY", "")
    if not secret:
        # Generate ephemeral secret for dev (tokens won't survive restart)
        secret = secrets.token_hex(32)
    return secret


def validate_dashboard_credentials(username: str, password: str) -> bool:
    """Validate dashboard login credentials against env vars.

    SECURITY: In production, JHC_DASHBOARD_PASS MUST be explicitly set.
    No fallback to JHC_API_KEY — that would expose the admin API key
    as a web login password, defeating the purpose of separate credentials.
    """
    expected_user = os.environ.get("JHC_DASHBOARD_USER", "admin")
    expected_pass = os.environ.get("JHC_DASHBOARD_PASS", "")

    if not expected_pass:
        # In production, refuse login if no dashboard password is configured
        if os.environ.get("JHC_ENV") == "production":
            return False
        # Dev/local only: allow API key as fallback for convenience
        expected_pass = os.environ.get("JHC_API_KEY", "")

    if not expected_pass:
        return False

    return (
        hmac.compare_digest(username, expected_user)
        and hmac.compare_digest(password, expected_pass)
    )