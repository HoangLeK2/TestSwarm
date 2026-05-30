"""JWT helpers for token-protected content permalinks."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from jose import JWTError, jwt

from core.security import jwt_algorithm, jwt_secret_key

CONTENT_SHARE_TYPE = "content_share"
CONTENT_SHARE_DAYS = 30


def create_content_share_token(*, user_id: str, content_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=CONTENT_SHARE_DAYS)
    return jwt.encode(
        {
            "sub": user_id,
            "content_id": content_id,
            "type": CONTENT_SHARE_TYPE,
            "exp": expire,
        },
        jwt_secret_key(),
        algorithm=jwt_algorithm(),
    )


def verify_content_share_token(token: str, *, content_id: str) -> None:
    """Raise HTTPException 403 when the share token is invalid for this content."""
    if not token or not token.strip():
        raise HTTPException(status_code=403, detail="Share token required")
    try:
        payload = jwt.decode(
            token.strip(),
            jwt_secret_key(),
            algorithms=[jwt_algorithm()],
        )
    except JWTError as exc:
        raise HTTPException(status_code=403, detail="Invalid or expired share link") from exc

    if str(payload.get("type") or "") != CONTENT_SHARE_TYPE:
        raise HTTPException(status_code=403, detail="Invalid share link")
    if str(payload.get("content_id") or "") != content_id:
        raise HTTPException(status_code=403, detail="Share link does not match content")
