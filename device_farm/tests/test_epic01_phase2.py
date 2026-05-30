"""Epic 01 Phase 2: sessions, DB safe mode, RBAC codes, debounce."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.deps import _get_auth_context, _get_current_user, _get_db
from api.routes.admin import router as admin_router
from api.routes.auth import router as auth_router
from api.routes.sessions import router as sessions_router
from auth.jwt_service import issue_access_token
from auth.password_service import hash_password
from auth.refresh_token_service import issue_refresh_token
from auth.session_service import revoke_idle_sessions
from db.database import Base
from db.models import Organization, OrganizationMember, User
from db.models.activity import ActivityLog
from runtime.db_health import DbHealthMonitor


PASS = "Str0ng!Pass#123"


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


def _build_app(session_factory) -> FastAPI:
    app = FastAPI()
    app.include_router(auth_router, prefix="/api")
    app.include_router(sessions_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")

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
    email: str,
    password: str = PASS,
    user_id: str,
    org_id: str,
    member_role: str,
) -> tuple[User, str, str]:
    async with session_factory() as session:
        org = Organization(
            id=org_id,
            business_name="Acme",
            business_email="acme@example.com",
        )
        user = User(
            id=user_id,
            email=email,
            name=email.split("@")[0],
            hashed_password=hash_password(password),
            role="operator",
            org_id=org_id,
            is_active=True,
        )
        session.add(org)
        session.add(user)
        session.add(
            OrganizationMember(
                organization_id=org_id,
                user_id=user_id,
                role=member_role,
            )
        )
        await session.commit()
    return user, org_id, member_role


async def _auth_headers(
    session_factory,
    user: User,
    org_id: str,
    org_role: str,
    *,
    session_id: str | None = None,
) -> dict[str, str]:
    if session_id is None:
        async with session_factory() as session:
            _raw, session_id = await issue_refresh_token(session, user.id)
            await session.commit()
    token, _exp, _jti = issue_access_token(
        user_id=user.id,
        org_id=org_id,
        roles=[org_role, user.role],
        session_id=session_id,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_list_sessions_marks_current(session_factory):
    app = _build_app(session_factory)
    user, org_id, role = await _seed_user(
        session_factory,
        email="alice@acme.example",
        user_id="u-alice",
        org_id="org-acme",
        member_role="member",
    )
    async with session_factory() as session:
        _r1, sid1 = await issue_refresh_token(session, user.id, user_agent="Chrome")
        _r2, sid2 = await issue_refresh_token(session, user.id, user_agent="Safari")
        await session.commit()

    headers = await _auth_headers(session_factory, user, org_id, role, session_id=sid1)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/me/sessions", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["sessions"]) == 2
    current = [s for s in body["sessions"] if s["is_current"]]
    assert len(current) == 1
    assert current[0]["session_id"] == sid1


@pytest.mark.asyncio
async def test_revoke_other_session(session_factory):
    app = _build_app(session_factory)
    user, org_id, role = await _seed_user(
        session_factory,
        email="alice@acme.example",
        user_id="u-alice",
        org_id="org-acme",
        member_role="member",
    )
    async with session_factory() as session:
        _r1, sid1 = await issue_refresh_token(session, user.id)
        _r2, sid2 = await issue_refresh_token(session, user.id)
        await session.commit()

    headers = await _auth_headers(session_factory, user, org_id, role, session_id=sid1)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete(f"/api/me/sessions/{sid2}", headers=headers)
        assert resp.status_code == 204
        still = await client.get("/api/me/sessions", headers=headers)
        ids = {s["session_id"] for s in still.json()["sessions"]}
        assert sid1 in ids
        assert sid2 not in ids


@pytest.mark.asyncio
async def test_member_forbidden_on_admin_members(session_factory):
    app = _build_app(session_factory)
    user, org_id, role = await _seed_user(
        session_factory,
        email="carol@acme.example",
        user_id="u-carol",
        org_id="org-acme",
        member_role="member",
    )
    headers = await _auth_headers(session_factory, user, org_id, role)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/members", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "FORBIDDEN_ROLE"


@pytest.mark.asyncio
async def test_owner_admin_members_success(session_factory):
    app = _build_app(session_factory)
    user, org_id, role = await _seed_user(
        session_factory,
        email="bob@acme.example",
        user_id="u-bob",
        org_id="org-acme",
        member_role="owner",
    )
    headers = await _auth_headers(session_factory, user, org_id, role)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/members", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


def test_db_health_debounce_enter_and_exit():
    monitor = DbHealthMonitor(debounce_count=3)
    monitor.mark_connected()
    for _ in range(2):
        monitor._record_failure()
    assert monitor.safe_mode is False
    monitor._record_failure()
    assert monitor.safe_mode is True
    for _ in range(2):
        monitor._record_success()
    assert monitor.safe_mode is True
    monitor._record_success()
    assert monitor.safe_mode is False


@pytest.mark.asyncio
async def test_idle_sessions_revoked(session_factory):
    async with session_factory() as session:
        user = User(
            id="u-idle",
            email="idle@acme.example",
            name="idle",
            hashed_password=hash_password(PASS),
            role="operator",
            is_active=True,
        )
        session.add(user)
        await session.flush()
        _raw, sid = await issue_refresh_token(session, user.id)
        from sqlalchemy import select
        from db.models.refresh_token import RefreshToken

        row = (await session.execute(select(RefreshToken).where(RefreshToken.id == sid))).scalar_one()
        row.last_used_at = datetime.now(timezone.utc) - timedelta(days=31)
        await session.commit()

    async with session_factory() as session:
        revoked = await revoke_idle_sessions(session)
        await session.commit()
    assert sid in revoked


@pytest.mark.asyncio
async def test_db_safe_mode_middleware_blocks_crud(session_factory):
    from web.db_safe_mode import DbSafeModeMiddleware

    app = FastAPI()

    @app.get("/api/devices")
    async def devices():
        return {"ok": True}

    @app.get("/api/server/status")
    async def status():
        return {"safe_mode": True}

    monitor = DbHealthMonitor()
    monitor.mark_disconnected()
    app.state.db_health = monitor
    app.add_middleware(DbSafeModeMiddleware)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        blocked = await client.get("/api/devices")
        allowed = await client.get("/api/server/status")
    assert blocked.status_code == 503
    assert blocked.json()["code"] == "SERVICE_DEGRADED"
    assert allowed.status_code == 200
