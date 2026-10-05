"""JWT access token issue/decode helpers (DF-T-01-002)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from jose import JWTError, ExpiredSignatureError, jwt

from core.env import access_expire_hours
from core.security import jwt_algorithm
from auth.secret_versioning import active_kid, signing_material


class JwtIssueError(Exception):
    pass


def access_ttl_seconds() -> int:
    return int(timedelta(hours=access_expire_hours()).total_seconds())


def issue_access_token(
    *,
    user_id: str,
    org_id: str | None,
    roles: list[str],
    jti: str | None = None,
    session_id: str | None = None,
) -> tuple[str, int, str]:
    """Return (token, expires_in_seconds, jti)."""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(hours=access_expire_hours())
    token_jti = jti or str(uuid4())
    payload = {
        "sub": user_id,
        "org_id": org_id,
        "roles": roles,
        "jti": token_jti,
        "type": "access",
        "iat": now,
        "exp": expire,
    }
    if session_id:
        payload["sid"] = session_id
    kid, secret = signing_material()
    token = jwt.encode(
        payload,
        secret,
        algorithm=jwt_algorithm(),
        headers={"kid": kid},
    )
    return token, access_ttl_seconds(), token_jti


def decode_access_payload(raw_token: str) -> dict:
    from auth.secret_versioning import (
        JwtKeyRevokedError,
        all_verify_materials,
        verify_material_for_kid,
    )
    from jose import jwt as jose_jwt

    header = jose_jwt.get_unverified_header(raw_token)
    kid = header.get("kid")
    candidates = []
    if kid:
        try:
            candidates = [verify_material_for_kid(str(kid))]
        except JwtKeyRevokedError as exc:
            raise JwtIssueError("TOKEN_EXPIRED_KEY_REVOKED") from exc
    else:
        candidates = all_verify_materials()

    last_exc: Exception | None = None
    for material in candidates:
        try:
            return jose_jwt.decode(raw_token, material.secret, algorithms=[jwt_algorithm()])
        except ExpiredSignatureError as exc:
            raise JwtIssueError("TOKEN_EXPIRED") from exc
        except JWTError as exc:
            last_exc = exc
            continue
    if last_exc is not None:
        raise JwtIssueError("INVALID_TOKEN") from last_exc
    raise JwtIssueError("INVALID_TOKEN")
