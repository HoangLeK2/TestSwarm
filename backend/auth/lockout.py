"""Account lockout after repeated failed logins (DF-T-01-011)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from core.env import (
    lockout_duration_minutes,
    lockout_failed_threshold,
    lockout_window_minutes,
)
from db import crud as repo
from db.models.user import User


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_account_locked(user: User) -> bool:
    locked_until = getattr(user, "locked_until", None)
    if locked_until is None:
        return False
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    return locked_until > _now()


def lock_expires_at(user: User) -> datetime | None:
    locked_until = getattr(user, "locked_until", None)
    if locked_until is None:
        return None
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    return locked_until if locked_until > _now() else None


async def is_last_org_owner(db: AsyncSession, user: User, org_id: str | None) -> bool:
    if not org_id:
        return False
    role = await repo.get_organization_role_for_user(db, user.id, org_id)
    if role != "owner":
        return False
    owner_count = await repo.count_organization_owners(db, org_id)
    return owner_count <= 1


def _reset_fail_window_if_expired(user: User, now: datetime) -> None:
    last = getattr(user, "last_failed_login_at", None)
    if last is None:
        return
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    window = timedelta(minutes=lockout_window_minutes())
    if now - last > window:
        user.failed_login_count = 0


async def record_failed_login(
    db: AsyncSession,
    user: User,
    org_id: str | None,
) -> tuple[bool, bool]:
    """Increment fail counter; lock if threshold reached.

    Returns (locked_now, skip_last_admin).
    """
    now = _now()
    _reset_fail_window_if_expired(user, now)
    user.failed_login_count = int(getattr(user, "failed_login_count", 0) or 0) + 1
    user.last_failed_login_at = now

    if user.failed_login_count < lockout_failed_threshold():
        await db.flush()
        return False, False

    if await is_last_org_owner(db, user, org_id):
        await db.flush()
        return False, True

    user.locked_until = now + timedelta(minutes=lockout_duration_minutes())
    await db.flush()
    return True, False


async def clear_lockout_state(db: AsyncSession, user: User) -> bool:
    """Reset counters on successful login. Returns True if auto-unlocked expired lock."""
    was_locked = is_account_locked(user) or getattr(user, "locked_until", None) is not None
    auto_unlocked = was_locked and not is_account_locked(user)
    user.failed_login_count = 0
    user.locked_until = None
    user.last_failed_login_at = None
    await db.flush()
    return auto_unlocked


async def admin_unlock(db: AsyncSession, user: User) -> None:
    user.failed_login_count = 0
    user.locked_until = None
    user.last_failed_login_at = None
    await db.flush()
