"""Epic 01 Phase 1: refresh rotation, lockout, password policy, security audit."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.deps import _get_current_user, _get_db
from api.routes.auth import router as auth_router
from api.routes.me import router as me_router
from api.routes.organizations import router as org_router
from auth.password_service import hash_password
from db.database import Base
from db.models import Organization, OrganizationMember, User
from db.models.activity import ActivityLog
from db.models.refresh_token import RefreshToken


PASS = "Str0ng!Pass#123"
WEAK = "password"


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


def _build_app(session_factory, *, include_org: bool = False) -> FastAPI:
    app = FastAPI()
    app.include_router(auth_router, prefix="/api")
    app.include_router(me_router, prefix="/api")
    if include_org:
        app.include_router(org_router, prefix="/api")

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


async def _seed_user(
    session_factory,
    *,
    email: str = "alice@acme.example",
    password: str = PASS,
    user_id: str = "user-alice",
    org_id: str = "org-acme",
    failed_login_count: int = 0,
    locked_until: datetime | None = None,
    member_role: str = "member",
) -> User:
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        org = Organization(
            id=org_id,
            business_name="Acme",
            business_email="acme@example.com",
            status="active",
            created_at=now,
        )
        user = User(
            id=user_id,
            email=email,
            name="Alice",
            hashed_password=hash_password(password),
            org_id=org_id,
            failed_login_count=failed_login_count,
            locked_until=locked_until,
        )
        session.add_all([org, user])
        await session.flush()
        owner_user = User(
            id="owner-other",
            email="owner@acme.example",
            name="Owner",
            hashed_password=hash_password("OwnerStr0ng!Pass"),
            org_id=org_id,
        )
        session.add(owner_user)
        await session.flush()
        session.add_all(
            [
                OrganizationMember(
                    id="mem-alice",
                    organization_id=org_id,
                    user_id=user_id,
                    role=member_role,
                    created_at=now,
                ),
                OrganizationMember(
                    id="mem-owner",
                    organization_id=org_id,
                    user_id="owner-other",
                    role="owner",
                    created_at=now,
                ),
            ]
        )
        await session.commit()
    return user


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


@pytest.mark.asyncio
async def test_login_success_returns_tokens_and_audit(session_factory):
    await _seed_user(session_factory)
    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            "/api/auth/login",
            json={"email": "alice@acme.example", "password": PASS},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["expires_in"] > 0

    async with session_factory() as session:
        refresh_count = (
            await session.execute(select(RefreshToken))
        ).scalars().all()
        assert len(refresh_count) == 1
        audits = (
            await session.execute(
                select(ActivityLog).where(ActivityLog.action == "auth.login.success")
            )
        ).scalars().all()
        assert len(audits) == 1


@pytest.mark.asyncio
async def test_login_wrong_password_returns_invalid_credentials(session_factory):
    await _seed_user(session_factory)
    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            "/api/auth/login",
            json={"email": "alice@acme.example", "password": "wrong"},
        )
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_refresh_rotation_revokes_old_token(session_factory):
    await _seed_user(session_factory)
    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        login = await client.post(
            "/api/auth/login",
            json={"email": "alice@acme.example", "password": PASS},
        )
        r1 = login.json()["refresh_token"]
        refreshed = await client.post("/api/auth/refresh", json={"refresh_token": r1})
        assert refreshed.status_code == 200
        r2 = refreshed.json()["refresh_token"]
        replay = await client.post("/api/auth/refresh", json={"refresh_token": r1})
        assert replay.status_code == 401
        assert replay.json()["detail"]["code"] == "REFRESH_REVOKED"
        ok = await client.post("/api/auth/refresh", json={"refresh_token": r2})
        assert ok.status_code == 200


@pytest.mark.asyncio
async def test_logout_revokes_refresh_token(session_factory):
    user = await _seed_user(session_factory)
    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        login = await client.post(
            "/api/auth/login",
            json={"email": "alice@acme.example", "password": PASS},
        )
        tokens = login.json()
        app.dependency_overrides[_get_current_user] = lambda: user  # type: ignore[assignment]
        logout = await client.post(
            "/api/auth/logout",
            json={"refresh_token": tokens["refresh_token"]},
            headers=_auth_headers(tokens["access_token"]),
        )
        assert logout.status_code == 204
        replay = await client.post(
            "/api/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert replay.status_code == 401


@pytest.mark.asyncio
async def test_account_lockout_after_failed_attempts(session_factory, monkeypatch):
    monkeypatch.setattr("auth.lockout.lockout_failed_threshold", lambda: 3)
    await _seed_user(session_factory)
    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        for _ in range(3):
            await client.post(
                "/api/auth/login",
                json={"email": "alice@acme.example", "password": "wrong"},
            )
        locked = await client.post(
            "/api/auth/login",
            json={"email": "alice@acme.example", "password": PASS},
        )
    assert locked.status_code == 423
    assert locked.json()["detail"]["code"] == "ACCOUNT_LOCKED"


@pytest.mark.asyncio
async def test_wrong_password_on_locked_account_still_401(session_factory, monkeypatch):
    monkeypatch.setattr("auth.lockout.lockout_failed_threshold", lambda: 2)
    locked_until = datetime.now(timezone.utc) + timedelta(minutes=30)
    await _seed_user(
        session_factory,
        failed_login_count=5,
        locked_until=locked_until,
    )
    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            "/api/auth/login",
            json={"email": "alice@acme.example", "password": "wrong"},
        )
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_change_password_weak_rejected(session_factory):
    user = await _seed_user(session_factory)
    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        login = await client.post(
            "/api/auth/login",
            json={"email": "alice@acme.example", "password": PASS},
        )
        app.dependency_overrides[_get_current_user] = lambda: user  # type: ignore[assignment]
        resp = await client.post(
            "/api/me/change-password",
            json={"current_password": PASS, "new_password": WEAK},
            headers=_auth_headers(login.json()["access_token"]),
        )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "WEAK_PASSWORD"


@pytest.mark.asyncio
async def test_admin_unlock_member(session_factory):
    locked_until = datetime.now(timezone.utc) + timedelta(minutes=30)
    await _seed_user(
        session_factory,
        failed_login_count=5,
        locked_until=locked_until,
    )
    app = _build_app(session_factory, include_org=True)

    async def _admin():
        u = User(
            id="admin-1",
            email="admin@acme.example",
            name="Admin",
            hashed_password="x",
            org_id="org-acme",
        )
        u.org_role = "owner"  # type: ignore[attr-defined]
        return u

    app.dependency_overrides[_get_current_user] = _admin  # type: ignore[assignment]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post("/api/organizations/members/user-alice/unlock")
    assert resp.status_code == 204

    async with session_factory() as session:
        user = (
            await session.execute(select(User).where(User.id == "user-alice"))
        ).scalar_one()
        assert user.failed_login_count == 0
        assert user.locked_until is None
