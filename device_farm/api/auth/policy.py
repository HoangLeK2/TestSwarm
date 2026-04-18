"""Central authorization checks.

Routes express intent via `assert_owns_*` calls. Each check raises
HTTPException(403) if the caller cannot act on the subject, or 404 when
returning 403 would leak existence to a non-owner (e.g. sessions).
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status

from api.auth.context import AuthContext
from db import crud as repo
from db.database import AsyncSessionLocal


async def assert_owns_device(ctx: AuthContext, serial: str) -> None:
    async with AsyncSessionLocal() as db:
        rows = await repo.list_devices(db, user_id=ctx.user_id)
    allowed = {d.serial for d in rows if d.serial}
    if serial not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to control this device",
        )


async def assert_owns_session(ctx: AuthContext, session_id: str) -> Optional[str]:
    """Verify ctx owns mcp_session(session_id); return device_serial on success.

    Uses 404 on mismatch so tenants cannot probe for each other's session ids.
    """
    async with AsyncSessionLocal() as db:
        row = await repo.get_mcp_session(db, session_id)
    if row is None or row.status != "active":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    if row.user_id and row.user_id != ctx.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    return row.device_serial


async def user_owns_device(ctx: AuthContext, serial: str) -> bool:
    """Boolean variant for places that cannot raise (e.g. preview stream
    owner checks); prefer `assert_owns_device` everywhere else."""
    async with AsyncSessionLocal() as db:
        rows = await repo.list_devices(db, user_id=ctx.user_id)
    return serial in {d.serial for d in rows if d.serial}
