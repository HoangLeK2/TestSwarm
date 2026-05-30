"""Central authorization checks.

Routes express intent via `assert_owns_*` calls. Each check raises
HTTPException(403) if the caller cannot act on the subject, or 404 when
returning 403 would leak existence to a non-owner (e.g. sessions).
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status

from api.auth.context import AuthContext
from api.org_scope import resource_visible_to_user
from db import crud as repo
from db.database import AsyncSessionLocal
from tenancy.background import lookup_device_by_serial


async def assert_owns_device(ctx: AuthContext, serial: str) -> None:
    async with AsyncSessionLocal() as db:
        ref = await lookup_device_by_serial(db, serial)
        if ref is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to control this device",
            )
        user = await repo.get_user(db, ctx.user_id)
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to control this device",
            )
        org_id = getattr(user, "org_id", None)
        user.org_role = await repo.get_organization_role_for_user(  # type: ignore[attr-defined]
            db, user.id, org_id
        )
        visible = await resource_visible_to_user(
            db,
            user,
            owner_user_id=ref.user_id,
            org_id=ref.org_id,
        )
    if not visible:
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
    try:
        await assert_owns_device(ctx, serial)
        return True
    except HTTPException:
        return False
