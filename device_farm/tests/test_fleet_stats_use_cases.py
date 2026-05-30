"""DF-T-02-013 — Fleet stats use-case integration tests."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.crud.fleet_stats import query_fleet_stats
from db.crud.mcp_session import create_mcp_session, end_mcp_session
from db.database import Base
from db.models.device import Device
from db.models.device_fsm import DeviceFsmSnapshot
from db.models.device_group import DeviceGroup, DeviceGroupMember
from db.models.enums import DeviceFsmState
from db.models.relay_agent import RelayAgent
from services.fleet_stats import derive_session_owner_type
from tenancy.context import set_current_org_id
from tests.test_fleet_stats import (
    NOW,
    ORG_ID,
    USER_ID,
    _build_app,
    _seed_base,
    _seed_devices_with_states,
    _seed_sessions,
)


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


def _assert_fsm_invariant(body: dict) -> None:
    devices = body["devices"]
    bucket_sum = sum(
        devices[key]
        for key in (
            "unknown",
            "connecting",
            "online",
            "busy",
            "reconnecting",
            "dead",
        )
    )
    assert bucket_sum == devices["total"]


@pytest.mark.asyncio
async def test_uc_b1_operator_empty_org_sees_zero_totals(session_factory):
    """UC-B1: New org with no devices returns zeroed aggregates."""
    await _seed_base(session_factory)
    app = _build_app(session_factory, user_id=USER_ID, org_id=ORG_ID, org_role="owner")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/devices/fleet/stats")

    assert resp.status_code == 200
    body = resp.json()
    assert body["devices"]["total"] == 0
    assert body["active_sessions"]["total"] == 0
    _assert_fsm_invariant(body)


@pytest.mark.asyncio
async def test_uc_b2_campaign_execution_session_counted(session_factory):
    """UC-B2: Active execution session (exec: prefix) appears in fleet stats."""
    await _seed_base(session_factory)
    async with session_factory() as db:
        db.add(
            Device(
                id="dev-exec",
                serial="SER-EXEC",
                name="exec-device",
                user_id=USER_ID,
                org_id=ORG_ID,
                created_at=NOW,
            )
        )
        db.add(
            DeviceFsmSnapshot(
                device_id="dev-exec",
                state=DeviceFsmState.ONLINE.value,
                updated_at=NOW,
            )
        )
        await create_mcp_session(db, "exec:run-42", "SER-EXEC", None)
        await db.commit()

    app = _build_app(session_factory, user_id=USER_ID, org_id=ORG_ID, org_role="owner")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/devices/fleet/stats")

    assert resp.status_code == 200
    body = resp.json()
    assert body["active_sessions"]["execution"] == 1
    assert body["active_sessions"]["total"] == 1
    _assert_fsm_invariant(body)


@pytest.mark.asyncio
async def test_uc_b3_user_session_counted(session_factory):
    """UC-B3: Operator MCP session with user_id counts as user owner."""
    await _seed_base(session_factory)
    async with session_factory() as db:
        db.add(
            Device(
                id="dev-user",
                serial="SER-USER",
                name="user-device",
                user_id=USER_ID,
                org_id=ORG_ID,
                created_at=NOW,
            )
        )
        db.add(
            DeviceFsmSnapshot(
                device_id="dev-user",
                state=DeviceFsmState.BUSY.value,
                updated_at=NOW,
                session_id="mcp-user-live",
            )
        )
        await create_mcp_session(db, "mcp-user-live", "SER-USER", USER_ID)
        await db.commit()

    app = _build_app(session_factory, user_id=USER_ID, org_id=ORG_ID, org_role="owner")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/devices/fleet/stats")

    body = resp.json()
    assert body["active_sessions"]["user"] == 1
    assert derive_session_owner_type(session_id="mcp-user-live", user_id=USER_ID).value == "user"


@pytest.mark.asyncio
async def test_uc_b4_ended_session_excluded_from_active_totals(session_factory):
    """UC-B4: Ended MCP session is not counted as active."""
    await _seed_base(session_factory)
    async with session_factory() as db:
        db.add(
            Device(
                id="dev-ended",
                serial="SER-END",
                name="ended",
                user_id=USER_ID,
                org_id=ORG_ID,
                created_at=NOW,
            )
        )
        db.add(
            DeviceFsmSnapshot(
                device_id="dev-ended",
                state=DeviceFsmState.ONLINE.value,
                updated_at=NOW,
            )
        )
        await create_mcp_session(db, "mcp-ended-1", "SER-END", USER_ID)
        await end_mcp_session(db, "mcp-ended-1")
        await db.commit()

    app = _build_app(session_factory, user_id=USER_ID, org_id=ORG_ID, org_role="owner")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/devices/fleet/stats")

    body = resp.json()
    assert body["active_sessions"]["total"] == 0


@pytest.mark.asyncio
async def test_uc_b5_group_filter_scopes_sessions_and_devices(session_factory):
    """UC-B5: group_id filter limits both device FSM and active sessions."""
    await _seed_base(session_factory)
    await _seed_devices_with_states(session_factory)
    await _seed_sessions(session_factory)

    async with session_factory() as db:
        group = DeviceGroup(name="Online only", user_id=USER_ID, org_id=ORG_ID)
        db.add(group)
        await db.flush()
        db.add(
            DeviceGroupMember(
                id="dgm-online",
                group_id=group.id,
                device_id="dev-online",
                org_id=ORG_ID,
            )
        )
        await db.commit()
        group_id = group.id

    app = _build_app(session_factory, user_id=USER_ID, org_id=ORG_ID, org_role="owner")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/devices/fleet/stats", params={"group_id": group_id})

    body = resp.json()
    assert body["devices"]["total"] == 1
    assert body["devices"]["online"] == 1
    assert body["active_sessions"]["user"] == 1
    assert body["active_sessions"]["execution"] == 0
    assert body["active_sessions"]["campaign"] == 0


@pytest.mark.asyncio
async def test_uc_b6_relay_filter_excludes_off_relay_devices(session_factory):
    """UC-B6: relay_host filter only counts serials registered on that relay."""
    await _seed_base(session_factory)
    await _seed_devices_with_states(session_factory)

    async with session_factory() as db:
        db.add(
            RelayAgent(
                id="relay-uc6",
                relay_id="relay-uc6-id",
                hostname="relay-uc6.local",
                ip="10.0.0.9",
                serials=["SER-ON"],
                org_id=ORG_ID,
                user_id=USER_ID,
                connected_at=NOW,
                created_at=NOW,
            )
        )
        await db.commit()

    app = _build_app(session_factory, user_id=USER_ID, org_id=ORG_ID, org_role="owner")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/devices/fleet/stats",
            params={"relay_host": "relay-uc6.local"},
        )

    body = resp.json()
    assert body["devices"]["total"] == 1
    assert body["devices"]["online"] == 1
    assert body["filters"]["relay_host"] == "relay-uc6.local"


@pytest.mark.asyncio
async def test_uc_b7_device_without_fsm_snapshot_counts_as_unknown(session_factory):
    """UC-B7: Device row without device_states snapshot is aggregated as unknown."""
    await _seed_base(session_factory)
    async with session_factory() as db:
        db.add(
            Device(
                id="dev-no-fsm",
                serial="SER-NO-FSM",
                name="no-fsm",
                user_id=USER_ID,
                org_id=ORG_ID,
                created_at=NOW,
            )
        )
        await db.commit()

    set_current_org_id(ORG_ID)
    async with session_factory() as db:
        stats = await query_fleet_stats(db, org_id=ORG_ID)

    assert stats.device_total == 1
    assert stats.devices_by_state["unknown"] == 1


@pytest.mark.asyncio
async def test_uc_b8_manage_caller_sees_owner_mismatch_anomaly(session_factory):
    """UC-B8: devices:manage caller sees session/device owner mismatch."""
    await _seed_base(session_factory)
    other_user = "user-other-in-org"
    async with session_factory() as db:
        from db.models import User

        db.add(
            User(
                id=other_user,
                email="other-in-org@local",
                name="Other",
                hashed_password="hashed",
                org_id=ORG_ID,
            )
        )
        db.add(
            Device(
                id="dev-mismatch",
                serial="SER-MISMATCH",
                name="mismatch",
                user_id=USER_ID,
                org_id=ORG_ID,
                created_at=NOW,
            )
        )
        db.add(
            DeviceFsmSnapshot(
                device_id="dev-mismatch",
                state=DeviceFsmState.ONLINE.value,
                updated_at=NOW,
            )
        )
        await create_mcp_session(db, "mcp-mismatch", "SER-MISMATCH", other_user)
        await db.commit()

    app = _build_app(session_factory, user_id=USER_ID, org_id=ORG_ID, org_role="owner")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/devices/fleet/stats")

    body = resp.json()
    reasons = {item["reason"] for item in body["owner_anomalies"]}
    assert "session_owner_differs_from_device_owner" in reasons


@pytest.mark.asyncio
async def test_uc_b9_busy_ghost_claim_counted_without_duplicate_mcp_row(session_factory):
    """UC-B9: BUSY FSM claim without active MCP row still counts owner bucket once."""
    await _seed_base(session_factory)
    async with session_factory() as db:
        db.add(
            Device(
                id="dev-ghost",
                serial="SER-GHOST",
                name="ghost",
                user_id=USER_ID,
                org_id=ORG_ID,
                created_at=NOW,
            )
        )
        db.add(
            DeviceFsmSnapshot(
                device_id="dev-ghost",
                state=DeviceFsmState.BUSY.value,
                updated_at=NOW,
                session_id="ghost-unknown-claim",
            )
        )
        await db.commit()

    app = _build_app(session_factory, user_id=USER_ID, org_id=ORG_ID, org_role="owner")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/devices/fleet/stats")

    body = resp.json()
    assert body["active_sessions"]["unknown"] == 1
    assert body["active_sessions"]["total"] == 1
    ghost = [
        a
        for a in body["owner_anomalies"]
        if a["session_id"] == "ghost-unknown-claim"
    ]
    assert len(ghost) == 1
    assert ghost[0]["reason"] == "busy_device_without_active_mcp_session"
