from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from api.routes import devices as device_routes
from api.schemas.device import DeviceNameUpdate


def _device(name: str = ""):
    return SimpleNamespace(
        id="dev-1",
        org_id="org-1",
        serial="ZY22H7ABCDEF",
        device_serial="ZY22H7ABCDEF",
        name=name,
        device_key="key-1",
        user_id="user-1",
        brand="samsung",
        model="SM-N975F",
        android_version="12",
        sdk_version=31,
        screen_width=1080,
        screen_height=2400,
        last_seen=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        adb_serial=None,
        relay_serial=None,
        managed_by_org_id=None,
        managed_by_relay_id=None,
        adb_ip=None,
        adb_port=5555,
        tags="",
        status="paired",
        paired_at=None,
        unpaired_at=None,
        notes="",
    )


@pytest.mark.asyncio
async def test_update_device_name_trims_alias_and_keeps_serial(monkeypatch):
    db = SimpleNamespace(commit=AsyncMock())
    user = SimpleNamespace(id="user-1", org_id="org-1")
    get_device = AsyncMock(side_effect=[_device(), _device("PT-01")])
    update_device_name = AsyncMock()
    monkeypatch.setattr(device_routes.repo, "get_device", get_device)
    monkeypatch.setattr(device_routes.repo, "update_device_name", update_device_name)

    result = await device_routes.update_name(
        "dev-1", DeviceNameUpdate(name="  PT-01  "), db, user
    )

    assert result.name == "PT-01"
    assert result.serial == "ZY22H7ABCDEF"
    update_device_name.assert_awaited_once_with(db, "dev-1", "PT-01")
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_device_name_rejects_other_org(monkeypatch):
    db = SimpleNamespace(commit=AsyncMock())
    user = SimpleNamespace(id="user-1", org_id="org-2")
    monkeypatch.setattr(device_routes.repo, "get_device", AsyncMock(return_value=_device()))
    update_device_name = AsyncMock()
    monkeypatch.setattr(device_routes.repo, "update_device_name", update_device_name)

    with pytest.raises(HTTPException) as exc:
        await device_routes.update_name(
            "dev-1", DeviceNameUpdate(name="PT-01"), db, user
        )

    assert exc.value.status_code == 404
    update_device_name.assert_not_awaited()
    db.commit.assert_not_awaited()
