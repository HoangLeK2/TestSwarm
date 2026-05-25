from __future__ import annotations

import re
import unicodedata
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Organization, OrganizationMember, User


_DIACRITIC_MAP = str.maketrans({"đ": "d", "Đ": "D"})


def _ascii_fold(value: str | None) -> str:
    text = (value or "").translate(_DIACRITIC_MAP)
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(
        ch for ch in normalized
        if not unicodedata.combining(ch) and ord(ch) < 128
    )
    return re.sub(r"\s+", " ", ascii_text).strip()


def make_personal_org_name(name: str | None, email: str | None) -> str:
    base = _ascii_fold(name)
    if not base:
        prefix = (email or "").split("@", 1)[0]
        base = _ascii_fold(prefix)
    if not base:
        return "My Workspace"
    return f"{base}'s Workspace"


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


async def create_personal_org_for_user(
    db: AsyncSession,
    user: User,
) -> Optional[Organization]:
    result = await db.execute(
        select(OrganizationMember.id)
        .where(OrganizationMember.user_id == user.id)
        .limit(1)
    )
    if result.scalar_one_or_none() is not None:
        return None

    return await create_organization(
        db,
        owner_id=user.id,
        business_name=make_personal_org_name(user.name, user.email),
        business_email=user.email,
    )


async def list_organizations_for_user(db: AsyncSession, user_id: str) -> list[Organization]:
    result = await db.execute(
        select(Organization)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .where(OrganizationMember.user_id == user_id)
        .order_by(Organization.created_at)
    )
    return list(result.scalars().all())
