"""Opaque refresh token storage with rotation (DF-T-01-002)."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.session_service import device_fingerprint, touch_session
from core.env import refresh_expire_days
from db.models.refresh_token import RefreshToken
from db.models.user import User


class RefreshTokenError(Exception):
    code: str

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def issue_refresh_token(
    db: AsyncSession,
    user_id: str,
    *,
    device_fingerprint: str | None = None,
    last_ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, str]:
    """Return (raw_token, session_id)."""
    raw = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=refresh_expire_days())
    row = RefreshToken(
        user_id=user_id,
        token_hash=hash_refresh_token(raw),
        expires_at=expires_at,
        device_fingerprint=device_fingerprint,
        last_used_at=now,
        last_ip=(last_ip or None),
        user_agent=(user_agent or None),
    )
    db.add(row)
    await db.flush()
    return raw, row.id


async def revoke_refresh_token(db: AsyncSession, raw: str) -> bool:
    token_hash = hash_refresh_token(raw)
    row = (
        await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash).limit(1)
        )
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = datetime.now(timezone.utc)
    await db.flush()
    return True


async def rotate_refresh_token(
    db: AsyncSession,
    raw: str,
    *,
    last_ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[User, str, str]:
    """Validate refresh token, revoke it, issue a new one.

    Returns (user, new_raw_token, new_session_id).
    """
    token_hash = hash_refresh_token(raw)
    row = (
        await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash).limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise RefreshTokenError("INVALID_REFRESH")
    if row.revoked_at is not None:
        raise RefreshTokenError("REFRESH_REVOKED")
    now = datetime.now(timezone.utc)
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        raise RefreshTokenError("INVALID_REFRESH")

    user = (
        await db.execute(select(User).where(User.id == row.user_id).limit(1))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise RefreshTokenError("INVALID_REFRESH")

    await touch_session(db, row, ip=last_ip, user_agent=user_agent)
    row.revoked_at = now
    fp = row.device_fingerprint
    if not fp and (last_ip or user_agent):
        fp = device_fingerprint(user_agent=user_agent, ip=last_ip)
    new_raw, session_id = await issue_refresh_token(
        db,
        user.id,
        device_fingerprint=fp,
        last_ip=last_ip or row.last_ip,
        user_agent=user_agent or row.user_agent,
    )
    return user, new_raw, session_id
