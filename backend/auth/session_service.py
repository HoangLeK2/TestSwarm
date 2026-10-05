"""Session lifecycle helpers backed by refresh_tokens (DF-T-01-012)."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.env import session_idle_timeout_days
from db.models.refresh_token import RefreshToken


def device_fingerprint(*, user_agent: str | None, ip: str | None) -> str:
    raw = f"{user_agent or ''}|{ip or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def user_agent_summary(user_agent: str | None) -> str | None:
    if not user_agent:
        return None
    ua = user_agent.strip()
    if len(ua) <= 80:
        return ua
    return ua[:77] + "..."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def list_active_sessions(
    db: AsyncSession,
    user_id: str,
    *,
    current_session_id: str | None = None,
) -> list[dict]:
    now = _now()
    rows = (
        await db.execute(
            select(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > now,
            )
            .order_by(RefreshToken.last_used_at.desc().nullslast(), RefreshToken.created_at.desc())
        )
    ).scalars().all()

    out: list[dict] = []
    for row in rows:
        out.append(
            {
                "session_id": row.id,
                "created_at": row.created_at,
                "last_used_at": row.last_used_at or row.created_at,
                "last_ip": row.last_ip,
                "user_agent_summary": user_agent_summary(row.user_agent),
                "is_current": bool(current_session_id and row.id == current_session_id),
            }
        )
    return out


async def revoke_session(
    db: AsyncSession,
    user_id: str,
    session_id: str,
) -> RefreshToken | None:
    row = (
        await db.execute(
            select(RefreshToken)
            .where(
                RefreshToken.id == session_id,
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    row.revoked_at = _now()
    await db.flush()
    return row


async def revoke_all_other_sessions(
    db: AsyncSession,
    user_id: str,
    *,
    current_session_id: str | None,
) -> list[str]:
    now = _now()
    q = select(RefreshToken).where(
        RefreshToken.user_id == user_id,
        RefreshToken.revoked_at.is_(None),
        RefreshToken.expires_at > now,
    )
    if current_session_id:
        q = q.where(RefreshToken.id != current_session_id)
    rows = (await db.execute(q)).scalars().all()
    revoked_ids: list[str] = []
    for row in rows:
        row.revoked_at = now
        revoked_ids.append(row.id)
    if revoked_ids:
        await db.flush()
    return revoked_ids


async def touch_session(
    db: AsyncSession,
    row: RefreshToken,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    row.last_used_at = _now()
    if ip:
        row.last_ip = ip[:64]
    if user_agent:
        row.user_agent = user_agent[:512]


async def revoke_idle_sessions(db: AsyncSession) -> list[str]:
    """Revoke sessions idle longer than configured threshold."""
    cutoff = _now() - timedelta(days=session_idle_timeout_days())
    rows = (
        await db.execute(
            select(RefreshToken).where(
                RefreshToken.revoked_at.is_(None),
                RefreshToken.last_used_at.is_not(None),
                RefreshToken.last_used_at < cutoff,
            )
        )
    ).scalars().all()
    revoked: list[str] = []
    now = _now()
    for row in rows:
        last_used = _aware(row.last_used_at) or _aware(row.created_at)
        if last_used is None or last_used >= cutoff:
            continue
        row.revoked_at = now
        revoked.append(row.id)
    if revoked:
        await db.flush()
    return revoked
