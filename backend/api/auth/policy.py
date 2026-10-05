"""Central authorization checks.

Routes express intent via `assert_owns_*` calls. Each check raises
HTTPException(403) if the caller cannot act on the subject, or 404 when
returning 403 would leak existence to a non-owner (e.g. sessions).
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status

from api.auth.context import AuthContext
from api.org_scope import device_visible_to_user, resource_visible_to_user
from db import crud as repo
from db.database import AsyncSessionLocal
from tenancy.background import lookup_device_by_serial
from tenancy.resolve import get_user_default_org_id


async def assert_org_resource(
    *,
    resource_org_id: str | None,
    user_org_id: str | None,
    user_id: str,
    resource_id: str,
    resource_type: str = "resource",
) -> None:
    """Cross-org access returns 404 and emits ownership.violation audit."""
    if not resource_org_id or not user_org_id or resource_org_id == user_org_id:
        return
    async with AsyncSessionLocal() as db:
        from services.security_audit import emit_security_event

        await emit_security_event(
            db,
            action="ownership.violation",
            user_id=user_id,
            org_id=user_org_id,
            entity_type=resource_type,
            entity_id=resource_id,
            details={"resource_org_id": resource_org_id},
        )
        await db.commit()
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "NOT_FOUND"},
    )


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
        org_id = ctx.org_id or get_user_default_org_id(user)
        user.org_id = org_id  # type: ignore[attr-defined]
        user.org_role = await repo.get_organization_role_for_user(  # type: ignore[attr-defined]
            db, user.id, org_id
        )
        visible = await device_visible_to_user(db, user, ref)
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
