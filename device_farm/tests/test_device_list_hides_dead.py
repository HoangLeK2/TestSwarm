"""A dead (unplugged/removed) device must not clutter the fleet list.

The device is still `paired` in the DB, but once the agent stops reporting it
the authoritative state becomes DEAD, and the general list should drop it.
Explicit `state=` / id / serial queries still return dead devices so revive and
removal tooling keeps working.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models.enums import DeviceFsmState


def _row(serial: str, state: str) -> SimpleNamespace:
    return SimpleNamespace(
        db_id=f"id-{serial}",
        device_serial=serial,
        adb_serial=serial,
        relay_serial=serial,
        adb_ip=None,
        adb_port=5555,
        name=serial,
        state=state,
        group_ids=[],
        current_session_id=None,
        owner_type=None,
        owner_id=None,
        last_seen_at=None,
        model="",
        android_version="",
    )


async def _call(*, state=None, device_id=None, rows):
    from api.routes import devices as mod

    page = SimpleNamespace(items=rows, next_cursor=None, total=len(rows))
    req = MagicMock()
    req.app.state.manager = None
    user = SimpleNamespace(org_id="org-a", id="user-a", role="member")

    with patch.object(mod, "query_fleet_devices", AsyncMock(return_value=page)), \
         patch.object(mod, "_get_ctrl_servicer_optional", return_value=None):
        return await mod.list_devices(
            request=req,
            db=AsyncMock(),
            user=user,
            cursor=None,
            limit=50,          # any param → fleet mode
            state=state,
            group_id=None,
            owner_type=None,
            relay_host=None,
            tag=None,
            q=None,
            sort=None,
            device_id=device_id,
            device_serial=None,
            adb_serial=None,
            relay_serial=None,
        )


@pytest.mark.asyncio
async def test_dead_device_dropped_from_default_list():
    rows = [
        _row("emulator-5554", DeviceFsmState.ONLINE.value),
        _row("10AE7S00HD002JK", DeviceFsmState.DEAD.value),
    ]
    out = await _call(rows=rows)

    serials = [i.device_serial for i in out.items]
    assert "emulator-5554" in serials
    assert "10AE7S00HD002JK" not in serials
    # total kept honest with what was returned
    assert out.total == 1


@pytest.mark.asyncio
async def test_explicit_state_filter_still_returns_dead():
    rows = [_row("10AE7S00HD002JK", DeviceFsmState.DEAD.value)]
    out = await _call(state=DeviceFsmState.DEAD.value, rows=rows)

    assert [i.device_serial for i in out.items] == ["10AE7S00HD002JK"]


@pytest.mark.asyncio
async def test_direct_device_id_lookup_still_returns_dead():
    rows = [_row("10AE7S00HD002JK", DeviceFsmState.DEAD.value)]
    out = await _call(device_id="id-10AE7S00HD002JK", rows=rows)

    assert [i.device_serial for i in out.items] == ["10AE7S00HD002JK"]


@pytest.mark.asyncio
async def test_all_online_list_is_unchanged():
    rows = [
        _row("emulator-5554", DeviceFsmState.ONLINE.value),
        _row("emulator-5556", DeviceFsmState.ONLINE.value),
    ]
    out = await _call(rows=rows)

    assert len(out.items) == 2
    assert out.total == 2
