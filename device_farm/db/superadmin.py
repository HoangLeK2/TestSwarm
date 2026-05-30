from __future__ import annotations

import os
import secrets

from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud.organization import make_personal_org_name
from db.models import Organization, OrganizationMember, User
from db import crud as repo


_pwd = CryptContext(schemes=["bcrypt_sha256"], deprecated="auto")
_SUPERADMIN_ROLE = "superadmin"


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def hash_superadmin_password(password: str) -> str:
    return _pwd.hash(password)


def verify_superadmin_password(password: str, hashed: str) -> bool:
    return _pwd.verify(password, hashed)


async def _attach_personal_org(db: AsyncSession, user: User) -> None:
    """Ensure user has a personal org before persisting users.org_id (NOT NULL)."""
    if user.org_id:
        return
    org = Organization(
        business_name=make_personal_org_name(user.name, user.email),
        business_email=user.email,
    )
    db.add(org)
    await db.flush()
    user.org_id = org.id
    db.add(
        OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role="owner",
        )
    )
    await db.flush()


async def ensure_superadmin_from_env(db: AsyncSession) -> User | None:
    """Upsert the global superadmin account when env credentials are configured.

    This runs at startup so adding env vars after migration 051 has already been
    recorded still creates or repairs the account on the next restart.
    """
    email = _env("DEVICE_FARM_SUPERADMIN_EMAIL").lower()
    password = _env("DEVICE_FARM_SUPERADMIN_PASSWORD")
    if not email or not password:
        return None

    name = _env("DEVICE_FARM_SUPERADMIN_NAME") or "Super Admin"
    hashed_password = hash_superadmin_password(password)
    existing = await repo.get_user_by_email(db, email)
    if existing is not None:
        existing.name = name
        existing.hashed_password = hashed_password
        existing.role = _SUPERADMIN_ROLE
        existing.is_active = True
        if not existing.org_id:
            await _attach_personal_org(db, existing)
        else:
            await db.flush()
        return existing

    # Create org before the user row: a pending User is auto-flushed with the org
    # and would violate users.org_id NOT NULL if org_id is still unset.
    org = Organization(
        business_name=make_personal_org_name(name, email),
        business_email=email,
    )
    db.add(org)
    await db.flush()
    user = User(
        email=email,
        name=name,
        hashed_password=hashed_password,
        api_key=secrets.token_urlsafe(32)[:64],
        role=_SUPERADMIN_ROLE,
        is_active=True,
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
