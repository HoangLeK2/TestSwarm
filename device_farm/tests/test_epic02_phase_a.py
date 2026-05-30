"""Epic 02 Phase A: claim/release, auto-release, registry pair/unpair."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.crud.router import api_router
from api.deps import _get_current_user, _get_db
from db.crud.device import create_device
from db.crud.device_reserve_session import get_active_session
from db.database import Base
from db.models import Organization, User
from db.models.enums import DeviceFsmEvent
from db.models.tenant_settings import TenantSettings
from services.device_reserve.service import auto_release_expired_sessions, claim_device_session
from services.device_state.service import DeviceStateService
from tenancy.context import set_current_org_id


ORG_ID = "org-epic02-a"
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
                business_name="Epic02 A",
                business_email="a@org.local",
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
        await db.flush()
        await svc.apply_event(
            db, device.id, event=DeviceFsmEvent.ATTACHED.value, source="agent", event_id="1"
        )
        await svc.apply_event(
            db, device.id, event=DeviceFsmEvent.ONLINE.value, source="agent", event_id="2"
        )
        await db.commit()
        return device.id


@pytest.mark.asyncio
async def test_registry_pair_and_repair(session_factory):
    await _seed_org(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/devices/registry/pair",
            json={
                "device_serial": "R58M12345",
                "adb_serial": "192.168.1.10:5555",
                "relay_serial": "relay-h1",
                "name": "Phone 1",
            },
        )
        assert created.status_code == 201
        body = created.json()
        assert body["device_serial"] == "R58M12345"
        assert body["device_key"]
        db_id = body["db_id"]

        repaired = await client.post(
            "/api/devices/registry/pair",
            json={
                "device_serial": "R58M12345",
                "adb_serial": "192.168.1.20:5555",
                "relay_serial": "relay-h1",
            },
        )
        assert repaired.status_code == 200
        assert repaired.json()["device_key"] is None

        detail = await client.get(f"/api/devices/{db_id}")
        assert detail.status_code == 200
        assert detail.json()["adb_serial"] == "192.168.1.20:5555"


@pytest.mark.asyncio
async def test_claim_release_flow(session_factory):
    await _seed_org(session_factory)
    device_id = await _online_device(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        claim = await client.post(
            f"/api/devices/{device_id}/claim",
            json={"owner_type": "manual", "owner_id": USER_A, "ttl_sec": 1800},
        )
        assert claim.status_code == 201
        session_id = claim.json()["session_id"]

        busy = await client.post(
            f"/api/devices/{device_id}/claim",
            json={"owner_type": "manual", "owner_id": USER_B},
        )
        assert busy.status_code == 409
        assert busy.json()["detail"]["code"] == "DEVICE_BUSY"

        release = await client.post(
            f"/api/devices/{device_id}/release",
            json={"session_id": session_id},
        )
        assert release.status_code == 200

        again = await client.post(
            f"/api/devices/{device_id}/claim",
            json={"owner_type": "manual", "owner_id": USER_A},
        )
        assert again.status_code == 201


@pytest.mark.asyncio
async def test_release_forbidden_for_non_owner(session_factory):
    await _seed_org(session_factory)
    device_id = await _online_device(session_factory)
    set_current_org_id(ORG_ID)
    async with session_factory() as db:
        view = await claim_device_session(
            db,
            device_id=device_id,
            org_id=ORG_ID,
            actor_user_id=USER_A,
            owner_type="manual",
            owner_id=USER_A,
        )
        await db.commit()
        session_id = view.session_id

    app = _build_app(session_factory, user_id=USER_B, org_role="supervisor")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/devices/{device_id}/release",
            json={"session_id": session_id},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "NOT_SESSION_OWNER"


@pytest.mark.asyncio
async def test_auto_release_after_idle(session_factory):
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
            ttl_sec=600,
        )
        row = await get_active_session(db, device_id)
        assert row is not None
        row.last_heartbeat = NOW - timedelta(seconds=310)
        await db.commit()

    set_current_org_id(ORG_ID)
    async with session_factory() as db:
        released = await auto_release_expired_sessions(db)
        await db.commit()
        assert released == 1

    async with session_factory() as db:
        row = await get_active_session(db, device_id)
        assert row is None


@pytest.mark.asyncio
async def test_heartbeat_prevents_auto_release(session_factory):
    await _seed_org(session_factory)
    device_id = await _online_device(session_factory, serial="R58M99999")
    set_current_org_id(ORG_ID)
    async with session_factory() as db:
        view = await claim_device_session(
            db,
            device_id=device_id,
            org_id=ORG_ID,
            actor_user_id=USER_A,
            owner_type="manual",
            owner_id=USER_A,
            ttl_sec=600,
        )
        row = await get_active_session(db, device_id)
        row.last_heartbeat = NOW - timedelta(seconds=200)
        await db.commit()
        session_id = view.session_id

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        hb = await client.post(f"/api/sessions/{session_id}/heartbeat")
        assert hb.status_code == 200

    set_current_org_id(ORG_ID)
    async with session_factory() as db:
        released = await auto_release_expired_sessions(db)
        await db.commit()
        assert released == 0


@pytest.mark.asyncio
async def test_unpair_blocked_when_busy(session_factory):
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
        resp = await client.post(f"/api/devices/{device_id}/unpair")
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "DEVICE_IN_SESSION"


@pytest.mark.asyncio
async def test_tenant_idle_threshold_override(session_factory):
    await _seed_org(session_factory)
    async with session_factory() as db:
        db.add(
            TenantSettings(
                org_id=ORG_ID,
                dead_threshold_sec=600,
                session_idle_thresholds={"manual": 900},
            )
        )
        await db.commit()

    device_id = await _online_device(session_factory, serial="R58-TENANT")
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
        row = await get_active_session(db, device_id)
        row.last_heartbeat = NOW - timedelta(seconds=600)
        await db.commit()

    set_current_org_id(ORG_ID)
    async with session_factory() as db:
        released = await auto_release_expired_sessions(db)
        await db.commit()
        assert released == 0
