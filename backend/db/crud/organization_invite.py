from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Organization, OrganizationInvitation, OrganizationMember, User


def _new_token() -> str:
    return secrets.token_urlsafe(32)


async def get_pending_invitation_by_org_email(
    db: AsyncSession, organization_id: str, email: str
) -> OrganizationInvitation | None:
    normalized = (email or "").strip().lower()
    return (
        await db.execute(
            select(OrganizationInvitation)
            .where(OrganizationInvitation.organization_id == organization_id)
            .where(func.lower(OrganizationInvitation.email) == normalized)
            .where(OrganizationInvitation.status == "pending")
            .limit(1)
        )
    ).scalar_one_or_none()


async def get_invitation_by_token(
    db: AsyncSession, token: str
) -> OrganizationInvitation | None:
    cleaned = (token or "").strip()
    if not cleaned:
        return None
    return (
        await db.execute(
            select(OrganizationInvitation)
            .where(OrganizationInvitation.token == cleaned)
            .limit(1)
        )
    ).scalar_one_or_none()


async def create_or_refresh_organization_invitation(
    db: AsyncSession,
    *,
    organization_id: str,
    email: str,
    role: str,
    invited_by_user_id: str | None,
    expire_days: int,
) -> OrganizationInvitation:
    normalized = (email or "").strip().lower()
    expires_at = datetime.now(timezone.utc) + timedelta(days=max(1, expire_days))
    existing = await get_pending_invitation_by_org_email(db, organization_id, normalized)
    if existing is not None:
        existing.token = _new_token()
        existing.role = role
        existing.invited_by_user_id = invited_by_user_id
        existing.expires_at = expires_at
        await db.flush()
        return existing

    invite = OrganizationInvitation(
        organization_id=organization_id,
        email=normalized,
        role=role,
        token=_new_token(),
        status="pending",
        invited_by_user_id=invited_by_user_id,
        expires_at=expires_at,
    )
    db.add(invite)
    await db.flush()
    return invite


async def mark_invitation_accepted(
    db: AsyncSession,
    invitation: OrganizationInvitation,
    *,
    user_id: str,
) -> OrganizationInvitation:
    invitation.status = "accepted"
    invitation.accepted_by_user_id = user_id
    invitation.accepted_at = datetime.now(timezone.utc)
    await db.flush()
    return invitation


async def get_organization_by_id(
    db: AsyncSession, organization_id: str
) -> Organization | None:
    return (
        await db.execute(
            select(Organization).where(Organization.id == organization_id).limit(1)
        )
    ).scalar_one_or_none()


async def user_has_membership(
    db: AsyncSession, organization_id: str, user_id: str
) -> bool:
    row = (
        await db.execute(
            select(OrganizationMember.id)
            .where(OrganizationMember.organization_id == organization_id)
            .where(OrganizationMember.user_id == user_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None
