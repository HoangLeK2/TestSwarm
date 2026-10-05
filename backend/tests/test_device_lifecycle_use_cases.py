"""End-to-end use-case tests: Device FSM + lifecycle WS + fleet stats (DF-T-02-002/013/015)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from db.crud.device import create_device
from db.crud.fleet_stats import query_fleet_stats
from db.models import Organization, User
from db.models.device_fsm import DeviceFsmSnapshot
from db.models.enums import DeviceFsmEvent, DeviceFsmState
from services.device_state.lifecycle_schema import LifecycleEventType
from services.device_state.service import ApplyOutcome, DeviceStateService
from services.device_state.ws_publisher import DeviceLifecyclePublisher, DEBOUNCE_MS
from services.device_state.events import DeviceStateChangedEvent
from tenancy.context import set_current_org_id, tenant_context

USER_ID = "user-lifecycle-uc"
ORG_ID = "org-lifecycle-uc"


@pytest_asyncio.fixture
async def uc_org_seed(tenancy_session_factory):
    now = datetime.now(timezone.utc)
    async with tenancy_session_factory() as db:
        db.add(
            Organization(
                id=ORG_ID,
                business_name="Lifecycle UC Org",
                business_email="uc@org.local",
                status="active",
                plan="standard",
                created_at=now,
            )
        )
        db.add(
            User(
                id=USER_ID,
                email="uc@test.local",
                name="UC Tester",
                hashed_password="hashed",
                org_id=ORG_ID,
            )
        )
        await db.commit()
    set_current_org_id(ORG_ID)


async def _online_device(db, svc: DeviceStateService, serial: str = "uc-001"):
    dev = await create_device(db, serial=serial, user_id=USER_ID, org_id=ORG_ID)
    await svc.apply_event(
        db, dev.id, event=DeviceFsmEvent.ATTACHED.value, source="agent", event_id=f"a-{serial}"
    )
    await svc.apply_event(
        db, dev.id, event=DeviceFsmEvent.ONLINE.value, source="agent", event_id=f"o-{serial}"
    )
    return dev


@pytest.mark.asyncio
async def test_uc_agent_bootstraps_device_to_online(tenancy_session_factory, uc_org_seed):
    """UC-BE-01: Agent attach + online → control plane stores ONLINE."""
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        dev = await _online_device(db, svc)
        await db.commit()

    async with tenancy_session_factory() as db:
        assert await svc.get_state(db, dev.id) == DeviceFsmState.ONLINE
        row = (
            await db.execute(
                select(DeviceFsmSnapshot).where(DeviceFsmSnapshot.device_id == dev.id)
            )
        ).scalar_one()
        assert row.state == DeviceFsmState.ONLINE.value


@pytest.mark.asyncio
async def test_uc_claim_release_updates_fleet_stats(tenancy_session_factory, uc_org_seed):
    """UC-BE-02/03: Claim BUSY then release ONLINE reflected in fleet stats."""
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        dev = await _online_device(db, svc)
        await db.commit()

    async with tenancy_session_factory() as db:
        await svc.claim(db, dev.id, "exec:run-99", event_id="claim-uc")
        await db.commit()

    async with tenancy_session_factory() as db:
        stats = await query_fleet_stats(db, org_id=ORG_ID)
        assert stats.devices_by_state["busy"] == 1
        assert stats.devices_by_state["online"] == 0
        assert stats.active_sessions_by_owner["execution"] == 1

    async with tenancy_session_factory() as db:
        await svc.release(db, dev.id, "exec:run-99", event_id="release-uc")
        await db.commit()

    async with tenancy_session_factory() as db:
        stats = await query_fleet_stats(db, org_id=ORG_ID)
        assert stats.devices_by_state["online"] == 1
        assert stats.devices_by_state["busy"] == 0
        assert stats.active_sessions_by_owner["execution"] == 0


@pytest.mark.asyncio
async def test_uc_reconnecting_marked_dead_clears_session(tenancy_session_factory, uc_org_seed):
    """UC-BE-04: RECONNECTING timeout → DEAD clears held session."""
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        dev = await _online_device(db, svc)
        await svc.claim(db, dev.id, "sess-hold", event_id="c1")
        await svc.apply_event(
            db,
            dev.id,
            event=DeviceFsmEvent.RECONNECTING.value,
            source="agent",
            event_id="r1",
        )
        snap = (
            await db.execute(
                select(DeviceFsmSnapshot).where(DeviceFsmSnapshot.device_id == dev.id)
            )
        ).scalar_one()
        snap.reconnecting_since = datetime.now(timezone.utc) - timedelta(minutes=30)
        await db.commit()

    async with tenancy_session_factory() as db:
        result = await svc.mark_dead_reconnect_timeout(
            db,
            dev.id,
            reason="reconnect_timeout",
            device_serial=dev.serial,
            event_id="dead-uc",
        )
        await db.commit()
        assert result.outcome == ApplyOutcome.APPLIED
        assert result.to_state == DeviceFsmState.DEAD

    async with tenancy_session_factory() as db:
        row = (
            await db.execute(
                select(DeviceFsmSnapshot).where(DeviceFsmSnapshot.device_id == dev.id)
            )
        ).scalar_one()
        assert row.state == DeviceFsmState.DEAD.value
        assert row.session_id is None


@pytest.mark.asyncio
async def test_uc_fsm_claim_emits_session_claimed_lifecycle(tenancy_session_factory, uc_org_seed):
    """UC-BE-05: session.claim FSM event maps to session.claimed on lifecycle WS."""
    from unittest.mock import AsyncMock

    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        dev = await _online_device(db, svc)
        await db.commit()

    ws_manager = AsyncMock()
    publisher = DeviceLifecyclePublisher()
    publisher.bind_ws_manager(ws_manager)
    publisher.set_event_loop(asyncio.get_running_loop())
    publisher._org_device_cache[dev.id] = (ORG_ID, 0.0)

    async with tenancy_session_factory() as db:
        await svc.claim(db, dev.id, "exec:map-test", event_id="claim-map")
        await db.commit()

    await publisher._enqueue_fsm_event(
        DeviceStateChangedEvent(
            device_id=dev.id,
            from_state=DeviceFsmState.ONLINE.value,
            to_state=DeviceFsmState.BUSY.value,
            event=DeviceFsmEvent.SESSION_CLAIM.value,
            source="claim",
            event_id="claim-map",
            session_id="exec:map-test",
        )
    )
    await asyncio.sleep(DEBOUNCE_MS / 1000.0 + 0.05)

    msg = ws_manager.broadcast_to_org.await_args[0][1]
    assert msg["event"]["type"] == LifecycleEventType.SESSION_CLAIMED
    assert msg["event"]["session_id"] == "exec:map-test"


@pytest.mark.asyncio
async def test_uc_snapshot_matches_db_after_transitions(
    tenancy_session_factory, uc_org_seed
):
    """UC-BE-06: Lifecycle snapshot reflects persisted FSM rows."""
    from unittest.mock import patch

    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        dev1 = await _online_device(db, svc, serial="snap-1")
        dev2 = await create_device(db, serial="snap-2", user_id=USER_ID, org_id=ORG_ID)
        await svc.apply_event(
            db,
            dev2.id,
            event=DeviceFsmEvent.ATTACHED.value,
            source="agent",
            event_id="a2",
        )
        await db.commit()

    publisher = DeviceLifecyclePublisher()
    with patch(
        "services.device_state.ws_publisher.AsyncSessionLocal",
        tenancy_session_factory,
    ):
        with tenant_context(ORG_ID):
            snapshot = await publisher.build_snapshot(ORG_ID)

    by_id = {d.device_id: d.state for d in snapshot.devices}
    assert by_id[dev1.id] == DeviceFsmState.ONLINE.value
    assert by_id[dev2.id] == DeviceFsmState.CONNECTING.value


@pytest.mark.asyncio
async def test_uc_duplicate_online_event_is_idempotent(tenancy_session_factory, uc_org_seed):
    """UC-BE-07: Replayed agent ONLINE with same event_id does not duplicate transitions."""
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        dev = await _online_device(db, svc)
        await db.commit()

    async with tenancy_session_factory() as db:
        first = await svc.apply_event(
            db,
            dev.id,
            event=DeviceFsmEvent.ONLINE.value,
            source="agent",
            event_id="dup-online",
        )
        second = await svc.apply_event(
            db,
            dev.id,
            event=DeviceFsmEvent.ONLINE.value,
            source="agent",
            event_id="dup-online",
        )
        await db.commit()
        assert first.outcome == ApplyOutcome.NO_OP
        assert second.outcome == ApplyOutcome.DEDUPED
