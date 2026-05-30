"""AC-4: disabled org blocks login."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.deps import _get_db
from api.routes.auth import router as auth_router
from db.database import Base
from db.models import Organization, OrganizationMember, User
from db import crud as repo
from auth.password_service import hash_password


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


@pytest.mark.asyncio
async def test_login_blocked_when_org_disabled(session_factory, monkeypatch):
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        org = Organization(
            id="org-stale",
            business_name="Stale Org",
            status="disabled",
            created_at=now,
        )
        user = User(
            id="user-ed",
            email="ed@stale.example",
            name="Ed",
            hashed_password=hash_password("secret"),
            org_id="org-stale",
        )
        session.add_all([org, user])
        await session.flush()
        session.add(
            OrganizationMember(
                id="mem-ed",
                organization_id=org.id,
                user_id=user.id,
                role="owner",
                created_at=now,
            )
        )
        await session.commit()

    async def fake_get_user_by_email(db, email):
        return user

    monkeypatch.setattr(repo, "get_user_by_email", fake_get_user_by_email)

    app = _build_auth_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            "/api/auth/login",
            json={"email": "ed@stale.example", "password": "secret"},
        )
    assert resp.status_code == 403
    detail = resp.json().get("detail")
    if isinstance(detail, dict):
        assert detail.get("code") == "ORG_DISABLED"
    else:
        assert "ORG_DISABLED" in str(detail) or "disabled" in str(detail).lower()
