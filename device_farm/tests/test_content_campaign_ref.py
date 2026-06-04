from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.database import Base
from db.models.campaign import Campaign
from db.models.execution import Execution
from services.content.campaign_ref import resolve_persist_campaign_id


@pytest_asyncio.fixture
async def session():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as s:
        yield s
    await eng.dispose()


@pytest.mark.asyncio
async def test_resolve_persist_campaign_id_prefers_execution(session):
    now = datetime.now(timezone.utc)
    campaign = Campaign(
        id="camp-1",
        name="Test",
        name_lower="test",
        org_id="org-1",
        user_id="user-1",
        status="idle",
        created_at=now,
        updated_at=now,
    )
    execution = Execution(
        id="exec-1",
        run_type="campaign_device",
        campaign_id="camp-1",
        status="running",
        created_at=now,
    )
    session.add_all([campaign, execution])
    await session.commit()

    resolved = await resolve_persist_campaign_id(
        session,
        campaign_id="stale-from-workflow",
        execution_id="exec-1",
    )
    assert resolved == "camp-1"


@pytest.mark.asyncio
async def test_resolve_persist_campaign_id_drops_execution_orphan_campaign_id(session):
    now = datetime.now(timezone.utc)
    execution = Execution(
        id="exec-orphan",
        run_type="campaign_device",
        campaign_id="deleted-campaign",
        status="running",
        created_at=now,
    )
    session.add(execution)
    await session.commit()

    resolved = await resolve_persist_campaign_id(
        session,
        campaign_id=None,
        execution_id="exec-orphan",
    )
    assert resolved is None


@pytest.mark.asyncio
async def test_resolve_persist_campaign_id_drops_missing_campaign(session):
    now = datetime.now(timezone.utc)
    execution = Execution(
        id="exec-2",
        run_type="campaign_device",
        campaign_id=None,
        status="running",
        created_at=now,
    )
    session.add(execution)
    await session.commit()

    resolved = await resolve_persist_campaign_id(
        session,
        campaign_id="missing-campaign",
        execution_id="exec-2",
    )
    assert resolved is None


@pytest.mark.asyncio
async def test_resolve_persist_campaign_id_returns_none_without_ids(session):
    resolved = await resolve_persist_campaign_id(
        session,
        campaign_id=None,
        execution_id=None,
    )
    assert resolved is None


@pytest.mark.asyncio
async def test_resolve_persist_campaign_id_without_tenant_context(session, monkeypatch):
    """Temporal/content paths must not require request-scoped tenant context."""
    monkeypatch.setenv("TENANCY_STRICT_MODE", "true")
    now = datetime.now(timezone.utc)
    campaign = Campaign(
        id="camp-strict",
        name="Strict",
        name_lower="strict",
        org_id="org-1",
        user_id="user-1",
        status="idle",
        created_at=now,
        updated_at=now,
    )
    execution = Execution(
        id="exec-strict",
        run_type="campaign_device",
        campaign_id="camp-strict",
        status="running",
        created_at=now,
    )
    session.add_all([campaign, execution])
    await session.commit()

    resolved = await resolve_persist_campaign_id(
        session,
        campaign_id="camp-strict",
        execution_id="exec-strict",
    )
    assert resolved == "camp-strict"


@pytest.mark.asyncio
async def test_resolve_persist_campaign_id_preview_never_attaches_campaign(session):
    now = datetime.now(timezone.utc)
    campaign = Campaign(
        id="camp-preview",
        name="Preview Camp",
        name_lower="preview camp",
        org_id="org-1",
        user_id="user-1",
        status="idle",
        created_at=now,
        updated_at=now,
    )
    execution = Execution(
        id="exec-preview",
        run_type="preview",
        kind="preview",
        campaign_id="camp-preview",
        status="running",
        created_at=now,
    )
    session.add_all([campaign, execution])
    await session.commit()

    resolved = await resolve_persist_campaign_id(
        session,
        campaign_id="camp-preview",
        execution_id="exec-preview",
    )
    assert resolved is None
