"""Relay transport → device FSM bridge (DF-T-02-002)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio

from db.crud.device import create_device
from db.models import Organization, User
from db.models.enums import DeviceFsmEvent, DeviceFsmState
from services.device_state.relay_bridge import (
    apply_relay_offline,
    apply_relay_online,
    resolve_device_id_for_relay,
)
from services.device_state.service import DeviceStateService
from tenancy.context import set_current_org_id, tenant_context

USER_ID = "user-relay-bridge"
ORG_ID = "org-relay-bridge"


@pytest_asyncio.fixture
async def relay_bridge_seed(tenancy_session_factory):
    now = datetime.now(timezone.utc)
    async with tenancy_session_factory() as db:
        db.add(
            Organization(
                id=ORG_ID,
                business_name="Relay Bridge Org",
                business_email="rb@org.local",
                status="active",
                plan="standard",
                created_at=now,
            )
        )
        db.add(
            User(
                id=USER_ID,
                email="rb@test.local",
                name="RB Tester",
                hashed_password="hashed",
                org_id=ORG_ID,
            )
        )
        await db.commit()
    set_current_org_id(ORG_ID)


@pytest.mark.asyncio
async def test_resolve_device_by_hardware_and_adb_serial(
    tenancy_session_factory, relay_bridge_seed
):
    async with tenancy_session_factory() as db:
        with tenant_context(ORG_ID):
            dev = await create_device(
                db,
                serial="10AE7S00HD002JK",
                user_id=USER_ID,
                org_id=ORG_ID,
            )
            dev.adb_serial = "10AE7S00HD002JK"
            dev.adb_ip = "172.16.0.83"
            await db.commit()

        assert (
            await resolve_device_id_for_relay(db, "10AE7S00HD002JK")
        ) == dev.id
        assert (
            await resolve_device_id_for_relay(db, "172.16.0.83:44601")
        ) == dev.id
        assert (
            await resolve_device_id_for_relay(
                db, "172.16.0.83:44601", hardware_serial="10AE7S00HD002JK"
            )
        ) == dev.id


@pytest.mark.asyncio
async def test_apply_relay_online_unknown_to_online(
    tenancy_session_factory, relay_bridge_seed
):
    async with tenancy_session_factory() as db:
        with tenant_context(ORG_ID):
            dev = await create_device(
                db,
                serial="10AE7S00HD002JK",
                user_id=USER_ID,
                org_id=ORG_ID,
            )
            dev.adb_serial = "10AE7S00HD002JK"
            await db.commit()

    async with tenancy_session_factory() as db:
        with tenant_context(ORG_ID):
            ok = await apply_relay_online("10AE7S00HD002JK", db=db)
            await db.commit()
    assert ok is True

    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        assert await svc.get_state(db, dev.id) == DeviceFsmState.ONLINE


@pytest.mark.asyncio
async def test_apply_relay_online_idempotent_when_already_online(
    tenancy_session_factory, relay_bridge_seed
):
    async with tenancy_session_factory() as db:
        with tenant_context(ORG_ID):
            dev = await create_device(
                db,
                serial="dev-online",
                user_id=USER_ID,
                org_id=ORG_ID,
            )
            await db.commit()

    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        await svc.apply_event(
            db,
            dev.id,
            event=DeviceFsmEvent.ATTACHED.value,
            source="agent",
            event_id="seed-a",
        )
        await svc.apply_event(
            db,
            dev.id,
            event=DeviceFsmEvent.ONLINE.value,
            source="agent",
            event_id="seed-o",
        )
        await db.commit()

    async with tenancy_session_factory() as db:
        with tenant_context(ORG_ID):
            ok = await apply_relay_online("dev-online", db=db)
            await db.commit()
    assert ok is True
    async with tenancy_session_factory() as db:
        assert await svc.get_state(db, dev.id) == DeviceFsmState.ONLINE


@pytest.mark.asyncio
async def test_apply_relay_offline_marks_reconnecting(
    tenancy_session_factory, relay_bridge_seed
):
    async with tenancy_session_factory() as db:
        with tenant_context(ORG_ID):
            dev = await create_device(
                db,
                serial="dev-drop",
                user_id=USER_ID,
                org_id=ORG_ID,
            )
            await db.commit()

    async with tenancy_session_factory() as db:
        with tenant_context(ORG_ID):
            ok1 = await apply_relay_online("dev-drop", db=db)
            await db.commit()
    assert ok1 is True
    async with tenancy_session_factory() as db:
        with tenant_context(ORG_ID):
            ok2 = await apply_relay_offline("dev-drop", db=db)
            await db.commit()
    assert ok2 is True

    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        assert await svc.get_state(db, dev.id) == DeviceFsmState.RECONNECTING
