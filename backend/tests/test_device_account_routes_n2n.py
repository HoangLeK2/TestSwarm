from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.deps import _get_current_user, _get_db
from api.routes.accounts import router as accounts_router
from db.database import Base
from db.models.account import Account, DeviceAccount
from db.models.device import Device
from db.models.device_fsm import DeviceFsmSnapshot
from db.models.enums import DeviceFsmState
from services.account_verification import AccountVerificationResult, VerificationStatus
from tenancy.context import set_current_org_id


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


def _build_app(session_factory, *, allow_permissions: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(accounts_router, prefix="/api")
    app.state.manager = None

    async def db_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    async def user_override():
        set_current_org_id("org-1")
        return SimpleNamespace(id="user-1", org_id="org-1", org_role="owner")

    async def allow_permission():
        return None

    async def deny_permission():
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN_ROLE"})

    app.dependency_overrides[_get_db] = db_override
    app.dependency_overrides[_get_current_user] = user_override
    permission_override = allow_permission if allow_permissions else deny_permission
    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        for dependency in getattr(dependant, "dependencies", []):
            if getattr(dependency.call, "__name__", "") == "_require_permission":
                app.dependency_overrides[dependency.call] = permission_override
    return app


async def _seed(session_factory):
    async with session_factory() as session:
        session.add_all(
            [
                Device(id="device-1", serial="serial-1", org_id="org-1"),
                Device(id="device-2", serial="serial-2", org_id="org-2"),
                Account(
                    id="account-1",
                    platform="android",
                    username="one",
                    org_id="org-1",
                ),
                Account(
                    id="account-2",
                    platform="android",
                    username="two",
                    org_id="org-1",
                ),
                Account(
                    id="account-foreign",
                    platform="android",
                    username="foreign",
                    org_id="org-2",
                ),
                DeviceFsmSnapshot(device_id="device-1", state=DeviceFsmState.ONLINE.value),
            ]
        )
        await session.commit()


@pytest.mark.asyncio
async def test_assign_multiple_set_primary_and_remove(session_factory):
    await _seed(session_factory)
    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(
            "/api/devices/device-1/accounts",
            json={"account_id": "account-1", "is_primary": True},
        )
        second = await client.post(
            "/api/devices/device-1/accounts",
            json={"account_id": "account-2"},
        )
        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text

        promoted = await client.post(
            "/api/devices/device-1/accounts/primary",
            json={"account_id": "account-2"},
        )
        assert promoted.status_code == 200, promoted.text

        listed = await client.get("/api/devices/device-1/accounts")
        assert listed.status_code == 200
        links = {row["account_id"]: row for row in listed.json()}
        assert links["account-1"]["is_primary"] is False
        assert links["account-2"]["is_primary"] is True
        assert links["account-2"]["verification_status"] == "unknown"

        removed = await client.delete("/api/accounts/account-1/devices/device-1")
        assert removed.status_code == 200
        assert removed.json()["ok"] is True
        listed = await client.get("/api/devices/device-1/accounts")
        assert [row["account_id"] for row in listed.json()] == ["account-2"]


@pytest.mark.asyncio
async def test_device_account_routes_hide_cross_tenant_resources(session_factory):
    await _seed(session_factory)
    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/devices/device-2/accounts")).status_code == 404
        response = await client.post(
            "/api/devices/device-1/accounts",
            json={"account_id": "account-foreign"},
        )
        assert response.status_code == 404
        response = await client.post(
            "/api/devices/device-2/accounts",
            json={"account_id": "account-1"},
        )
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_verify_returns_verification_contract(session_factory, monkeypatch):
    await _seed(session_factory)
    async with session_factory() as session:
        session.add(DeviceAccount(id="link-1", device_id="device-1", account_id="account-1"))
        await session.commit()

    attempted_at = datetime.now(timezone.utc)

    async def fake_verify(targets, manager):
        target = targets[0]
        return {
            target.assignment_id: AccountVerificationResult(
                assignment_id=target.assignment_id,
                status=VerificationStatus.VERIFIED,
                reason="identifier_match",
                attempted_at=attempted_at,
                attempt_id="attempt-1",
                duration_ms=12.5,
            )
        }

    monkeypatch.setattr("services.account_verification.verify_targets", fake_verify)
    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/devices/device-1/accounts/account-1/verify")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "verified"
    assert response.json()["assignment_id"] == "link-1"
    assert response.json()["attempt_id"] == "attempt-1"
    assert response.json()["duration_ms"] == 12.5


@pytest.mark.asyncio
async def test_update_permission_is_required(session_factory):
    await _seed(session_factory)
    app = _build_app(session_factory, allow_permissions=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/devices/device-1/accounts",
            json={"account_id": "account-1"},
        )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "FORBIDDEN_ROLE"


@pytest.mark.asyncio
async def test_account_search_filters_server_side(session_factory):
    """The step-editor account picker shows a handful of rows and cannot filter
    client-side: an account outside the fetched page would be unreachable."""
    await _seed(session_factory)
    async with session_factory() as session:
        session.add(
            Account(
                id="account-3",
                platform="android",
                username="hidden",
                display_name="Nguyen Van Two",
                org_id="org-1",
            )
        )
        await session.commit()

    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        by_username = await client.get("/api/accounts", params={"search": "two"})
        assert by_username.status_code == 200, by_username.text
        assert {row["id"] for row in by_username.json()} == {"account-2", "account-3"}

        by_display_name = await client.get("/api/accounts", params={"search": "nguyen"})
        assert [row["id"] for row in by_display_name.json()] == ["account-3"]

        limited = await client.get("/api/accounts", params={"limit": 1})
        assert len(limited.json()) == 1

        no_match = await client.get("/api/accounts", params={"search": "zzz"})
        assert no_match.json() == []

        unfiltered = await client.get("/api/accounts")
        assert len(unfiltered.json()) >= 3


@pytest.mark.asyncio
async def test_account_available_devices_supports_backend_search_and_pagination(
    session_factory,
):
    await _seed(session_factory)
    async with session_factory() as session:
        session.add_all(
            [
                Device(
                    id="device-3",
                    serial="serial-3",
                    name="Alpha",
                    org_id="org-1",
                ),
                Device(
                    id="device-4",
                    serial="needle-4",
                    name="Beta",
                    org_id="org-1",
                ),
                DeviceAccount(
                    id="link-1",
                    device_id="device-1",
                    account_id="account-1",
                ),
            ]
        )
        await session.commit()

    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first_page = await client.get(
            "/api/accounts/account-1/available-devices",
            params={"limit": 1, "offset": 0},
        )
        assert first_page.status_code == 200, first_page.text
        first_body = first_page.json()
        assert first_body["total"] == 2
        assert first_body["offset"] == 0
        assert first_body["limit"] == 1
        assert [row["id"] for row in first_body["items"]] == ["device-3"]

        second_page = await client.get(
            "/api/accounts/account-1/available-devices",
            params={"limit": 1, "offset": 1},
        )
        assert second_page.status_code == 200
        assert [row["id"] for row in second_page.json()["items"]] == ["device-4"]

        searched = await client.get(
            "/api/accounts/account-1/available-devices",
            params={"q": "needle", "limit": 10},
        )
        assert searched.status_code == 200
        searched_body = searched.json()
        assert searched_body["total"] == 1
        assert [row["id"] for row in searched_body["items"]] == ["device-4"]

        linked_match = await client.get(
            "/api/accounts/account-1/available-devices",
            params={"q": "serial-1"},
        )
        assert linked_match.status_code == 200
        assert linked_match.json()["total"] == 0

        foreign_account = await client.get(
            "/api/accounts/account-foreign/available-devices",
        )
        assert foreign_account.status_code == 404
