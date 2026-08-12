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
                    platform="facebook",
                    username="one",
                    org_id="org-1",
                ),
                Account(
                    id="account-2",
                    platform="facebook",
                    username="two",
                    org_id="org-1",
                ),
                Account(
                    id="account-foreign",
                    platform="facebook",
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

        session = await client.get("/api/devices/device-1/platform-sessions/facebook")
        assert session.status_code == 200
        assert session.json()["state"] == "login_required"
        assert session.json()["account_id"] is None
        assert session.json()["evidence"]["expected_account_id"] == "account-2"

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
async def test_manual_session_confirmation_and_remove_invalidation(session_factory):
    await _seed(session_factory)
    async with session_factory() as session:
        session.add(DeviceAccount(id="link-1", device_id="device-1", account_id="account-1"))
        await session.commit()

    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        confirmed = await client.post(
            "/api/devices/device-1/platform-sessions/facebook/confirm",
            json={
                "account_id": "account-1",
                "reason": "migration_operator_confirmed",
                "display_name_observed": "One",
                "evidence": {
                    "readiness": "ready",
                    "password": "secret",
                    "hierarchy_xml": "<hierarchy />",
                    "screen_hash": "abc123",
                },
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        body = confirmed.json()
        assert body["state"] == "active"
        assert body["account_id"] == "account-1"
        assert body["establishment_method"] == "operator_confirmed"
        assert body["evidence"] == {
            "readiness": "ready",
            "screen_hash": "abc123",
            "actor": "user-1",
        }

        removed = await client.delete("/api/accounts/account-1/devices/device-1")
        assert removed.status_code == 200

        current = await client.get("/api/devices/device-1/platform-sessions/facebook")
        assert current.status_code == 200
        assert current.json()["state"] == "login_required"
        assert current.json()["account_id"] is None
        assert current.json()["state_reason"] == "provenance_account_unassigned"


@pytest.mark.asyncio
async def test_session_confirmation_rejects_stale_version(session_factory):
    await _seed(session_factory)
    async with session_factory() as session:
        session.add(DeviceAccount(id="link-1", device_id="device-1", account_id="account-1"))
        await session.commit()

    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        current = await client.get("/api/devices/device-1/platform-sessions/facebook")
        assert current.status_code == 200
        stale_version = current.json()["version"] - 1
        response = await client.post(
            "/api/devices/device-1/platform-sessions/facebook/confirm",
            json={
                "account_id": "account-1",
                "reason": "migration_operator_confirmed",
                "expected_version": stale_version,
            },
        )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_login_attempt_start_complete_and_cancel_contract(session_factory):
    await _seed(session_factory)
    async with session_factory() as session:
        session.add(DeviceAccount(id="link-1", device_id="device-1", account_id="account-1"))
        await session.commit()

    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        started = await client.post(
            "/api/devices/device-1/platform-sessions/facebook/login-attempts",
            json={"account_id": "account-1", "evidence": {"password": "secret", "ticket": "T-1"}},
        )
        assert started.status_code == 201, started.text
        body = started.json()
        assert body["state"] == "running"
        assert body["reserve_session_id"]
        assert body["evidence"] == {"ticket": "T-1", "actor": "user-1"}

        blocked = await client.post(
            f"/api/devices/device-1/platform-sessions/facebook/login-attempts/{body['id']}/complete",
            json={"operator_confirmed": False},
        )
        assert blocked.status_code == 409

        completed = await client.post(
            f"/api/devices/device-1/platform-sessions/facebook/login-attempts/{body['id']}/complete",
            json={"operator_confirmed": True, "evidence": {"screen_hash": "abc", "hierarchy_xml": "<x />"}},
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["state"] == "completed"

        current = await client.get("/api/devices/device-1/platform-sessions/facebook")
        assert current.status_code == 200
        assert current.json()["state"] == "active"
        assert current.json()["account_id"] == "account-1"
        assert current.json()["establishment_method"] == "operator_login_attempt"
        assert current.json()["evidence"] == {"actor": "user-1", "screen_hash": "abc"}

        second = await client.post(
            "/api/devices/device-1/platform-sessions/facebook/login-attempts",
            json={"account_id": "account-1"},
        )
        assert second.status_code == 201, second.text
        cancelled = await client.post(
            f"/api/devices/device-1/platform-sessions/facebook/login-attempts/{second.json()['id']}/cancel",
            json={"reason": "operator_cancelled"},
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["state"] == "cancelled"


@pytest.mark.asyncio
async def test_controlled_login_attempt_is_disabled_by_default(session_factory):
    await _seed(session_factory)
    async with session_factory() as session:
        session.add(DeviceAccount(id="link-1", device_id="device-1", account_id="account-1"))
        await session.commit()

    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/devices/device-1/platform-sessions/facebook/login-attempts/controlled",
            json={"account_id": "account-1"},
        )
    assert response.status_code == 423
    assert response.json()["detail"]["code"] == "controlled_login_disabled"


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
