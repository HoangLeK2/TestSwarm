from __future__ import annotations

"""End-to-end (HTTP) tests for /api/device-groups routes.

Smoke check that:
  - POST /device-groups creates a group
  - GET /device-groups lists groups
  - POST /device-groups/{id}/devices adds devices (the user-reported "thêm nhóm thiết bị" flow)
  - DELETE /device-groups/{id}/devices/{device_id} removes a member

The DB is replaced with an in-memory async SQLite engine so the real CRUD layer
runs against real SQLAlchemy models (no mocking of the data layer).
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.deps import _get_current_user, _get_db
from api.routes.device_groups import router as device_groups_router
from db.database import Base
from db.models.device import Device
from db.models.device_group import DeviceGroup, DeviceGroupMember  # noqa: F401  — register tables
from tenancy.context import set_current_org_id


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


def _build_app(session_factory) -> FastAPI:
    app = FastAPI()
    app.include_router(device_groups_router, prefix="/api")

    async def _db_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as s:
            yield s

    async def _user_override():
        set_current_org_id("org-1")
        return SimpleNamespace(
            id="user-1",
            role="operator",
            org_role="owner",
            is_active=True,
            org_id="org-1",
        )

    app.dependency_overrides[_get_db] = _db_override
    app.dependency_overrides[_get_current_user] = _user_override
    return app


async def _seed_devices(
    session_factory,
    ids: list[str],
    owner: str = "user-1",
    *,
    org_id: str = "org-1",
) -> None:
    async with session_factory() as s:
        for did in ids:
            s.add(
                Device(
                    id=did,
                    serial=f"SERIAL_{did}",
                    name=f"dev-{did}",
                    user_id=owner,
                    org_id=org_id,
                    created_at=datetime.now(timezone.utc),
                )
            )
        await s.commit()


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_then_list(session_factory):
    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/api/device-groups", json={"name": "FB Farm"})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["name"] == "FB Farm"
        assert body["device_count"] == 0
        gid = body["id"]

        r2 = await ac.get("/api/device-groups")
        assert r2.status_code == 200
        groups = r2.json()
        assert len(groups) == 1
        assert groups[0]["id"] == gid


@pytest.mark.asyncio
async def test_add_devices_to_group_succeeds(session_factory):
    """The user-reported flow: thêm nhóm thiết bị."""
    await _seed_devices(session_factory, ["d1", "d2", "d3"])
    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/api/device-groups", json={"name": "G1"})
        gid = r.json()["id"]

        r2 = await ac.post(
            f"/api/device-groups/{gid}/devices",
            json={"device_ids": ["d1", "d2", "d3"]},
        )
        assert r2.status_code == 200, r2.text
        assert r2.json() == {"group_id": gid, "added": 3, "requested": 3}

        r3 = await ac.get(f"/api/device-groups/{gid}")
        assert r3.status_code == 200
        detail = r3.json()
        assert detail["device_count"] == 3
        assert {d["id"] for d in detail["devices"]} == {"d1", "d2", "d3"}


@pytest.mark.asyncio
async def test_add_devices_idempotent(session_factory):
    await _seed_devices(session_factory, ["d1"])
    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        gid = (await ac.post("/api/device-groups", json={"name": "G"})).json()["id"]

        first = await ac.post(f"/api/device-groups/{gid}/devices", json={"device_ids": ["d1"]})
        second = await ac.post(f"/api/device-groups/{gid}/devices", json={"device_ids": ["d1"]})

        assert first.json()["added"] == 1
        assert second.json()["added"] == 0  # already present, not re-added


@pytest.mark.asyncio
async def test_add_devices_filters_other_users(session_factory):
    """Devices in another org must be silently dropped."""
    await _seed_devices(session_factory, ["mine"], owner="user-1")
    await _seed_devices(session_factory, ["theirs"], owner="user-2", org_id="org-2")
    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        gid = (await ac.post("/api/device-groups", json={"name": "G"})).json()["id"]
        r = await ac.post(
            f"/api/device-groups/{gid}/devices",
            json={"device_ids": ["mine", "theirs", "ghost"]},
        )
        assert r.status_code == 200
        assert r.json()["added"] == 1  # only "mine" passes ownership check
        assert r.json()["requested"] == 3


@pytest.mark.asyncio
async def test_available_devices_supports_search_and_pagination(session_factory):
    await _seed_devices(session_factory, ["d1", "d2", "d3", "d4"])
    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        gid = (await ac.post("/api/device-groups", json={"name": "G"})).json()["id"]
        await ac.post(f"/api/device-groups/{gid}/devices", json={"device_ids": ["d1"]})

        first_page = await ac.get(
            f"/api/device-groups/{gid}/available-devices",
            params={"limit": 2, "offset": 0},
        )
        assert first_page.status_code == 200, first_page.text
        first_body = first_page.json()
        assert first_body["total"] == 3
        assert first_body["offset"] == 0
        assert first_body["limit"] == 2
        assert [d["id"] for d in first_body["items"]] == ["d2", "d3"]

        second_page = await ac.get(
            f"/api/device-groups/{gid}/available-devices",
            params={"limit": 2, "offset": 2},
        )
        assert second_page.status_code == 200
        assert [d["id"] for d in second_page.json()["items"]] == ["d4"]

        searched = await ac.get(
            f"/api/device-groups/{gid}/available-devices",
            params={"q": "SERIAL_d3", "limit": 2},
        )
        assert searched.status_code == 200
        searched_body = searched.json()
        assert searched_body["total"] == 1
        assert [d["id"] for d in searched_body["items"]] == ["d3"]


@pytest.mark.asyncio
async def test_remove_device_from_group(session_factory):
    await _seed_devices(session_factory, ["d1", "d2"])
    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        gid = (await ac.post("/api/device-groups", json={"name": "G"})).json()["id"]
        await ac.post(f"/api/device-groups/{gid}/devices", json={"device_ids": ["d1", "d2"]})

        r = await ac.delete(f"/api/device-groups/{gid}/devices/d1")
        assert r.status_code == 200
        assert r.json() == {"ok": True, "group_id": gid, "device_id": "d1"}

        detail = (await ac.get(f"/api/device-groups/{gid}")).json()
        assert detail["device_count"] == 1
        assert {d["id"] for d in detail["devices"]} == {"d2"}


@pytest.mark.asyncio
async def test_add_to_other_users_group_404(session_factory):
    """Group owned by another user must not be visible/writable."""
    # Create the group as user-1
    app1 = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app1), base_url="http://t") as ac:
        gid = (await ac.post("/api/device-groups", json={"name": "OwnedByU1"})).json()["id"]

    # Now act as user-2
    app2 = FastAPI()
    app2.include_router(device_groups_router, prefix="/api")

    async def _db_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as s:
            yield s

    async def _user_override():
        return SimpleNamespace(
            id="user-2",
            role="operator",
            org_role="owner",
            is_active=True,
            org_id="org-2",
        )

    app2.dependency_overrides[_get_db] = _db_override
    app2.dependency_overrides[_get_current_user] = _user_override

    async with AsyncClient(transport=ASGITransport(app=app2), base_url="http://t") as ac:
        r = await ac.post(f"/api/device-groups/{gid}/devices", json={"device_ids": []})
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_invalid_color_400(session_factory):
    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/api/device-groups",
            json={"name": "Bad", "color": "not-a-hex"},
        )
        assert r.status_code == 422  # pydantic field_validator rejects
