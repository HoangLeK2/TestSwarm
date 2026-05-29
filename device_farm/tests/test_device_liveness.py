from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services.device_liveness import is_device_dispatchable


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
