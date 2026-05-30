"""DF-T-02-013 — Fleet stats endpoint integration tests."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.crud.router import api_router
from api.deps import _get_current_user, _get_db
from db.crud.fleet_stats import query_fleet_stats
from db.crud.mcp_session import create_mcp_session
from db.database import Base
from db.models import Organization, OrganizationMember, User
from db.models.device import Device
from db.models.device_fsm import DeviceFsmSnapshot
from db.models.device_group import DeviceGroup, DeviceGroupMember
from db.models.enums import DeviceFsmState, McpSessionStatus
from db.models.relay_agent import RelayAgent
from services.fleet_stats import derive_session_owner_type
from tenancy.context import set_current_org_id


ORG_ID = "org-fleet-stats"
USER_ID = "user-fleet-stats"
OTHER_ORG = "org-other"
OTHER_USER = "user-other"
NOW = datetime.now(timezone.utc)


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


def _build_app(session_factory, *, user_id: str, org_id: str, role: str = "operator", org_role: str = "member"):
    app = FastAPI()
    app.include_router(api_router, prefix="/api")

    async def _db_override():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _user_override():
        set_current_org_id(org_id)
        return SimpleNamespace(
            id=user_id,
            email=f"{user_id}@example.com",
            name=user_id,
            role=role,
            org_role=org_role,
            is_active=True,
            org_id=org_id,
        )

    app.dependency_overrides[_get_db] = _db_override
    app.dependency_overrides[_get_current_user] = _user_override
    return app


async def _seed_base(session_factory):
    async with session_factory() as db:
        db.add(
            Organization(
                id=ORG_ID,
                business_name="Fleet Org",
                business_email="fleet@org.local",
                status="active",
                plan="standard",
                created_at=NOW,
            )
        )
        db.add(
            Organization(
                id=OTHER_ORG,
                business_name="Other Org",
                business_email="other@org.local",
                status="active",
                plan="standard",
                created_at=NOW,
            )
        )
        db.add(
            User(
                id=USER_ID,
                email="fleet@org.local",
                name="Fleet User",
                hashed_password="hashed",
                org_id=ORG_ID,
            )
        )
        db.add(
            User(
                id=OTHER_USER,
                email="other@org.local",
                name="Other User",
                hashed_password="hashed",
                org_id=OTHER_ORG,
            )
        )
        await db.flush()
        db.add(
            OrganizationMember(
                id="mem-fleet",
                organization_id=ORG_ID,
                user_id=USER_ID,
                role="owner",
                created_at=NOW,
            )
        )
        await db.commit()


async def _seed_devices_with_states(session_factory):
    states = [
        ("dev-unknown", "SER-UNK", DeviceFsmState.UNKNOWN),
        ("dev-connecting", "SER-CON", DeviceFsmState.CONNECTING),
        ("dev-online", "SER-ON", DeviceFsmState.ONLINE),
        ("dev-busy", "SER-BUSY", DeviceFsmState.BUSY),
        ("dev-reconnecting", "SER-REC", DeviceFsmState.RECONNECTING),
        ("dev-dead", "SER-DEAD", DeviceFsmState.DEAD),
    ]
    async with session_factory() as db:
        for device_id, serial, state in states:
            db.add(
                Device(
                    id=device_id,
                    serial=serial,
                    name=serial,
                    user_id=USER_ID,
                    org_id=ORG_ID,
                    created_at=NOW,
                )
            )
            db.add(
                DeviceFsmSnapshot(
                    device_id=device_id,
                    state=state.value,
                    updated_at=NOW,
                    session_id="sess-busy-1" if state == DeviceFsmState.BUSY else None,
                )
            )
        await db.commit()


async def _seed_sessions(session_factory):
    async with session_factory() as db:
        await create_mcp_session(db, "mcp-user-1", "SER-ON", USER_ID)
        await create_mcp_session(db, "exec:run-1", "SER-CON", None)
        await create_mcp_session(db, "camp:run-1", "SER-REC", None)
        ended = await create_mcp_session(db, "mcp-ended", "SER-DEAD", USER_ID)
        ended.status = McpSessionStatus.ENDED.value
        await db.commit()


def test_derive_session_owner_type_matrix():
    assert derive_session_owner_type(session_id="abc", user_id=USER_ID).value == "user"
    assert derive_session_owner_type(session_id="exec:1", user_id=None).value == "execution"
    assert derive_session_owner_type(session_id="camp:1", user_id=None).value == "campaign"
    assert derive_session_owner_type(session_id="sys:1", user_id=None).value == "system"
    assert derive_session_owner_type(session_id="random", user_id=None).value == "unknown"


@pytest.mark.asyncio
async def test_fleet_stats_success_counts(session_factory):
    await _seed_base(session_factory)
    await _seed_devices_with_states(session_factory)
    await _seed_sessions(session_factory)

    app = _build_app(session_factory, user_id=USER_ID, org_id=ORG_ID, org_role="owner")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/devices/fleet/stats")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["filters"]["organization_id"] == ORG_ID
    assert body["devices"]["total"] == 6
    assert body["devices"]["unknown"] == 1
    assert body["devices"]["connecting"] == 1
    assert body["devices"]["online"] == 1
    assert body["devices"]["busy"] == 1
    assert body["devices"]["reconnecting"] == 1
    assert body["devices"]["dead"] == 1
    assert body["active_sessions"]["user"] >= 1
    assert body["active_sessions"]["execution"] >= 1
    assert body["active_sessions"]["campaign"] >= 1
    assert isinstance(body["owner_anomalies"], list)
    reasons = {item["reason"] for item in body["owner_anomalies"]}
    assert "active_session_missing_owner" not in reasons
    assert "busy_device_without_active_mcp_session" in reasons


@pytest.mark.asyncio
async def test_fleet_stats_member_hides_owner_details(session_factory):
    await _seed_base(session_factory)
    await _seed_devices_with_states(session_factory)
    await _seed_sessions(session_factory)

    app = _build_app(session_factory, user_id=USER_ID, org_id=ORG_ID, org_role="member")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/devices/fleet/stats")

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("owner_anomalies") is None


@pytest.mark.asyncio
async def test_fleet_stats_group_filter(session_factory):
    await _seed_base(session_factory)
    await _seed_devices_with_states(session_factory)

    async with session_factory() as db:
        group = DeviceGroup(name="Edge", user_id=USER_ID, org_id=ORG_ID)
        db.add(group)
        await db.flush()
        db.add(DeviceGroupMember(id="dgm-1", group_id=group.id, device_id="dev-online", org_id=ORG_ID))
        await db.commit()
        group_id = group.id

    app = _build_app(session_factory, user_id=USER_ID, org_id=ORG_ID, org_role="owner")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/devices/fleet/stats", params={"group_id": group_id})

    assert resp.status_code == 200
    body = resp.json()
    assert body["devices"]["total"] == 1
    assert body["devices"]["online"] == 1
    assert body["filters"]["group_id"] == group_id


@pytest.mark.asyncio
async def test_fleet_stats_relay_host_filter(session_factory):
    await _seed_base(session_factory)
    await _seed_devices_with_states(session_factory)

    async with session_factory() as db:
        db.add(
            RelayAgent(
                id="relay-1",
                relay_id="relay-host-1",
                hostname="relay-a.local",
                ip="10.0.0.5",
                serials=["SER-ON", "SER-BUSY"],
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
            params={"relay_host": "relay-a.local"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["devices"]["total"] == 2
    assert body["filters"]["relay_host"] == "relay-a.local"


@pytest.mark.asyncio
async def test_fleet_stats_group_wrong_org_returns_404(session_factory):
    await _seed_base(session_factory)
    await _seed_devices_with_states(session_factory)

    async with session_factory() as db:
        other_group = DeviceGroup(name="Other", user_id=OTHER_USER, org_id=OTHER_ORG)
        db.add(other_group)
        await db.commit()
        other_group_id = other_group.id

    app = _build_app(session_factory, user_id=USER_ID, org_id=ORG_ID, org_role="owner")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/devices/fleet/stats", params={"group_id": other_group_id})

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_fleet_stats_unknown_relay_host_returns_404(session_factory):
    await _seed_base(session_factory)
    await _seed_devices_with_states(session_factory)

    app = _build_app(session_factory, user_id=USER_ID, org_id=ORG_ID, org_role="owner")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/devices/fleet/stats", params={"relay_host": "missing.local"})

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_fleet_stats_empty_relay_host_returns_422(session_factory):
    await _seed_base(session_factory)
    app = _build_app(session_factory, user_id=USER_ID, org_id=ORG_ID, org_role="owner")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/devices/fleet/stats", params={"relay_host": "  "})

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_fleet_stats_read_only_no_side_effects(session_factory):
    await _seed_base(session_factory)
    await _seed_devices_with_states(session_factory)

    async with session_factory() as db:
        set_current_org_id(ORG_ID)
        before_devices = len((await db.execute(select(Device))).scalars().all())

    app = _build_app(session_factory, user_id=USER_ID, org_id=ORG_ID, org_role="owner")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.get("/api/devices/fleet/stats")
        second = await client.get("/api/devices/fleet/stats")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["devices"] == second.json()["devices"]

    async with session_factory() as db:
        set_current_org_id(ORG_ID)
        after_devices = len((await db.execute(select(Device))).scalars().all())
    assert before_devices == after_devices


@pytest.mark.asyncio
async def test_fleet_stats_cross_tenant_isolation(session_factory):
    await _seed_base(session_factory)
    await _seed_devices_with_states(session_factory)
    await _seed_sessions(session_factory)

    async with session_factory() as db:
        db.add(
            Device(
                id="dev-other-1",
                serial="OTHER-1",
                name="other",
                user_id=OTHER_USER,
                org_id=OTHER_ORG,
                created_at=NOW,
            )
        )
        db.add(
            DeviceFsmSnapshot(
                device_id="dev-other-1",
                state=DeviceFsmState.ONLINE.value,
                updated_at=NOW,
            )
        )
        await create_mcp_session(db, "other-session", "OTHER-1", OTHER_USER)
        await db.commit()

    app = _build_app(session_factory, user_id=USER_ID, org_id=ORG_ID, org_role="owner")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/devices/fleet/stats")

    assert resp.status_code == 200
    body = resp.json()
    assert body["devices"]["total"] == 6
    assert body["active_sessions"]["total"] == 4


@pytest.mark.asyncio
async def test_fleet_stats_owner_gets_empty_anomaly_list_without_issues(session_factory):
    await _seed_base(session_factory)
    async with session_factory() as db:
        db.add(
            Device(
                id="dev-clean",
                serial="SER-CLEAN",
                name="clean",
                user_id=USER_ID,
                org_id=ORG_ID,
                created_at=NOW,
            )
        )
        db.add(
            DeviceFsmSnapshot(
                device_id="dev-clean",
                state=DeviceFsmState.ONLINE.value,
                updated_at=NOW,
            )
        )
        await create_mcp_session(db, "mcp-clean", "SER-CLEAN", USER_ID)
        await db.commit()

    app = _build_app(session_factory, user_id=USER_ID, org_id=ORG_ID, org_role="owner")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/devices/fleet/stats")

    assert resp.status_code == 200
    assert resp.json()["owner_anomalies"] == []


@pytest.mark.asyncio
async def test_fleet_stats_handles_large_org(session_factory):
    await _seed_base(session_factory)
    async with session_factory() as db:
        for i in range(100):
            device_id = f"dev-bulk-{i}"
            db.add(
                Device(
                    id=device_id,
                    serial=f"BULK-{i}",
                    name=f"bulk-{i}",
                    user_id=USER_ID,
                    org_id=ORG_ID,
                    created_at=NOW,
                )
            )
            state = DeviceFsmState.ONLINE if i % 2 == 0 else DeviceFsmState.DEAD
            db.add(
                DeviceFsmSnapshot(
                    device_id=device_id,
                    state=state.value,
                    updated_at=NOW,
                )
            )
        await db.commit()

    set_current_org_id(ORG_ID)
    async with session_factory() as db:
        stats = await query_fleet_stats(db, org_id=ORG_ID)
    assert stats.device_total == 100
    assert stats.devices_by_state["online"] == 50
    assert stats.devices_by_state["dead"] == 50
