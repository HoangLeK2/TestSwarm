from __future__ import annotations

from importlib import import_module
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.deps import _get_db
from api.routes import auth as auth_routes
from api.routes.auth import router as auth_router
from db.crud.organization import (
    create_personal_org_for_user,
    make_personal_org_name,
)
from db.database import Base
from db.migrations import _CompatConn
from db.models import Organization, OrganizationMember, User

personal_org_backfill = import_module("db.migrations.037_personal_org_backfill")


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _build_auth_app(session_factory) -> FastAPI:
    app = FastAPI()
    app.include_router(auth_router, prefix="/api")

    async def _db_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[_get_db] = _db_override
    return app


def test_make_personal_org_name_uses_name():
    assert make_personal_org_name("Hoang", "hoang@example.com") == "Hoang's Workspace"


def test_make_personal_org_name_strips_vietnamese_diacritics():
    assert make_personal_org_name("Hoàng", "hoang@example.com") == "Hoang's Workspace"
    assert make_personal_org_name("Đức Anh", "duc@example.com") == "Duc Anh's Workspace"
    assert make_personal_org_name("Lệ Nguyễn", "le@example.com") == "Le Nguyen's Workspace"


def test_make_personal_org_name_falls_back_to_email_prefix():
    assert make_personal_org_name("", "owner@example.com") == "owner's Workspace"
    assert make_personal_org_name("山田", "yamada@example.com") == "yamada's Workspace"
    assert make_personal_org_name("山田", "") == "My Workspace"


@pytest.mark.asyncio
async def test_create_personal_org_for_user_creates_owner_membership(session_factory):
    user = User(
        id="user-1",
        email="hoang@example.com",
        name="Hoàng",
        hashed_password="hashed",
    )
    async with session_factory() as session:
        session.add(user)
        await session.flush()

        org = await create_personal_org_for_user(session, user)
        assert org is not None
        assert org.business_name == "Hoang's Workspace"
        assert org.business_email == "hoang@example.com"

        member = (
            await session.execute(
                select(OrganizationMember)
                .where(OrganizationMember.user_id == user.id)
                .where(OrganizationMember.organization_id == org.id)
            )
        ).scalar_one()
        assert member.role == "owner"


@pytest.mark.asyncio
async def test_create_personal_org_for_user_skips_existing_membership(session_factory):
    async with session_factory() as session:
        user = User(
            id="user-1",
            email="owner@example.com",
            name="Owner",
            hashed_password="hashed",
        )
        existing = Organization(id="org-1", business_name="Existing")
        session.add_all([user, existing])
        await session.flush()
        session.add(
            OrganizationMember(
                id="member-1",
                user_id=user.id,
                organization_id=existing.id,
                role="owner",
            )
        )
        await session.flush()

        assert await create_personal_org_for_user(session, user) is None
        count = (
            await session.execute(select(OrganizationMember).where(OrganizationMember.user_id == user.id))
        ).scalars().all()
        assert len(count) == 1


@pytest.mark.asyncio
async def test_register_route_creates_default_org(session_factory):
    app = _build_auth_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.post(
            "/api/auth/register",
            json={
                "email": "new@example.com",
                "name": "Nguyễn Văn A",
                "password": "secret123",
            },
        )
        assert response.status_code == 201, response.text

    async with session_factory() as session:
        user = (
            await session.execute(select(User).where(User.email == "new@example.com"))
        ).scalar_one()
        orgs = await session.execute(
            select(Organization, OrganizationMember)
            .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .where(OrganizationMember.user_id == user.id)
        )
        org, member = orgs.one()
        assert org.business_name == "Nguyen Van A's Workspace"
        assert org.business_email == "new@example.com"
        assert member.role == "owner"


@pytest.mark.asyncio
async def test_register_route_rolls_back_user_when_org_creation_fails(
    session_factory,
    monkeypatch,
):
    async def fail_personal_org(*_args, **_kwargs):
        raise RuntimeError("org create failed")

    monkeypatch.setattr(
        auth_routes.repo,
        "create_personal_org_for_user",
        fail_personal_org,
    )

    app = _build_auth_app(session_factory)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.post(
            "/api/auth/register",
            json={
                "email": "rollback@example.com",
                "name": "Rollback User",
                "password": "secret123",
            },
        )
        assert response.status_code == 500

    async with session_factory() as session:
        user = (
            await session.execute(
                select(User).where(User.email == "rollback@example.com")
            )
        ).scalar_one_or_none()
        assert user is None


@pytest.mark.asyncio
async def test_personal_org_backfill_migration_is_idempotent(engine):
    async with engine.begin() as conn:
        await conn.execute(
            User.__table__.insert().values(
                id="orphan-user",
                email="orphan@example.com",
                name="Orphan",
                hashed_password="hashed",
            )
        )
        compat = _CompatConn(conn)
        await personal_org_backfill.upgrade(compat)
        await personal_org_backfill.upgrade(compat)

        rows = (
            await conn.execute(
                select(Organization.business_name, OrganizationMember.role)
                .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
                .where(OrganizationMember.user_id == "orphan-user")
            )
        ).all()
        assert rows == [("Orphan's Workspace", "owner")]
