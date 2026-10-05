from __future__ import annotations

import re
import unicodedata
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Organization, OrganizationMember, User


_SUPERADMIN_ROLE = "superadmin"


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

    org = await create_organization(
        db,
        owner_id=user.id,
        business_name=make_personal_org_name(user.name, user.email),
        business_email=user.email,
    )
    if not user.default_org_id:
        user.default_org_id = org.id
        await db.flush()
    return org


async def list_organizations_for_user(db: AsyncSession, user_id: str) -> list[Organization]:
    items, _ = await query_organizations(
        db, user_id=user_id, limit=10_000, order_desc=False
    )
    return items


async def list_all_organizations(db: AsyncSession) -> list[Organization]:
    items, _ = await query_organizations(
        db, user_id=None, limit=10_000, order_desc=False
    )
    return items


def _organization_search_filter(q, search: str | None):
    if not search:
        return q
    escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    return q.where(
        or_(
            Organization.business_name.ilike(pattern, escape="\\"),
            Organization.business_email.ilike(pattern, escape="\\"),
        )
    )


async def query_organizations(
    db: AsyncSession,
    *,
    user_id: str | None = None,
    search: str | None = None,
    offset: int = 0,
    limit: int = 50,
    ensure_id: str | None = None,
    order_desc: bool = True,
) -> tuple[list[Organization], int]:
    """Paginated organization list. ``user_id=None`` returns all orgs (superadmin)."""
    safe_limit = min(max(limit, 1), 100)
    safe_offset = max(offset, 0)

    q = select(Organization)
    if user_id is not None:
        q = (
            q.join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .where(OrganizationMember.user_id == user_id)
        )
    q = _organization_search_filter(q, (search or "").strip() or None)

    count_q = select(func.count()).select_from(q.subquery())
    total = int((await db.execute(count_q)).scalar_one() or 0)

    # Prefer shared team orgs over the auto-created personal workspace when listing.
    personal_last = Organization.business_name.like("%'s Workspace")
    order = Organization.created_at.desc() if order_desc else Organization.created_at.asc()
    rows = await db.execute(
        q.order_by(personal_last.asc(), order)
        .offset(safe_offset)
        .limit(safe_limit)
    )
    items = list(rows.scalars().all())

    if ensure_id and not any(o.id == ensure_id for o in items):
        extra_q = select(Organization).where(Organization.id == ensure_id)
        if user_id is not None:
            extra_q = (
                extra_q.join(
                    OrganizationMember,
                    OrganizationMember.organization_id == Organization.id,
                ).where(OrganizationMember.user_id == user_id)
            )
        extra = (await db.execute(extra_q.limit(1))).scalar_one_or_none()
        if extra is not None:
            items = [extra, *items]

    return items, total


async def get_organization_role_for_user(
    db: AsyncSession, user_id: str, organization_id: str | None
) -> str | None:
    if not organization_id:
        return None
    role = (
        await db.execute(select(User.role).where(User.id == user_id).limit(1))
    ).scalar_one_or_none()
    if role == _SUPERADMIN_ROLE:
        return "owner"
    return (
        await db.execute(
            select(OrganizationMember.role)
            .where(OrganizationMember.user_id == user_id)
            .where(OrganizationMember.organization_id == organization_id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def list_organization_members(
    db: AsyncSession, organization_id: str
) -> list[tuple[OrganizationMember, User]]:
    result = await db.execute(
        select(OrganizationMember, User)
        .join(User, User.id == OrganizationMember.user_id)
        .where(OrganizationMember.organization_id == organization_id)
        .order_by(OrganizationMember.created_at)
    )
    return list(result.all())


async def get_organization_member(
    db: AsyncSession, organization_id: str, user_id: str
) -> OrganizationMember | None:
    return (
        await db.execute(
            select(OrganizationMember)
            .where(OrganizationMember.organization_id == organization_id)
            .where(OrganizationMember.user_id == user_id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def add_organization_member(
    db: AsyncSession,
    *,
    organization_id: str,
    user_id: str,
    role: str = "member",
) -> OrganizationMember:
    member = OrganizationMember(
        organization_id=organization_id,
        user_id=user_id,
        role=role,
    )
    db.add(member)
    await db.flush()
    return member


async def remove_organization_member(
    db: AsyncSession, organization_id: str, user_id: str
) -> bool:
    member = await get_organization_member(db, organization_id, user_id)
    if member is None:
        return False
    await db.delete(member)
    await db.flush()
    return True


async def count_organization_owners(
    db: AsyncSession, organization_id: str
) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(OrganizationMember)
        .where(OrganizationMember.organization_id == organization_id)
        .where(OrganizationMember.role == "owner")
    )
    return int(result.scalar_one() or 0)


async def update_organization_member_role(
    db: AsyncSession,
    *,
    organization_id: str,
    user_id: str,
    role: str,
) -> OrganizationMember | None:
    member = await get_organization_member(db, organization_id, user_id)
    if member is None:
        return None
    member.role = role
    await db.flush()
    return member


async def get_current_org_for_user(db: AsyncSession, user_id: str) -> Organization | None:
    """Current organization for auth scoping.

    Today this is ``users.default_org_id`` if set, else first membership.
    """
    row = (
        await db.execute(select(User.default_org_id).where(User.id == user_id).limit(1))
    ).scalar_one_or_none()
    if row:
        return (
            await db.execute(select(Organization).where(Organization.id == row).limit(1))
        ).scalar_one_or_none()
    orgs = await list_organizations_for_user(db, user_id)
    return orgs[0] if orgs else None
