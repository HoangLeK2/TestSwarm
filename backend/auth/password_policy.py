"""Password complexity and reuse checks (DF-T-01-011)."""
from __future__ import annotations

import re

from auth.common_passwords import COMMON_PASSWORDS
from auth.password_service import verify_password
from core.env import password_history_size, password_min_length

_SPECIAL = re.compile(r"[^A-Za-z0-9]")


def validate_password_strength(password: str) -> list[str]:
    """Return list of violated rule codes; empty list means valid."""
    violations: list[str] = []
    pwd = password or ""
    if len(pwd) < password_min_length():
        violations.append("min_length")
    if not re.search(r"[A-Z]", pwd):
        violations.append("missing_uppercase")
    if not re.search(r"[a-z]", pwd):
        violations.append("missing_lowercase")
    if not re.search(r"\d", pwd):
        violations.append("missing_digit")
    if not _SPECIAL.search(pwd):
        violations.append("missing_special")
    if pwd.lower() in COMMON_PASSWORDS:
        violations.append("in_breach_list")
    return violations


async def assert_password_not_reused(
    db,
    user_id: str,
    new_password: str,
    *,
    current_hash: str | None = None,
) -> bool:
    """True if password matches a recent hash (reuse)."""
    from sqlalchemy import select

    from db.models.password_history import PasswordHistory

    if current_hash and verify_password(new_password, current_hash):
        return True

    limit = password_history_size()
    rows = (
        await db.execute(
            select(PasswordHistory)
            .where(PasswordHistory.user_id == user_id)
            .order_by(PasswordHistory.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    for row in rows:
        if verify_password(new_password, row.password_hash):
            return True
    return False


async def record_password_history(db, user_id: str, password_hash: str) -> None:
    from sqlalchemy import delete, select

    from db.models.password_history import PasswordHistory

    db.add(PasswordHistory(user_id=user_id, password_hash=password_hash))
    await db.flush()

    limit = password_history_size()
    ids = (
        await db.execute(
            select(PasswordHistory.id)
            .where(PasswordHistory.user_id == user_id)
            .order_by(PasswordHistory.created_at.desc())
        )
    ).scalars().all()
    stale = ids[limit:]
    if stale:
        await db.execute(delete(PasswordHistory).where(PasswordHistory.id.in_(stale)))
        await db.flush()
