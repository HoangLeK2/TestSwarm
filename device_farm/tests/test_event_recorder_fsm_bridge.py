"""Runtime lifecycle events keep dispatch FSM snapshots fresh."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from db.crud.device import create_device
from db.models import Organization, User
from db.models.device_event import DeviceEvent
from db.models.enums import DeviceFsmEvent, DeviceFsmState
from runtime.core.event_recorder import EventRecorder
from services.device_state.service import DeviceStateService
from tenancy.context import set_current_org_id, tenant_context

USER_ID = "user-event-recorder-fsm"
ORG_ID = "org-event-recorder-fsm"


@pytest_asyncio.fixture
async def event_recorder_seed(tenancy_session_factory):
    now = datetime.now(timezone.utc)
    async with tenancy_session_factory() as db:
        db.add(
            Organization(
                id=ORG_ID,
                business_name="Event Recorder FSM Org",
                business_email="event-recorder-fsm@org.local",
                status="active",
                plan="standard",
                created_at=now,
            )
        )
        db.add(
            User(
                id=USER_ID,
                email="event-recorder-fsm@test.local",
                name="Event Recorder FSM Tester",
                hashed_password="hashed",
                org_id=ORG_ID,
            )
        )
        await db.commit()
    set_current_org_id(ORG_ID)


@pytest.mark.asyncio
async def test_connected_event_promotes_unknown_device_fsm_to_online(
    tenancy_session_factory, event_recorder_seed, monkeypatch
):
    monkeypatch.setattr("db.database.AsyncSessionLocal", tenancy_session_factory)
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        with tenant_context(ORG_ID):
            dev = await create_device(
                db,
                serial="runtime-ready-001",
                user_id=USER_ID,
                org_id=ORG_ID,
            )
            await db.commit()

    recorder = EventRecorder(db_enabled=True)
    await recorder._write_db(
        {
            "id": "runtime-ready-event-001",
            "serial": "runtime-ready-001",
            "event": "connected",
            "reason": None,
            "old_state": "CONNECTING",
            "new_state": "READY",
            "device_model": "Pixel",
            "device_brand": "Google",
            "extra_data": None,
        }
    )

    async with tenancy_session_factory() as db:
        assert await svc.get_state(db, dev.id) == DeviceFsmState.ONLINE
        persisted = (
            await db.execute(
                select(DeviceEvent).where(DeviceEvent.id == "runtime-ready-event-001")
            )
        ).scalar_one()
        assert persisted.event == "connected"


@pytest.mark.asyncio
async def test_connected_event_does_not_release_busy_device(
    tenancy_session_factory, event_recorder_seed, monkeypatch
):
    monkeypatch.setattr("db.database.AsyncSessionLocal", tenancy_session_factory)
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        with tenant_context(ORG_ID):
            dev = await create_device(
                db,
                serial="runtime-ready-busy",
                user_id=USER_ID,
                org_id=ORG_ID,
            )
            await svc.apply_event(
                db,
                dev.id,
                event=DeviceFsmEvent.ATTACHED.value,
                source="agent",
                event_id="busy-attached",
            )
            await svc.apply_event(
                db,
                dev.id,
                event=DeviceFsmEvent.ONLINE.value,
                source="agent",
                event_id="busy-online",
            )
            await svc.claim(db, dev.id, "exec-runtime-busy", event_id="busy-claim")
            await db.commit()

    recorder = EventRecorder(db_enabled=True)
    await recorder._write_db(
        {
            "id": "runtime-ready-event-busy",
            "serial": "runtime-ready-busy",
            "event": "connected",
            "reason": None,
            "old_state": "CONNECTING",
            "new_state": "READY",
            "device_model": None,
            "device_brand": None,
            "extra_data": None,
        }
    )

    async with tenancy_session_factory() as db:
        assert await svc.get_state(db, dev.id) == DeviceFsmState.BUSY
