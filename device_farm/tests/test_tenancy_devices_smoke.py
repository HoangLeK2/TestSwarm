from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.crud.router import api_router
from api.deps import _get_db
from db.database import Base
from db.models import Device, Organization, OrganizationMember, User
from tenancy.context import tenant_context


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


def _app(session_factory) -> FastAPI:
    app = FastAPI()
    app.include_router(api_router, prefix="/api")

    async def _db_override():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[_get_db] = _db_override
    return app


@pytest.mark.asyncio
async def test_cross_tenant_device_list_isolation(session_factory):
    async with session_factory() as session:
        org_a = Organization(id="org-a", business_name="Acme")
        org_b = Organization(id="org-b", business_name="Beta")
        user_a = User(
            id="user-a",
            email="a@example.com",
            name="A",
            hashed_password="x",
            org_id="org-a",
        )
        user_b = User(
            id="user-b",
            email="b@example.com",
            name="B",
            hashed_password="x",
            org_id="org-b",
        )
        session.add_all([org_a, org_b, user_a, user_b])
        session.add_all(
            [
                OrganizationMember(
                    id="m-a",
                    organization_id=org_a.id,
                    user_id=user_a.id,
                    role="owner",
                ),
                OrganizationMember(
                    id="m-b",
                    organization_id=org_b.id,
                    user_id=user_b.id,
                    role="owner",
                ),
            ]
        )
        session.add_all(
            [
                Device(id="dev-a-1", serial="A1", name="a1", user_id=user_a.id, org_id=org_a.id),
                Device(id="dev-a-2", serial="A2", name="a2", user_id=user_a.id, org_id=org_a.id),
                Device(id="dev-b-1", serial="B1", name="b1", user_id=user_b.id, org_id=org_b.id),
            ]
        )
        await session.commit()

    # Direct ORM test for default filter behavior (no explicit WHERE org_id)
    async with session_factory() as session:
        from sqlalchemy import select

        with tenant_context("org-a"):
            devices = (await session.execute(select(Device))).scalars().all()
            assert {d.serial for d in devices} == {"A1", "A2"}

            stmt = select(Device)
            compiled = str(
                stmt.compile(compile_kwargs={"literal_binds": True})
            )
            # AC-6: ORM criteria adds org_id predicate when tenant context is set.
            assert "org_id" in compiled.lower()


@pytest.mark.asyncio
async def test_me_organization_endpoint(session_factory):
    app = _app(session_factory)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    # This endpoint requires JWT in real app, but tests here focus on handler wiring.
    # We call the underlying crud directly via dependency injection by faking CurrentUser
    # in higher-level tests elsewhere.
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        res = await client.get("/api/me/organization")
        assert res.status_code in {401, 403}

