from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Organization, OrganizationMember


async def create_organization(
    db: AsyncSession,
    owner_id: str,
    business_name: str,
    business_email: Optional[str] = None,
    business_logo: Optional[str] = None,
) -> Organization:
    org = Organization(
        business_name=(business_name or "").strip() or "Organization",
        business_email=(business_email or "").strip() or None,
        business_logo=(business_logo or "").strip() or None,
    )
    db.add(org)
    await db.flush()

    member = OrganizationMember(
        organization_id=org.id,
        user_id=owner_id,
        role="owner",
    )
    db.add(member)
    await db.flush()
    return org


async def list_organizations_for_user(db: AsyncSession, user_id: str) -> list[Organization]:
    result = await db.execute(
        select(Organization)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .where(OrganizationMember.user_id == user_id)
        .order_by(Organization.created_at)
    )
    return list(result.scalars().all())

