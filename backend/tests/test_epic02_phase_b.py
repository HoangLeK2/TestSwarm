"""Epic 02 Phase B: reconnect policy, admin override, fleet query, capacity."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.crud.router import api_router
from api.deps import _get_current_user, _get_db
from db.crud.device import create_device
from db.database import Base
from db.models import Organization, User
from db.models.enums import DeviceFsmEvent
from services.device_reserve.service import claim_device_session
from services.device_state.service import DeviceStateService
from tenancy.context import set_current_org_id


ORG_ID = "org-epic02-b"
USER_A = "user-alice"
USER_B = "user-bob"
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


def _build_app(session_factory, *, user_id: str = USER_A, org_role: str = "owner"):
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
        set_current_org_id(ORG_ID)
        return SimpleNamespace(
            id=user_id,
            email=f"{user_id}@example.com",
            name=user_id,
            role="operator",
            org_role=org_role,
            is_active=True,
            org_id=ORG_ID,
        )

    app.dependency_overrides[_get_db] = _db_override
    app.dependency_overrides[_get_current_user] = _user_override
    return app


async def _seed_org(session_factory):
    async with session_factory() as db:
        db.add(
            Organization(
                id=ORG_ID,
                business_name="Epic02 B",
                business_email="b@org.local",
                status="active",
                plan="standard",
                created_at=NOW,
            )
        )
        db.add(
            User(
                id=USER_A,
                email="alice@org.local",
                name="Alice",
                hashed_password="x",
                org_id=ORG_ID,
            )
        )
        db.add(
            User(
                id=USER_B,
                email="bob@org.local",
                name="Bob",
                hashed_password="x",
                org_id=ORG_ID,
            )
        )
        await db.commit()


async def _online_device(session_factory, serial: str = "R58M12345") -> str:
    set_current_org_id(ORG_ID)
    svc = DeviceStateService()
    async with session_factory() as db:
        device = await create_device(db, serial, user_id=USER_A, org_id=ORG_ID)
        device.device_serial = serial
        device.adb_serial = "192.168.1.10:5555"
        device.relay_serial = "relay-h1"
        device.paired_at = NOW
        await db.flush()
        await svc.apply_event(
            db, device.id, event=DeviceFsmEvent.ATTACHED.value, source="agent", event_id=f"{serial}-1"
        )
        await svc.apply_event(
            db, device.id, event=DeviceFsmEvent.ONLINE.value, source="agent", event_id=f"{serial}-2"
        )
        await db.commit()
        return device.id


async def _seed_devices(session_factory, count: int) -> None:
    for idx in range(count):
        await _online_device(session_factory, serial=f"R58M{idx:05d}")


@pytest.mark.asyncio
async def test_reconnect_policy_default_and_update(session_factory):
    await _seed_org(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/reconnect-policy")
        assert resp.status_code == 200
        assert resp.headers["x-policy-source"] == "default"
        body = resp.json()
        assert body["interval_base_ms"] == 1000
        assert body["max_attempts"] == 20

        bad = await client.put(
            "/api/admin/reconnect-policy",
            json={
                "interval_base_ms": 0,
                "max_interval_ms": 60000,
                "max_attempts": 20,
                "jitter_factor": 0.2,
            },
        )
        assert bad.status_code == 400
        assert bad.json()["detail"]["code"] == "INVALID_RANGE"

        ok = await client.put(
            "/api/admin/reconnect-policy",
            json={
                "interval_base_ms": 2000,
                "max_interval_ms": 120000,
                "max_attempts": 15,
                "jitter_factor": 0.3,
            },
        )
        assert ok.status_code == 200
        assert ok.json()["interval_base_ms"] == 2000
        assert ok.json()["source"] == "configured"


@pytest.mark.asyncio
async def test_reconnect_policy_forbidden_for_member(session_factory):
    await _seed_org(session_factory)
    app = _build_app(session_factory, user_id=USER_B, org_role="supervisor")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            "/api/admin/reconnect-policy",
            json={
                "interval_base_ms": 2000,
                "max_interval_ms": 120000,
                "max_attempts": 15,
                "jitter_factor": 0.3,
            },
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_force_release_busy_device(session_factory):
    await _seed_org(session_factory)
    device_id = await _online_device(session_factory)
    set_current_org_id(ORG_ID)
    async with session_factory() as db:
        await claim_device_session(
            db,
            device_id=device_id,
            org_id=ORG_ID,
            actor_user_id=USER_A,
            owner_type="manual",
            owner_id=USER_A,
        )
        await db.commit()

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/admin/devices/{device_id}/force-release",
            json={"reason": "stuck session after host crash"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["from_state"] == "busy"
        assert body["to_state"] == "online"
        assert body["old_owner_id"] == USER_A
        assert body["reason"] == "stuck session after host crash"


@pytest.mark.asyncio
async def test_admin_force_release_requires_reason(session_factory):
    await _seed_org(session_factory)
    device_id = await _online_device(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/admin/devices/{device_id}/force-release",
            json={"reason": "   "},
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_admin_reset_dead_device(session_factory):
    await _seed_org(session_factory)
    device_id = await _online_device(session_factory)
    set_current_org_id(ORG_ID)
    svc = DeviceStateService()
    async with session_factory() as db:
        await svc.apply_event(
            db, device_id, event=DeviceFsmEvent.RECONNECTING.value, source="agent", event_id="r1"
        )
        await svc.apply_event(
            db, device_id, event=DeviceFsmEvent.DEAD.value, source="agent", event_id="d1"
        )
        await db.commit()

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/admin/devices/{device_id}/reset-state",
            json={"reason": "operator confirmed USB reconnected"},
        )
        assert resp.status_code == 200
        assert resp.json()["from_state"] == "dead"
        assert resp.json()["to_state"] == "connecting"


@pytest.mark.asyncio
async def test_fleet_list_pagination_and_filter(session_factory):
    await _seed_org(session_factory)
    await _seed_devices(session_factory, 5)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        page1 = await client.get("/api/devices?limit=2&sort=name")
        assert page1.status_code == 200
        body1 = page1.json()
        assert len(body1["items"]) == 2
        assert body1["total"] == 5
        assert body1["next_cursor"]

        page2 = await client.get(f"/api/devices?limit=2&sort=name&cursor={body1['next_cursor']}")
        assert page2.status_code == 200
        body2 = page2.json()
        ids1 = {item["db_id"] for item in body1["items"]}
        ids2 = {item["db_id"] for item in body2["items"]}
        assert ids1.isdisjoint(ids2)

        search = await client.get("/api/devices?limit=10&q=R58M00003")
        assert search.status_code == 200
        assert search.json()["total"] == 1
        assert search.json()["items"][0]["device_serial"] == "R58M00003"

        bad_cursor = await client.get("/api/devices?limit=10&cursor=not-valid")
        assert bad_cursor.status_code == 400
        assert bad_cursor.json()["detail"]["code"] == "INVALID_CURSOR"

        bad_limit = await client.get("/api/devices?limit=999")
        assert bad_limit.status_code == 400


@pytest.mark.asyncio
async def test_fleet_list_state_filter(session_factory):
    await _seed_org(session_factory)
    await _online_device(session_factory, serial="R58M-ONLINE")
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/devices?limit=50&state=online")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert all(item["state"] == "online" for item in items)


@pytest.mark.asyncio
async def test_capacity_report(session_factory):
    await _seed_org(session_factory)
    await _seed_devices(session_factory, 3)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/devices/capacity")
        assert resp.status_code == 200
        body = resp.json()
        assert body["summary"]["total"] == 3
        assert body["summary"]["available"] >= 3
        assert len(body["sample_devices"]) == 3
        assert body["sample_devices"][0]["db_id"]
        assert body["sample_devices"][0]["device_serial"]
