"""The default inventory only shows reachable devices; explicit lookups retain history."""
from __future__ import annotations

from datetime import UTC, datetime
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


async def _call(*, state=None, device_id=None, rows, reachable_serials=None, connected_only=True):
    from api.routes import devices as mod

    registered = [
        SimpleNamespace(id=row.db_id, serial=row.device_serial, adb_serial=row.adb_serial)
        for row in rows
    ]
    req = MagicMock()
    req.app.state.manager = None
    user = SimpleNamespace(org_id="org-a", id="user-a", role="member")

    reachable_serials = set(reachable_serials or [])
    ctrl = SimpleNamespace(conn_for_serial=lambda serial: serial if serial in reachable_serials else None)
    async def query_page(*_args, visible_device_ids=None, **_kwargs):
        visible = rows if visible_device_ids is None else [
            row for row in rows if row.db_id in visible_device_ids
        ]
        return SimpleNamespace(items=visible, next_cursor=None, total=len(visible))

    with patch.object(mod, "query_fleet_devices", side_effect=query_page), \
         patch.object(mod.repo, "list_devices", AsyncMock(return_value=registered)), \
         patch.object(mod, "_get_ctrl_servicer_optional", return_value=ctrl), \
         patch.object(mod, "_get_relay_manager_optional", return_value=None):
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
            connected_only=connected_only,
        )


async def _call_unfiltered(*, devices, state_by_id, reachable_serials=None, connected_only=True):
    from api.routes import devices as mod

    req = MagicMock()
    req.app.state.manager = None
    user = SimpleNamespace(org_id="org-a", id="user-a", role="member")
    states = {
        device.id: SimpleNamespace(state=state_by_id[device.id])
        for device in devices
    }

    reachable_serials = set(reachable_serials or [])
    ctrl = SimpleNamespace(conn_for_serial=lambda serial: serial if serial in reachable_serials else None)
    with patch.object(mod.repo, "list_devices", AsyncMock(return_value=devices)), \
         patch.object(mod, "get_device_states_map", AsyncMock(return_value=states)), \
         patch.object(mod, "_get_ctrl_servicer_optional", return_value=ctrl), \
         patch.object(mod, "_get_relay_manager_optional", return_value=None):
        return await mod.list_devices(
            request=req,
            db=AsyncMock(),
            user=user,
            cursor=None,
            limit=None,
            state=None,
            group_id=None,
            owner_type=None,
            relay_host=None,
            tag=None,
            q=None,
            sort=None,
            device_id=None,
            device_serial=None,
            adb_serial=None,
            relay_serial=None,
            connected_only=connected_only,
        )


@pytest.mark.asyncio
async def test_default_page_hides_unreachable_device():
    rows = [
        _row("emulator-5554", DeviceFsmState.ONLINE.value),
        _row("10AE7S00HD002JK", DeviceFsmState.DEAD.value),
    ]
    out = await _call(rows=rows, reachable_serials={"emulator-5554"})

    serials = [i.device_serial for i in out.items]
    assert "emulator-5554" in serials
    assert "10AE7S00HD002JK" not in serials
    assert out.total == 1


@pytest.mark.asyncio
async def test_unfiltered_manage_list_hides_unreachable_registered_devices():
    registered = SimpleNamespace(
        id="id-dead-1",
        serial="dead-1",
        name="Dead phone",
        device_key="key",
        user_id="user-a",
        brand="Samsung",
        model="S22",
        android_version="13",
        sdk_version=33,
        screen_width=1080,
        screen_height=1920,
        last_seen=None,
        created_at=datetime.now(UTC),
        adb_serial=None,
        adb_ip=None,
        adb_port=5555,
    )

    out = await _call_unfiltered(
        devices=[registered],
        state_by_id={registered.id: DeviceFsmState.DEAD.value},
    )

    assert out == []


@pytest.mark.asyncio
async def test_explicit_state_filter_still_returns_dead():
    rows = [_row("10AE7S00HD002JK", DeviceFsmState.DEAD.value)]
    out = await _call(state=DeviceFsmState.DEAD.value, rows=rows, connected_only=False)

    assert [i.device_serial for i in out.items] == ["10AE7S00HD002JK"]


@pytest.mark.asyncio
async def test_direct_device_id_lookup_still_returns_dead():
    rows = [_row("10AE7S00HD002JK", DeviceFsmState.DEAD.value)]
    out = await _call(device_id="id-10AE7S00HD002JK", rows=rows, connected_only=False)

    assert [i.device_serial for i in out.items] == ["10AE7S00HD002JK"]


@pytest.mark.asyncio
async def test_all_online_list_is_unchanged():
    rows = [
        _row("emulator-5554", DeviceFsmState.ONLINE.value),
        _row("emulator-5556", DeviceFsmState.ONLINE.value),
    ]
    out = await _call(rows=rows, reachable_serials={"emulator-5554", "emulator-5556"})

    assert len(out.items) == 2
    assert out.total == 2


@pytest.mark.asyncio
async def test_default_page_empty_when_adb_snapshot_is_empty():
    out = await _call(rows=[_row("10AE7S00HD002JK", DeviceFsmState.ONLINE.value)])

    assert out.items == []
    assert out.total == 0


@pytest.mark.asyncio
async def test_regular_inventory_still_keeps_unreachable_registered_devices():
    out = await _call(
        rows=[_row("10AE7S00HD002JK", DeviceFsmState.DEAD.value)],
        connected_only=False,
    )

    assert [item.device_serial for item in out.items] == ["10AE7S00HD002JK"]
    assert out.total == 1
