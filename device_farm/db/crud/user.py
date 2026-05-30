from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Organization, OrganizationMember, User
from db.crud.organization import make_personal_org_name


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    normalized = (email or "").strip().lower()
    result = await db.execute(
        select(User).where(func.lower(User.email) == normalized)
    )
    return result.scalar_one_or_none()


async def get_user_by_api_key(db: AsyncSession, api_key: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.api_key == api_key))
    return result.scalar_one_or_none()


async def get_user(db: AsyncSession, user_id: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_org_id(db: AsyncSession, user_id: str) -> str | None:
    result = await db.execute(select(User.org_id).where(User.id == user_id).limit(1))
    return result.scalar_one_or_none()


async def create_user(
    db: AsyncSession,
    email: str,
    name: str,
    hashed_password: str,
    role: str = "operator",
    *,
    org_id: str | None = None,
) -> User:
    """Insert user row. Prefer ``create_user_with_default_org`` when ``users.org_id`` is NOT NULL."""
    user = User(
        email=email,
        name=name,
        hashed_password=hashed_password,
        role=role,
        org_id=org_id,
    )
    db.add(user)
    await db.flush()
    return user


async def create_user_with_default_org(
    db: AsyncSession,
    email: str,
    name: str,
    hashed_password: str,
    role: str = "operator",
) -> User:
    """Create personal workspace + owner membership before user insert (org_id NOT NULL)."""
    normalized_email = (email or "").strip().lower()
    org = Organization(
        business_name=make_personal_org_name(name, normalized_email),
        business_email=normalized_email or None,
    )
    db.add(org)
    await db.flush()

    user = User(
        email=normalized_email,
        name=name,
        hashed_password=hashed_password,
        role=role,
        org_id=org.id,
    )
    db.add(user)
    await db.flush()
    db.add(
        OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role="owner",
        )
    )
    await db.flush()
    return user


async def list_users(db: AsyncSession) -> list[User]:
    result = await db.execute(select(User).order_by(User.created_at))
    return list(result.scalars().all())

