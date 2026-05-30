"""AuthContext — frozen snapshot of the authenticated caller for one request."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from jose import JWTError, ExpiredSignatureError, jwt

from core.security import jwt_algorithm, jwt_secret_key


@dataclass(frozen=True)
class AuthContext:
    """Authenticated caller as derived from a JWT.

    Routes should treat this as the sole source of caller identity — never
    re-parse Authorization headers, never trust body/query user fields.
    """

    user_id: str
    token_type: str
    raw_token: str

    @property
    def is_access(self) -> bool:
        return self.token_type != "refresh"


class AuthError(Exception):
    """Raised when a token is absent, malformed, expired, or not an access token."""

    code: str = "INVALID_TOKEN"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        self.code = code or self.code
        super().__init__(message)


class TokenExpiredError(AuthError):
    code = "TOKEN_EXPIRED"


def decode_access_token(raw_token: str) -> AuthContext:
    """Decode an access JWT into an AuthContext, raising AuthError on failure."""
    if not raw_token:
        raise AuthError("missing token")
    try:
        payload = jwt.decode(raw_token, jwt_secret_key(), algorithms=[jwt_algorithm()])
    except ExpiredSignatureError as exc:
        raise TokenExpiredError(f"invalid token: {exc}") from exc
    except JWTError as exc:
        raise AuthError(f"invalid token: {exc}") from exc

    user_id = str(payload.get("sub") or "").strip()
    token_type = str(payload.get("type") or "access").strip() or "access"
    if not user_id:
        raise AuthError("token missing sub")
    if token_type == "refresh":
        raise AuthError("refresh token not allowed here")

    return AuthContext(user_id=user_id, token_type=token_type, raw_token=raw_token)


def try_decode_access_token(raw_token: Optional[str]) -> Optional[AuthContext]:
    """Lenient variant — returns None for any failure, used by anonymous-capable paths (WS)."""
    if not raw_token:
        return None
    try:
        return decode_access_token(raw_token)
    except AuthError:
        return None


def extract_bearer(header_value: Optional[str]) -> Optional[str]:
    """Return the raw token from an 'Authorization: Bearer <token>' header, else None.

    Header-only is intentional: query-string tokens leak via access logs,
    browser history, referrer, and proxy caches. The only browser-mandated
    exception is WebSocket — handled by its own helper, not this one.
    """
    if not header_value:
        return None
    h = header_value.strip()
    if not h.lower().startswith("bearer "):
        return None
    token = h[7:].strip()
    return token or None
