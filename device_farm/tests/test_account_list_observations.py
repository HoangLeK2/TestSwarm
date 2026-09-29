"""Guard: the profile reading a login scenario takes has to reach the operator.

``social_sync_connections`` writes two observations — the name the account's own
profile shows, and its friend count. Both landed in tables nobody read: the name
in ``device_platform_sessions.display_name_observed``, the count in
``account_graph_metrics`` behind a ``latest_graph_metric`` helper with zero
callers. The scenario reported friends=51 and the account page stayed blank.

The account row itself is deliberately not touched: ``display_name`` is what the
operator typed, and a misread profile must not be able to overwrite it. So the
fix is on the read side, and this asserts the read side still exists.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.deps import _get_current_user, _get_db
from api.routes.accounts import router as accounts_router
from db.database import Base
from db.models.account import Account, DeviceAccount
from db.models.account_graph_metric import AccountGraphMetric
from db.models.device import Device
from db.models.device_platform_session import DevicePlatformSession
from tenancy.context import set_current_org_id

_NOW = datetime(2026, 9, 11, 8, 29, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


def _build_app(session_factory) -> FastAPI:
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

    app.dependency_overrides[_get_db] = db_override
    app.dependency_overrides[_get_current_user] = user_override
    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        for dependency in getattr(dependant, "dependencies", []):
            if getattr(dependency.call, "__name__", "") == "_require_permission":
                app.dependency_overrides[dependency.call] = allow_permission
    return app


async def _seed(session_factory):
    async with session_factory() as session:
        session.add_all(
            [
                Device(
                    id="device-1",
                    serial="serial-1",
                    name="Điện thoại chính",
                    org_id="org-1",
                ),
                Device(id="device-2", serial="serial-2", org_id="org-1"),
                Account(
                    id="account-read",
                    platform="facebook",
                    username="61586957575493",
                    org_id="org-1",
                ),
                Account(
                    id="account-unread",
                    platform="facebook",
                    username="never-scanned",
                    org_id="org-1",
                ),
                # Stale reading on an older phone, and the current one. The
                # newest must win — an account that moved phones would otherwise
                # keep reporting the name it had on the phone it left.
                DevicePlatformSession(
                    id="ses-old",
                    org_id="org-1",
                    device_id="device-2",
                    platform="facebook",
                    account_id="account-read",
                    display_name_observed="Tên Cũ",
                    updated_at=_NOW - timedelta(days=3),
                ),
                DevicePlatformSession(
                    id="ses-new",
                    org_id="org-1",
                    device_id="device-1",
                    platform="facebook",
                    account_id="account-read",
                    display_name_observed="Thanh Trung Thảo",
                    updated_at=_NOW,
                ),
                AccountGraphMetric(
                    id="metric-old",
                    org_id="org-1",
                    account_id="account-read",
                    platform="facebook",
                    metric="friends",
                    value=12,
                    observed_at=_NOW - timedelta(days=3),
                ),
                AccountGraphMetric(
                    id="metric-new",
                    org_id="org-1",
                    account_id="account-read",
                    platform="facebook",
                    metric="friends",
                    value=51,
                    observed_at=_NOW,
                ),
                # A different metric on the same account must not be mistaken
                # for its friend count.
                AccountGraphMetric(
                    id="metric-followers",
                    org_id="org-1",
                    account_id="account-read",
                    platform="facebook",
                    metric="followers",
                    value=9999,
                    observed_at=_NOW,
                ),
                DeviceAccount(
                    id="link-1",
                    device_id="device-1",
                    account_id="account-read",
                    is_primary=True,
                    assigned_at=_NOW,
                ),
            ]
        )
        await session.commit()


@pytest.mark.asyncio
async def test_account_list_reports_the_latest_profile_reading(session_factory):
    await _seed(session_factory)
    app = _build_app(session_factory)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/accounts")

    assert response.status_code == 200, response.text
    rows = {row["id"]: row for row in response.json()}

    read = rows["account-read"]
    assert read["observed_display_name"] == "Thanh Trung Thảo"
    assert read["friends_count"] == 51
    assert read["friends_observed_at"]
    assert read["assigned_device_name"] == "Điện thoại chính"
    # The operator's own field is untouched by a profile reading.
    assert read["display_name"] == ""

    never = rows["account-unread"]
    assert never["observed_display_name"] is None
    assert never["friends_count"] is None
    assert never["assigned_device_name"] is None
