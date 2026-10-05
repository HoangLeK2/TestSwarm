from __future__ import annotations

"""End-to-end (HTTP) tests for /api/account-groups routes."""

from types import SimpleNamespace
from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.deps import _get_current_user, _get_db
from api.routes.account_groups import router as account_groups_router
from db.database import Base
from db.models.account_group import AccountGroup, AccountGroupMember  # noqa: F401
from tenancy.context import set_current_org_id
from tests.tenancy_test_support import seed_casbin_policy_tables


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await seed_casbin_policy_tables(conn)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _build_app(session_factory) -> FastAPI:
    app = FastAPI()
    app.include_router(account_groups_router, prefix="/api")

    async def _db_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as s:
            yield s

    async def _user_override():
        set_current_org_id("org-1")
        return SimpleNamespace(
            id="user-1",
            role="operator",
            org_role="owner",
            is_active=True,
            org_id="org-1",
        )

    app.dependency_overrides[_get_db] = _db_override
    app.dependency_overrides[_get_current_user] = _user_override
    return app


@pytest.mark.asyncio
async def test_create_then_list(session_factory):
    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/api/account-groups",
            json={
                "name": "FB Pool",
                "platform": "instagram",
                "rotation_strategy": "round_robin",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["name"] == "FB Pool"
        assert body["platform"] == "instagram"
        gid = body["id"]

        r2 = await ac.get("/api/account-groups")
        assert r2.status_code == 200
        groups = r2.json()
        assert len(groups) == 1
        assert groups[0]["id"] == gid
