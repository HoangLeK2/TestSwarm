"""Org-scoped data access helpers for multi-tenant API routes."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from api.auth.rbac import is_superadmin
from db import crud as repo
from db.models.activity import ActivityLog
from db.models.device import Device
from db.models.user import User


def data_owner_user_id(user: User) -> str | None:
    """Optional per-user filter for legacy owner-scoped list queries.

    When the request has an active organization (``user.org_id`` set by
    ``CurrentUser`` / ``X-Organization-Id``), returns ``None`` so callers rely on
    ``org_id`` tenant scoping and see all resources in that org.

    Without an org context, non-superadmin users still see only their own rows.
    """
    if is_superadmin(user):
        return None
    if getattr(user, "org_id", None):
        return None
    return user.id


async def org_member_user_ids(db: AsyncSession, org_id: str) -> list[str]:
    """All user ids with membership in ``org_id`` (for shared non-tenant tables)."""
    member_rows = await repo.list_organization_members(db, org_id)
    return [str(member.user_id) for member, _ in member_rows if member.user_id]


async def resource_visible_to_user(
    db: AsyncSession,
    user: User,
    *,
    owner_user_id: str | None = None,
    org_id: str | None = None,
) -> bool:
    """Whether ``user`` may access a row in the current org context."""
    user_org = getattr(user, "org_id", None)
    if user_org:
        if org_id and str(org_id) == str(user_org):
            return True
        if owner_user_id:
            member_ids = await org_member_user_ids(db, user_org)
            if str(owner_user_id) in member_ids:
                return True
        return False
    if owner_user_id in (None, user.id):
        return True
    return str(owner_user_id) == str(user.id)


async def assert_resource_visible(
    db: AsyncSession,
    user: User,
    *,
    owner_user_id: str | None = None,
    org_id: str | None = None,
    detail: str = "Not found",
) -> None:
    if not await resource_visible_to_user(
        db,
        user,
        owner_user_id=owner_user_id,
        org_id=org_id,
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


async def device_visible_to_user(
    db: AsyncSession,
    user: User,
    device,
) -> bool:
    if device is None:
        return False
    return await resource_visible_to_user(
        db,
        user,
        owner_user_id=getattr(device, "user_id", None),
        org_id=getattr(device, "org_id", None),
    )


async def campaign_visible_to_user(db: AsyncSession, user: User, campaign) -> bool:
    if campaign is None:
        return False
    return await resource_visible_to_user(
        db,
        user,
        owner_user_id=getattr(campaign, "user_id", None),
        org_id=getattr(campaign, "org_id", None),
    )


async def activity_log_scope(
    db: AsyncSession,
    user: User,
) -> ColumnElement[bool]:
    """Activity feed scope: org members + org device serials when org is set."""
    org_id = getattr(user, "org_id", None)
    if not org_id:
        return ActivityLog.user_id == user.id

    member_rows = await repo.list_organization_members(db, org_id)
    member_ids = [member.user_id for member, _ in member_rows]

    serial_rows = await db.execute(
        select(Device.serial).where(Device.org_id == org_id, Device.serial.is_not(None))
    )
    serials = [row[0] for row in serial_rows.all() if row[0]]

    conditions: list[ColumnElement[bool]] = []
    conditions.append(ActivityLog.org_id == org_id)
    if member_ids:
        conditions.append(ActivityLog.user_id.in_(member_ids))
    if serials:
        conditions.append(ActivityLog.device_serial.in_(serials))
    if not conditions:
        return ActivityLog.user_id == user.id
    return or_(*conditions)
