"""Epic 01 Phase 3: rate limit, JWT kid rotation, logging redaction."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.deps import _get_db
from api.routes.auth import router as auth_router
from auth.jwt_service import issue_access_token
from auth.secret_versioning import JwtKeyRevokedError, reload_jwt_secrets, verify_material_for_kid
from core.security import clear_jwt_cache, jwt_algorithm
from db.database import Base
from observability.logging import redact_value
from rate_limit.budget import parse_budget
from rate_limit.counters import reset as reset_rate_counters
from rate_limit.counters import snapshot as rate_counters
from rate_limit.store import InMemoryRateLimitStore, clear_memory_store


@pytest.fixture(autouse=True)
def _rate_limit_memory(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_USE_MEMORY", "1")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "1")
    clear_memory_store()
    reset_rate_counters()
    yield
    clear_memory_store()
    reset_rate_counters()


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


def test_parse_budget_minute():
    budget = parse_budget("30/min")
    assert budget.limit == 30
    assert budget.window_seconds == 60


def test_parse_budget_hour():
    budget = parse_budget("10/hour")
    assert budget.limit == 10
    assert budget.window_seconds == 3600


@pytest.mark.asyncio
async def test_login_rate_limit_blocks_after_budget(session_factory, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret-phase3")
    clear_jwt_cache()
    app = _build_auth_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(30):
            resp = await client.post(
                "/api/auth/login",
                json={"email": "missing@example.com", "password": "wrong"},
            )
            assert resp.status_code in {401, 403, 423}
        blocked = await client.post(
            "/api/auth/login",
            json={"email": "missing@example.com", "password": "wrong"},
        )
    assert blocked.status_code == 429
    assert blocked.json()["detail"]["code"] == "TOO_MANY_REQUESTS"
    assert blocked.headers.get("Retry-After")
    assert rate_counters()["rate_limit.rejected.count"] >= 1


def test_jwt_issue_includes_kid(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "kid-secret-v1")
    monkeypatch.setenv("JWT_ACTIVE_KID", "v1")
    clear_jwt_cache()
    reload_jwt_secrets()
    token, _exp, _jti = issue_access_token(
        user_id="u1",
        org_id="org1",
        roles=["member"],
    )
    header = jwt.get_unverified_header(token)
    assert header.get("kid") == "v1"


def test_jwt_previous_kid_revoked_after_overlap(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "secret-v2")
    monkeypatch.setenv("JWT_ACTIVE_KID", "v2")
    monkeypatch.setenv("JWT_SECRET_PREVIOUS", "secret-v1")
    monkeypatch.setenv("JWT_SECRET_PREVIOUS_KID", "v1")
    monkeypatch.setenv(
        "JWT_SECRET_PREVIOUS_ROTATED_AT",
        str((datetime.now(timezone.utc) - timedelta(hours=25)).timestamp()),
    )
    monkeypatch.setenv("JWT_SECRET_OVERLAP_HOURS", "24")
    clear_jwt_cache()
    reload_jwt_secrets()
    with pytest.raises(JwtKeyRevokedError):
        verify_material_for_kid("v1")


def test_log_redaction_masks_authorization():
    out = redact_value({"Authorization": "Bearer abc123", "route": "/api/auth/login"})
    assert out["Authorization"] == "<REDACTED>"
    assert out["route"] == "/api/auth/login"


@pytest.mark.asyncio
async def test_in_memory_rate_limit_store_window():
    store = InMemoryRateLimitStore()
    first = await store.consume("ip:1.2.3.4", limit=5, window_seconds=60)
    assert first.allowed is True
    assert first.remaining == 4
    for _ in range(4):
        await store.consume("ip:1.2.3.4", limit=5, window_seconds=60)
    blocked = await store.consume("ip:1.2.3.4", limit=5, window_seconds=60)
    assert blocked.allowed is False
    assert blocked.remaining == 0
