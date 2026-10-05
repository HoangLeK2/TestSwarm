from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.device_liveness import filter_live_devices_for_dispatch, is_device_dispatchable


@pytest.mark.asyncio
async def test_stale_last_seen_is_dispatchable_when_relay_is_live():
    db = AsyncMock()
    device = SimpleNamespace(
        id="dev-1",
        serial="SN001",
        last_seen=datetime.now(timezone.utc) - timedelta(hours=1),
    )

    with patch("services.device_liveness.relay_has_device", return_value=True):
        assert await is_device_dispatchable(
            db,
            device,
            offline_after_minutes=5,
        )


@pytest.mark.asyncio
async def test_stale_last_seen_without_transport_is_not_dispatchable():
    db = AsyncMock()
    device = SimpleNamespace(
        id="dev-1",
        serial="SN001",
        last_seen=datetime.now(timezone.utc) - timedelta(hours=1),
    )

    with patch("services.device_liveness.relay_has_device", return_value=False), patch(
        "services.device_liveness.db_has_open_session",
        new_callable=AsyncMock,
        return_value=False,
    ):
        assert not await is_device_dispatchable(
            db,
            device,
            offline_after_minutes=5,
        )


@pytest.mark.asyncio
async def test_filter_live_devices_bulk_loads_open_sessions_for_large_stale_batches():
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = ["dev-001", "dev-400"]
    db.execute = AsyncMock(return_value=result)
    devices = [
        SimpleNamespace(
            id=f"dev-{idx:03d}",
            serial=f"SN{idx:03d}",
            last_seen=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        for idx in range(1, 501)
    ]

    with patch("services.device_liveness.relay_has_device", return_value=False), patch(
        "services.device_liveness.db_has_open_session",
        new_callable=AsyncMock,
        return_value=False,
    ) as per_device_session:
        live, skipped = await filter_live_devices_for_dispatch(
            db,
            devices,
            offline_after_minutes=5,
        )

    per_device_session.assert_not_awaited()
    db.execute.assert_awaited_once()
    assert [device.id for device in live] == ["dev-001", "dev-400"]
    assert len(skipped) == 498
