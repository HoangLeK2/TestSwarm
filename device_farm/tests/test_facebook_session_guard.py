from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.database import Base
from services.device_platform_session import mark_active, mark_login_required
from services.facebook_session_guard import FacebookSessionGuardOutcome, guard_facebook_session
from tenancy.context import use_tenant_scope


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_guard_allows_active_fresh_session(session_factory, monkeypatch):
    monkeypatch.setenv("FACEBOOK_SESSION_GUARD_MODE", "enforce")
    async with session_factory() as db:
        with use_tenant_scope("org-1"):
            await mark_active(
                db,
                org_id="org-1",
                device_id="device-1",
                account_id="account-1",
                establishment_method="operator_confirmed",
                reason="test",
            )

            decision = await guard_facebook_session(
                db,
                org_id="org-1",
                device_id="device-1",
                account_id="account-1",
            )

    assert decision.outcome == FacebookSessionGuardOutcome.ALLOW
    assert decision.reason == "facebook_session_ready_cache"


@pytest.mark.asyncio
async def test_guard_blocks_login_required_only_in_enforce(session_factory, monkeypatch):
    async with session_factory() as db:
        with use_tenant_scope("org-1"):
            await mark_login_required(
                db,
                org_id="org-1",
                device_id="device-1",
                reason="primary_changed",
                expected_account_id="account-1",
            )

            monkeypatch.setenv("FACEBOOK_SESSION_GUARD_MODE", "shadow")
            shadow = await guard_facebook_session(
                db,
                org_id="org-1",
                device_id="device-1",
                account_id="account-1",
            )
            monkeypatch.setenv("FACEBOOK_SESSION_GUARD_MODE", "enforce")
            enforce = await guard_facebook_session(
                db,
                org_id="org-1",
                device_id="device-1",
                account_id="account-1",
            )

    assert shadow.outcome == FacebookSessionGuardOutcome.SHADOW_BLOCK
    assert shadow.blocks_execution is False
    assert enforce.outcome == FacebookSessionGuardOutcome.BLOCK
    assert enforce.blocks_execution is True


@pytest.mark.asyncio
async def test_guard_detects_account_mismatch(session_factory, monkeypatch):
    monkeypatch.setenv("FACEBOOK_SESSION_GUARD_MODE", "enforce")
    async with session_factory() as db:
        with use_tenant_scope("org-1"):
            await mark_active(
                db,
                org_id="org-1",
                device_id="device-1",
                account_id="account-1",
                establishment_method="operator_confirmed",
                reason="test",
            )

            decision = await guard_facebook_session(
                db,
                org_id="org-1",
                device_id="device-1",
                account_id="account-2",
            )

    assert decision.outcome == FacebookSessionGuardOutcome.BLOCK
    assert decision.reason == "facebook_session_account_mismatch"
