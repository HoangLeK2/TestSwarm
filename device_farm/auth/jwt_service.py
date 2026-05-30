"""JWT access token issue/decode helpers (DF-T-01-002)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from jose import JWTError, ExpiredSignatureError, jwt

from core.env import access_expire_hours
from core.security import jwt_algorithm, jwt_secret_key


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
    token = jwt.encode(payload, jwt_secret_key(), algorithm=jwt_algorithm())
    return token, access_ttl_seconds(), token_jti


def decode_access_payload(raw_token: str) -> dict:
    try:
        return jwt.decode(raw_token, jwt_secret_key(), algorithms=[jwt_algorithm()])
    except ExpiredSignatureError as exc:
        raise JwtIssueError("TOKEN_EXPIRED") from exc
    except JWTError as exc:
        raise JwtIssueError("INVALID_TOKEN") from exc
