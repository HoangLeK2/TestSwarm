from __future__ import annotations

"""Test DLQ list scoped by campaign_id (the user-reported "merge" bug)."""

import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.crud.execution_dlq import (
    create_dlq_entry,
    list_dlq_entries_for_user,
)
from db.database import Base
from db.models.device import Device
from db.models.execution import Execution
from services.dlq_maintenance import (
    dismiss_stale_offline_dlq_all_users,
    dismiss_stale_offline_dlq_entries_for_user,
)


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


@pytest.mark.asyncio
async def test_stale_offline_device_dlq_entries_are_auto_dismissed(session):
    old_seen = datetime.now(timezone.utc) - timedelta(minutes=30)
    recent_seen = datetime.now(timezone.utc) - timedelta(minutes=1)
    session.add_all(
        [
            Device(
                id="dev-old",
                serial="serial-old",
                user_id="u1",
                org_id="org-1",
                last_seen=old_seen,
            ),
            Device(
                id="dev-new",
                serial="serial-new",
                user_id="u1",
                org_id="org-1",
                last_seen=recent_seen,
            ),
        ]
    )
    await _seed_execution(session, "exec-old", "camp-A")
    await _seed_execution(session, "exec-new", "camp-A")
    await create_dlq_entry(
        session,
        execution_id="exec-old",
        device_serial="serial-old",
        error="stop_app: no adb relay or u2 for serial=serial-old",
    )
    await create_dlq_entry(
        session,
        execution_id="exec-new",
        device_serial="serial-new",
        error="stop_app: no adb relay or u2 for serial=serial-new",
    )
    await session.commit()

    dismissed = await dismiss_stale_offline_dlq_entries_for_user(
        session,
        user_id="u1",
        offline_after_minutes=5,
        campaign_id="camp-A",
    )
    await session.commit()

    assert dismissed == 1
    pending = await list_dlq_entries_for_user(
        session,
        user_id="u1",
        campaign_id="camp-A",
        status="pending",
    )
    assert {entry.device_serial for entry in pending} == {"serial-new"}

    dismissed_entries = await list_dlq_entries_for_user(
        session,
        user_id="u1",
        campaign_id="camp-A",
        status="dismissed",
    )
    assert {entry.device_serial for entry in dismissed_entries} == {"serial-old"}


@pytest.mark.asyncio
async def test_stale_offline_dlq_auto_dismiss_runs_for_all_users_with_pending(session):
    old_seen = datetime.now(timezone.utc) - timedelta(minutes=30)
    session.add_all(
        [
            Device(
                id="dev-u1",
                serial="serial-u1",
                user_id="u1",
                org_id="org-1",
                last_seen=old_seen,
            ),
            Device(
                id="dev-u2",
                serial="serial-u2",
                user_id="u2",
                org_id="org-2",
                last_seen=old_seen,
            ),
        ]
    )
    await _seed_execution(session, "exec-u1", "camp-1", user_id="u1")
    await _seed_execution(session, "exec-u2", "camp-2", user_id="u2")
    await create_dlq_entry(
        session,
        execution_id="exec-u1",
        device_serial="serial-u1",
        error="offline",
    )
    await create_dlq_entry(
        session,
        execution_id="exec-u2",
        device_serial="serial-u2",
        error="offline",
    )
    await session.commit()

    dismissed = await dismiss_stale_offline_dlq_all_users(
        session,
        offline_after_minutes=5,
    )
    assert dismissed == 2
    pending_u1 = await list_dlq_entries_for_user(session, user_id="u1", status="pending")
    pending_u2 = await list_dlq_entries_for_user(session, user_id="u2", status="pending")
    assert pending_u1 == []
    assert pending_u2 == []
