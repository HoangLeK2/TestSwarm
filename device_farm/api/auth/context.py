"""AuthContext — frozen snapshot of the authenticated caller for one request."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from jose import JWTError, ExpiredSignatureError, jwt

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from auth.secret_versioning import (
    JwtKeyRevokedError,
    all_verify_materials,
    verify_material_for_kid,
)
from core.security import jwt_algorithm


@dataclass(frozen=True)
class AuthContext:
    """Authenticated caller as derived from a JWT.

    Routes should treat this as the sole source of caller identity — never
    re-parse Authorization headers, never trust body/query user fields.
    """

    user_id: str
    token_type: str
    raw_token: str
    session_id: str | None = None
    org_id: str | None = None
    roles: tuple[str, ...] = ()

    @property
    def is_access(self) -> bool:
        return self.token_type != "refresh"


class AuthError(Exception):
    """Raised when a token is absent, malformed, expired, or not an access token."""

    code: str = "INVALID_TOKEN"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        self.code = code or self.code
        super().__init__(message)


class TokenRevokedKeyError(AuthError):
    code = "TOKEN_EXPIRED_KEY_REVOKED"


class TokenExpiredError(AuthError):
    code = "TOKEN_EXPIRED"


def _auth_context_from_mcp_record(raw_token: str, record) -> AuthContext:
    if record is None:
        raise AuthError("invalid mcp token")
    if not record.owner_user_id:
        raise AuthError("mcp token missing owner")
    return AuthContext(
        user_id=record.owner_user_id,
        token_type="mcp",
        raw_token=raw_token,
        org_id=record.org_id,
        roles=(f"mcp:{record.scope_type}",),
    )


async def decode_access_token_async(
    raw_token: str,
    *,
    db: "AsyncSession | None" = None,
) -> AuthContext:
    """Async decode path for FastAPI dependencies inside a running event loop."""
    if not raw_token:
        raise AuthError("missing token")
    if raw_token.startswith("dfmcp_"):
        try:
            from mcp.token_store import lookup_token_async
        except Exception as exc:
            raise AuthError("mcp token store unavailable") from exc
        record = await lookup_token_async(raw_token, db=db)
        return _auth_context_from_mcp_record(raw_token, record)
    return decode_access_token(raw_token)


def decode_access_token(raw_token: str) -> AuthContext:
    """Decode an access JWT into an AuthContext, raising AuthError on failure."""
    if not raw_token:
        raise AuthError("missing token")
    if raw_token.startswith("dfmcp_"):
        try:
            from mcp.token_store import lookup_token
        except Exception as exc:
            raise AuthError("mcp token store unavailable") from exc
        record = lookup_token(raw_token)
        return _auth_context_from_mcp_record(raw_token, record)
    header = jwt.get_unverified_header(raw_token)
    kid = header.get("kid")
    candidates = []
    if kid:
        try:
            candidates = [verify_material_for_kid(str(kid))]
        except JwtKeyRevokedError as exc:
            raise TokenRevokedKeyError(str(exc)) from exc
    else:
        candidates = all_verify_materials()

    payload = None
    last_exc: Exception | None = None
    for material in candidates:
        try:
            payload = jwt.decode(raw_token, material.secret, algorithms=[jwt_algorithm()])
            break
        except ExpiredSignatureError as exc:
            raise TokenExpiredError(f"invalid token: {exc}") from exc
        except JWTError as exc:
            last_exc = exc
            continue
    if payload is None:
        raise AuthError(f"invalid token: {last_exc}") from last_exc

    user_id = str(payload.get("sub") or "").strip()
    token_type = str(payload.get("type") or "access").strip() or "access"
    session_id = str(payload.get("sid") or "").strip() or None
    org_id = str(payload.get("org_id") or "").strip() or None
    raw_roles = payload.get("roles") or []
    roles = tuple(str(r).strip() for r in raw_roles if str(r).strip())
    if not user_id:
        raise AuthError("token missing sub")
    if token_type == "refresh":
        raise AuthError("refresh token not allowed here")

    return AuthContext(
        user_id=user_id,
        token_type=token_type,
        raw_token=raw_token,
        session_id=session_id,
        org_id=org_id,
        roles=roles,
    )


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
