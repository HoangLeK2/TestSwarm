from __future__ import annotations

"""Test DLQ list scoped by campaign_id (the user-reported "merge" bug)."""

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.crud.execution_dlq import create_dlq_entry, list_dlq_entries_for_user
from db.database import Base
from db.models.execution import Execution


@pytest_asyncio.fixture
async def session():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Sf = async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession)
    async with Sf() as s:
        yield s
    await eng.dispose()


async def _seed_execution(s: AsyncSession, exec_id: str, campaign_id: str, user_id: str = "u1"):
    s.add(
        Execution(
            id=exec_id,
            run_type="campaign_run",
            status="failed",
            campaign_id=campaign_id,
            user_id=user_id,
            created_at=datetime.now(timezone.utc),
        )
    )
    await s.flush()


@pytest.mark.asyncio
async def test_campaign_id_filter_isolates_dlq_per_campaign(session):
    await _seed_execution(session, "exec-A", "camp-A")
    await _seed_execution(session, "exec-B", "camp-B")
    await create_dlq_entry(session, execution_id="exec-A", device_serial="d1", error="boom A")
    await create_dlq_entry(session, execution_id="exec-B", device_serial="d2", error="boom B")
    await session.commit()

    a = await list_dlq_entries_for_user(session, user_id="u1", campaign_id="camp-A")
    assert {e.execution_id for e in a} == {"exec-A"}

    b = await list_dlq_entries_for_user(session, user_id="u1", campaign_id="camp-B")
    assert {e.execution_id for e in b} == {"exec-B"}

    all_ = await list_dlq_entries_for_user(session, user_id="u1")
    assert {e.execution_id for e in all_} == {"exec-A", "exec-B"}


@pytest.mark.asyncio
async def test_campaign_id_filter_with_status(session):
    await _seed_execution(session, "exec-X", "camp-X")
    await _seed_execution(session, "exec-Y", "camp-Y")
    await create_dlq_entry(session, execution_id="exec-X", device_serial="d1")
    await create_dlq_entry(session, execution_id="exec-Y", device_serial="d2")
    await session.commit()

    pending_x = await list_dlq_entries_for_user(
        session, user_id="u1", campaign_id="camp-X", status="pending"
    )
    assert {e.execution_id for e in pending_x} == {"exec-X"}


@pytest.mark.asyncio
async def test_campaign_id_filter_other_user_excluded(session):
    await _seed_execution(session, "exec-mine", "camp-shared", user_id="u1")
    await _seed_execution(session, "exec-theirs", "camp-shared", user_id="u2")
    await create_dlq_entry(session, execution_id="exec-mine", device_serial="d1")
    await create_dlq_entry(session, execution_id="exec-theirs", device_serial="d2")
    await session.commit()

    mine = await list_dlq_entries_for_user(session, user_id="u1", campaign_id="camp-shared")
    assert {e.execution_id for e in mine} == {"exec-mine"}
