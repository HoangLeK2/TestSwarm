"""Tests for relay.u2_executor — batch executor + primitive ops."""
from __future__ import annotations

import asyncio
import base64
import threading
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

import relay.u2_executor as u2_exec_mod
from relay.u2_executor import U2Executor, _resolve
from relay.u2_session_pool import U2SessionPool


@pytest.fixture
def mock_device():
    dev = MagicMock()
    return dev


@pytest.fixture
def executor(event_loop, mock_device):
    pool = AsyncMock()

    async def _run_locked(serial: str, fn):
        return fn(mock_device)

    pool.run_locked = AsyncMock(side_effect=_run_locked)
    pool.get_session = AsyncMock(return_value=mock_device)
    pool.evict = AsyncMock()
    exc = U2Executor(pool=pool, loop=event_loop)
    return exc, mock_device, pool


class _FlowDevice:
    def __init__(self, *hierarchies: str) -> None:
        self._hierarchies = list(hierarchies)
        self.clicks: list[tuple[int, int]] = []
        self.swipes: list[tuple[int, int, int, int, float]] = []
        self.advance_on_click = False

    def dump_hierarchy(self, compressed: bool = False) -> str:
        assert compressed is False
        if len(self._hierarchies) > 1:
            return self._hierarchies.pop(0)
        return self._hierarchies[0]

    def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))
        if self.advance_on_click and len(self._hierarchies) > 1:
            self._hierarchies.pop(0)

    def swipe(
        self,
        fx: int,
        fy: int,
        tx: int,
        ty: int,
        duration: float = 0.5,
    ) -> None:
        self.swipes.append((fx, fy, tx, ty, duration))

    def window_size(self) -> tuple[int, int]:
        return (1080, 2400)


def _fb_xml(*nodes: str) -> str:
    return f"<hierarchy>{''.join(nodes)}</hierarchy>"


def _fb_node(
    label: str,
    *,
    bounds: str,
    clickable: bool = False,
) -> str:
    return (
        f'<node text="{label}" content-desc="{label}" '
        f'clickable="{str(clickable).lower()}" bounds="{bounds}" />'
    )


def test_flow_fb_connect_visible_people_clicks_only_common_context_row(monkeypatch):
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    before = _fb_xml(
        _fb_node("Nguyen Van A", bounds="[40,100][400,145]"),
        _fb_node("3 bạn chung", bounds="[40,146][400,190]"),
        _fb_node("Thêm bạn bè", bounds="[600,120][900,200]", clickable=True),
    )
    after = _fb_xml(
        _fb_node("Nguyen Van A", bounds="[40,100][400,145]"),
        _fb_node("Hủy lời mời", bounds="[600,120][900,200]", clickable=True),
    )
    dev = _FlowDevice(before, after)

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {
            "min_score": 40,
            "require_common": True,
            "common_keywords": ["bạn chung", "cùng nhóm"],
        },
    )

    assert result["verified"] is True
    assert result["source"] == "visible_people_surface"
    assert result["target_id"].startswith("ui:")
    assert "ban chung" in result["matched_common"]
    assert result["selected_tap"] == [750, 160]
    assert dev.clicks == [(750, 160)]


def test_flow_fb_connect_visible_people_does_not_click_without_common_context():
    before = _fb_xml(
        _fb_node("Random Name", bounds="[40,100][400,145]"),
        _fb_node("Thêm bạn bè", bounds="[600,120][900,200]", clickable=True),
    )
    dev = _FlowDevice(before)

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {"min_score": 40, "require_common": True},
    )

    assert result["verified"] is False
    assert result["reason"] == "no_common_connectable_people"
    assert dev.clicks == []


def test_flow_fb_connect_visible_people_batch_sends_multiple_common_rows(monkeypatch):
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    before = _fb_xml(
        _fb_node("Bạn bè", bounds="[20,20][300,80]"),
        _fb_node("Gợi ý", bounds="[20,90][250,150]"),
        _fb_node("Nguyen Van A", bounds="[40,100][400,145]"),
        _fb_node("3 bạn chung", bounds="[40,146][400,190]"),
        _fb_node("Thêm bạn bè", bounds="[600,120][900,200]", clickable=True),
        _fb_node("Tran Van B", bounds="[40,320][400,365]"),
        _fb_node("1 bạn chung", bounds="[40,366][400,410]"),
        _fb_node("Thêm bạn bè", bounds="[600,340][900,420]", clickable=True),
        _fb_node("No Mutual", bounds="[40,540][400,585]"),
        _fb_node("Thêm bạn bè", bounds="[600,560][900,640]", clickable=True),
    )
    after_a = _fb_xml(
        _fb_node("Bạn bè", bounds="[20,20][300,80]"),
        _fb_node("Gợi ý", bounds="[20,90][250,150]"),
        _fb_node("Nguyen Van A", bounds="[40,100][400,145]"),
        _fb_node("Hủy lời mời", bounds="[600,120][900,200]", clickable=True),
        _fb_node("Tran Van B", bounds="[40,320][400,365]"),
        _fb_node("1 bạn chung", bounds="[40,366][400,410]"),
        _fb_node("Thêm bạn bè", bounds="[600,340][900,420]", clickable=True),
    )
    after_b = _fb_xml(
        _fb_node("Bạn bè", bounds="[20,20][300,80]"),
        _fb_node("Gợi ý", bounds="[20,90][250,150]"),
        _fb_node("Tran Van B", bounds="[40,320][400,365]"),
        _fb_node("Hủy lời mời", bounds="[600,340][900,420]", clickable=True),
    )
    dev = _FlowDevice(before, after_a, after_b)

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {
            "target_count": 2,
            "max_scrolls": 0,
            "min_score": 40,
            "require_common": True,
        },
    )

    assert result["verified"] is True
    assert result["batch"] is True
    assert result["sent_count"] == 2
    assert [item["mutual_count"] for item in result["sent"]] == [3, 1]
    assert dev.clicks == [(750, 160), (750, 380)]


def test_flow_fb_connect_visible_people_batch_dry_run_does_not_click(monkeypatch):
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    before = _fb_xml(
        _fb_node("Bạn bè", bounds="[20,20][300,80]"),
        _fb_node("Gợi ý", bounds="[20,90][250,150]"),
        _fb_node("Nguyen Van A", bounds="[40,100][400,145]"),
        _fb_node("3 bạn chung", bounds="[40,146][400,190]"),
        _fb_node("Thêm bạn bè", bounds="[600,120][900,200]", clickable=True),
        _fb_node("Tran Van B", bounds="[40,320][400,365]"),
        _fb_node("1 bạn chung", bounds="[40,366][400,410]"),
        _fb_node("Thêm bạn bè", bounds="[600,340][900,420]", clickable=True),
    )
    dev = _FlowDevice(before)

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {
            "target_count": 2,
            "max_scrolls": 0,
            "dry_run": True,
            "min_score": 40,
            "require_common": True,
        },
    )

    assert result["verified"] is False
    assert result["reason"] == "dry_run"
    assert result["eligible_count"] == 2
    assert result["sent_count"] == 0
    assert dev.clicks == []


def test_flow_fb_connect_visible_people_dedupes_same_person_after_scroll(monkeypatch):
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    first_screen = _fb_xml(
        _fb_node("Bạn bè", bounds="[20,20][300,80]"),
        _fb_node("Cu Minh", bounds="[40,100][400,145]"),
        _fb_node("1 bạn chung", bounds="[40,146][400,190]"),
        _fb_node("Thêm bạn bè", bounds="[600,120][900,200]", clickable=True),
    )
    overlapped_scroll = _fb_xml(
        _fb_node("Bạn bè", bounds="[20,20][300,80]"),
        _fb_node("Cu Minh", bounds="[40,260][400,305]"),
        _fb_node("1 bạn chung", bounds="[40,306][400,350]"),
        _fb_node("Bạn bè Bạn bè", bounds="[40,351][400,390]"),
        _fb_node("Thêm bạn bè", bounds="[600,280][900,360]", clickable=True),
    )
    dev = _FlowDevice(first_screen, overlapped_scroll)

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {
            "target_count": 2,
            "max_scrolls": 1,
            "dry_run": True,
            "min_score": 40,
            "require_common": True,
        },
    )

    assert result["reason"] == "dry_run"
    assert result["eligible_count"] == 1
    assert [item["display_name"] for item in result["eligible"]] == ["Cu Minh"]
    assert dev.clicks == []


def test_flow_fb_connect_visible_people_stops_after_unverified_tap(monkeypatch):
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    before = _fb_xml(
        _fb_node("Nguyen Van A", bounds="[40,100][400,145]"),
        _fb_node("3 bạn chung", bounds="[40,146][400,190]"),
        _fb_node("Thêm bạn bè", bounds="[600,120][900,200]", clickable=True),
        _fb_node("Tran Van B", bounds="[40,320][400,365]"),
        _fb_node("1 bạn chung", bounds="[40,366][400,410]"),
        _fb_node("Thêm bạn bè", bounds="[600,340][900,420]", clickable=True),
    )
    unchanged_after_tap = before
    dev = _FlowDevice(before, unchanged_after_tap)

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {
            "target_count": 2,
            "max_scrolls": 0,
            "min_score": 40,
            "require_common": True,
        },
    )

    assert result["verified"] is False
    assert result["reason"] == "request_not_verified"
    assert result["sent_count"] == 0
    assert result["eligible_count"] == 1
    assert len(result["skipped"]) == 1
    assert dev.clicks == [(750, 160)]


def test_flow_fb_connect_visible_people_opens_find_friends_surface(monkeypatch):
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    home = _fb_xml(_fb_node("Menu", bounds="[40,180][140,260]"))
    menu = _fb_xml(
        _fb_node("Menu", bounds="[20,20][200,80]"),
        _fb_node("Xem thêm", bounds="[70,900][440,980]"),
    )
    expanded = _fb_xml(
        _fb_node("Menu", bounds="[20,20][200,80]"),
        _fb_node("Tìm bạn bè", bounds="[70,1180][500,1260]"),
    )
    suggestions = _fb_xml(
        _fb_node("Bạn bè", bounds="[20,20][300,80]"),
        _fb_node("Gợi ý", bounds="[20,90][250,150]"),
        _fb_node("Nguyen Van A", bounds="[40,300][400,345]"),
        _fb_node("2 bạn chung", bounds="[40,346][400,390]"),
        _fb_node("Thêm bạn bè", bounds="[600,320][900,400]", clickable=True),
    )
    dev = _FlowDevice(home, menu, expanded, suggestions)

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {
            "open_surface": True,
            "target_count": 1,
            "dry_run": True,
            "min_score": 40,
            "require_common": True,
        },
    )

    assert result["reason"] == "dry_run"
    assert result["eligible_count"] == 1
    assert result["surface"]["ready"] is True
    assert dev.clicks[:3] == [(90, 208), (255, 940), (285, 1220)]


def test_flow_fb_connect_visible_people_closes_detail_before_opening_surface(
    monkeypatch,
):
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    detail = _fb_xml(
        _fb_node("Đóng", bounds="[35,147][161,273]", clickable=True),
        _fb_node("Bài viết của Some Page", bounds="[60,360][700,430]"),
    )
    home = _fb_xml(_fb_node("Menu", bounds="[40,180][140,260]"))
    menu = _fb_xml(
        _fb_node("Menu", bounds="[20,20][200,80]"),
        _fb_node("Tìm bạn bè", bounds="[70,1180][500,1260]"),
    )
    suggestions = _fb_xml(
        _fb_node("Bạn bè", bounds="[20,20][300,80]"),
        _fb_node("Gợi ý", bounds="[20,90][250,150]"),
        _fb_node("Nguyen Van A", bounds="[40,300][400,345]"),
        _fb_node("2 bạn chung", bounds="[40,346][400,390]"),
        _fb_node("Thêm bạn bè", bounds="[600,320][900,400]", clickable=True),
    )
    dev = _FlowDevice(detail, home, menu, suggestions)

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {
            "open_surface": True,
            "target_count": 1,
            "dry_run": True,
            "min_score": 40,
            "require_common": True,
        },
    )

    assert result["reason"] == "dry_run"
    assert result["eligible_count"] == 1
    assert result["surface"]["attempts"][:3] == [
        "close_detail_overlay",
        "tap_menu",
        "tap_find_friends",
    ]
    assert dev.clicks[:3] == [(98, 210), (90, 208), (285, 1220)]


# ── Batch tests ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_batch_empty(executor):
    exc, dev, pool = executor
    result = await exc.run_batch("serial", [], early_exit=True)
    assert result["ok"] is True
    assert result["results"] == []
    pool.run_locked.assert_not_called()


@pytest.mark.asyncio
async def test_run_batch_click_success(executor):
    exc, dev, pool = executor
    assert exc.ui_generation("serial") == 0
    result = await exc.run_batch("serial", [
        {"op": "click", "x": 100, "y": 200},
    ])
    assert result["ok"] is True
    assert len(result["results"]) == 1
    assert result["results"][0]["op"] == "click"
    assert result["results"][0]["ok"] is True
    assert result["total_ms"] >= 0
    assert result["results"][0]["duration_ms"] >= 0
    dev.click.assert_called_once_with(100, 200)
    assert exc.ui_generation("serial") == 2
    assert exc.ui_mutation_in_flight("serial") == 0


@pytest.mark.asyncio
async def test_run_batch_press_key_falls_back_to_adb_home_intent(executor, monkeypatch):
    exc, dev, pool = executor
    dev.press.side_effect = RuntimeError("JSON-RPC HTTP 502")
    adb_calls: list[tuple[str, str, int]] = []

    def fake_adb_shell(serial: str, cmd: str, timeout: int = 5):
        adb_calls.append((serial, cmd, timeout))
        return "", 0

    monkeypatch.setattr(u2_exec_mod, "_adb_shell", fake_adb_shell)

    result = await exc.run_batch("serial-1", [
        {"op": "press_key", "key": "home"},
    ])

    assert result["ok"] is True
    assert result["results"][0]["ok"] is True
    dev.press.assert_called_once_with("home")
    assert adb_calls == [
        ("serial-1", "am start -a android.intent.action.MAIN -c android.intent.category.HOME", 5)
    ]
    assert exc.ui_mutation_in_flight("serial-1") == 0


@pytest.mark.asyncio
async def test_run_batch_http_direct_touch_avoids_u2_session_lock(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    calls: list[dict] = []

    def http_rpc(_serial: str, payload: dict, _timeout: float) -> tuple[bool, str]:
        calls.append(payload)
        return True, ""

    exc = U2Executor(pool=pool, loop=event_loop, http_rpc=http_rpc)

    result = await exc.run_batch(
        "serial",
        [
            {"op": "click", "x": 100, "y": 200},
            {"op": "sleep", "seconds": 0},
            {"op": "swipe", "fx": 10, "fy": 20, "tx": 30, "ty": 40, "duration": 0.12},
        ],
    )

    assert result["ok"] is True
    assert [call["method"] for call in calls] == ["click", "swipe"]
    assert calls[0]["params"] == [100, 200]
    assert calls[1]["params"] == [10, 20, 30, 40, 4]
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["http_direct_batches"] == 1
    assert stats["http_direct_actions"] == 3
    assert exc.ui_generation("serial") == 2


@pytest.mark.asyncio
async def test_run_batch_http_direct_touch_early_exits_on_rpc_error(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    calls = 0

    def http_rpc(_serial: str, _payload: dict, _timeout: float) -> tuple[bool, str]:
        nonlocal calls
        calls += 1
        return False, "boom"

    exc = U2Executor(pool=pool, loop=event_loop, http_rpc=http_rpc)

    result = await exc.run_batch(
        "serial",
        [
            {"op": "click", "x": 100, "y": 200},
            {"op": "click", "x": 300, "y": 400},
        ],
    )

    assert result["ok"] is False
    assert result["stopped_at"] == 0
    assert result["results"][0]["error"] == "boom"
    assert calls == 1
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["http_direct_batches"] == 1
    assert stats["http_direct_failures"] == 1


@pytest.mark.asyncio
async def test_run_batch_click_spec_xpath_bounds_uses_http_direct(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    calls: list[dict] = []

    def http_rpc(_serial: str, payload: dict, _timeout: float) -> tuple[bool, str]:
        calls.append(payload)
        return True, ""

    exc = U2Executor(pool=pool, loop=event_loop, http_rpc=http_rpc)

    result = await exc.run_batch(
        "serial",
        [
            {
                "op": "click_spec",
                "spec": {"xpath": '//*[@bounds="[100,200][300,250]"]'},
            },
        ],
    )

    assert result["ok"] is True
    assert calls == [
        {"jsonrpc": "2.0", "method": "click", "id": 1, "params": [200, 225]}
    ]
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["click_spec_http_direct"] == 1
    assert stats["click_spec_http_direct_bounds"] == 1
    assert stats["http_direct_batches"] == 1


@pytest.mark.asyncio
async def test_run_batch_read_only_actions_do_not_advance_ui_generation(executor):
    exc, dev, pool = executor
    ui_obj = MagicMock()
    ui_obj.exists = True
    dev.return_value = ui_obj

    await exc.run_batch("serial", [
        {"op": "exists", "selector": {"text": "OK"}},
        {"op": "sleep", "seconds": 0},
    ])

    assert exc.ui_generation("serial") == 0


@pytest.mark.asyncio
async def test_run_batch_mutation_is_marked_in_flight_until_completion(executor):
    exc, dev, pool = executor
    started = asyncio.Event()
    release = asyncio.Event()

    async def _run_locked(serial: str, fn):
        started.set()
        await release.wait()
        return fn(dev)

    pool.run_locked = AsyncMock(side_effect=_run_locked)
    task = asyncio.create_task(
        exc.run_batch(
            "serial",
            [{"op": "click", "x": 100, "y": 200}],
        )
    )
    await asyncio.wait_for(started.wait(), timeout=0.5)

    assert exc.ui_generation("serial") == 1
    assert exc.ui_mutation_in_flight("serial") == 1

    release.set()
    result = await asyncio.wait_for(task, timeout=0.5)

    assert result["ok"] is True
    assert exc.ui_generation("serial") == 2
    assert exc.ui_mutation_in_flight("serial") == 0


@pytest.mark.asyncio
async def test_run_batch_exists_returns_value(executor):
    exc, dev, pool = executor
    ui_obj = MagicMock()
    ui_obj.exists = True
    dev.return_value = ui_obj

    result = await exc.run_batch("serial", [
        {"op": "exists", "selector": {"text": "OK"}},
    ])
    assert result["ok"] is True
    assert result["results"][0]["value"] is True


@pytest.mark.asyncio
async def test_run_batch_early_exit(executor):
    exc, dev, pool = executor

    # click succeeds, get_text fails (selector not found)
    ui_obj = MagicMock()
    ui_obj.exists = False
    dev.return_value = ui_obj

    result = await exc.run_batch("serial", [
        {"op": "click", "x": 10, "y": 20},
        {"op": "get_text", "selector": {"text": "missing"}},
        {"op": "click", "x": 30, "y": 40},
    ], early_exit=True)

    assert result["ok"] is False
    assert result["stopped_at"] == 1
    assert len(result["results"]) == 2
    # Third action should NOT have been called
    assert dev.click.call_count == 1


@pytest.mark.asyncio
async def test_run_batch_no_early_exit(executor):
    """With early_exit=False, all actions run even if some fail."""
    exc, dev, pool = executor

    ui_obj = MagicMock()
    ui_obj.exists = False
    dev.return_value = ui_obj

    result = await exc.run_batch("serial", [
        {"op": "click", "x": 10, "y": 20},
        {"op": "get_text", "selector": {"text": "missing"}},
        {"op": "click", "x": 30, "y": 40},
    ], early_exit=False)

    assert len(result["results"]) == 3
    assert result["results"][0]["ok"] is True
    assert result["results"][1]["ok"] is False
    assert result["results"][2]["ok"] is True


@pytest.mark.asyncio
async def test_unknown_op_fails_cleanly(executor):
    exc, dev, pool = executor
    result = await exc.run_batch("serial", [
        {"op": "nonexistent"},
    ])
    assert result["ok"] is False
    assert result["stopped_at"] == 0
    assert "unknown op" in result["results"][0]["error"]
    assert result["total_ms"] >= 0
    assert result["results"][0]["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_session_unavailable(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock(side_effect=RuntimeError("no device"))
    pool.evict = AsyncMock()
    exc = U2Executor(pool=pool, loop=event_loop)

    result = await exc.run_batch("serial", [{"op": "click", "x": 1, "y": 2}])
    assert result["ok"] is False
    assert result["stopped_at"] == 0
    # Phase 2 moved get_session into the per-action loop so errors are attributed
    # to the specific action that tried to acquire the session.
    assert "no device" in result["error"]


@pytest.mark.asyncio
async def test_dump_hierarchy_forwards_optional_dump_kwargs(event_loop, mock_device):
    pool = AsyncMock()

    async def _run_locked(serial: str, fn):
        return fn(mock_device)

    pool.run_locked = AsyncMock(side_effect=_run_locked)
    pool.evict = AsyncMock()
    mock_device.dump_hierarchy.return_value = "<hierarchy />"
    exc = U2Executor(pool=pool, loop=event_loop)

    result = await exc.run_batch(
        "serial",
        [{"op": "dump_hierarchy", "compressed": True, "pretty": True, "max_depth": 20}],
    )

    assert result["ok"] is True
    assert result["results"][0]["value"] == "<hierarchy />"
    mock_device.dump_hierarchy.assert_called_once_with(compressed=True, pretty=True, max_depth=20)


@pytest.mark.asyncio
async def test_dump_hierarchy_prefers_http_dump(event_loop, mock_device):
    pool = AsyncMock()

    async def _run_locked(serial: str, fn):
        return fn(mock_device)

    pool.run_locked = AsyncMock(side_effect=_run_locked)
    xml = '<?xml version="1.0"?><hierarchy><node /></hierarchy>'
    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=lambda _s, _t, _c: xml,
    )
    result = await exc.run_batch("serial", [{"op": "dump_hierarchy", "timeout": 5.0}])
    assert result["ok"] is True
    assert result["results"][0]["value"] == xml
    mock_device.dump_hierarchy.assert_not_called()


@pytest.mark.asyncio
async def test_direct_http_dump_marks_pool_health(event_loop, mock_device):
    xml = "<hierarchy />"
    pool = U2SessionPool(loop=event_loop, connect_fn=MagicMock(return_value=mock_device))
    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=lambda _s, _t, _c: xml,
    )

    result = await exc.run_batch("serial", [{"op": "dump_hierarchy", "timeout": 5.0}])

    assert result["ok"] is True
    stats = pool.stats_snapshot(reset=False)
    assert stats["direct_http_health_marks"] == 1
    assert stats["direct_http_healthy_serials"] == 1


@pytest.mark.asyncio
async def test_dump_hierarchy_singleflight_deduplicates_concurrent_http_dump(event_loop):
    pool = AsyncMock()
    pool.evict = AsyncMock()
    xml = '<?xml version="1.0"?><hierarchy><node /></hierarchy>'
    started = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal calls
        with calls_lock:
            calls += 1
        started.set()
        release.wait(timeout=1.0)
        return xml

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)
    first = asyncio.create_task(
        exc.run_batch("serial", [{"op": "dump_hierarchy", "timeout": 5.0}])
    )
    while not started.is_set():
        await asyncio.sleep(0)
    joined = [
        asyncio.create_task(
            exc.run_batch("serial", [{"op": "dump_hierarchy", "timeout": 5.0}])
        )
        for _index in range(5)
    ]
    await asyncio.sleep(0)
    release.set()

    results = await asyncio.gather(first, *joined)

    assert calls == 1
    assert all(result["ok"] is True for result in results)
    assert all(result["results"][0]["value"] == xml for result in results)
    stats = exc.stats_snapshot(reset=False)
    assert stats["dump_singleflight_leaders"] == 1
    assert stats["dump_singleflight_joins"] == 5
    assert stats["dump_background_singleflight_leaders"] == 1
    assert stats["dump_background_singleflight_joins"] == 5
    assert stats["hierarchy_background_requests"] == 6
    assert stats["hierarchy_background_success"] == 6
    pool.run_locked.assert_not_called()


@pytest.mark.asyncio
async def test_dump_hierarchy_singleflight_is_scoped_by_visible_lane(event_loop):
    pool = AsyncMock()
    pool.evict = AsyncMock()
    started = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal calls
        with calls_lock:
            calls += 1
            call_no = calls
        if call_no == 1:
            started.set()
            release.wait(timeout=5.0)
        return (
            f'<?xml version="1.0"?><hierarchy><node text="{call_no}" /></hierarchy>'
        )

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)
    background = asyncio.create_task(
        exc.run_batch("serial", [{"op": "dump_hierarchy", "timeout": 5.0}])
    )
    while not started.is_set():
        await asyncio.sleep(0)

    visible = asyncio.create_task(
        exc.run_batch(
            "serial",
            [{"op": "dump_hierarchy", "timeout": 5.0}],
            priority="visible",
        )
    )
    for _index in range(100):
        with calls_lock:
            if calls >= 2:
                break
        await asyncio.sleep(0.01)

    visible_result = await asyncio.wait_for(visible, timeout=1.0)
    assert background.done() is False
    release.set()
    background_result = await background

    assert calls == 2
    assert background_result["ok"] is True
    assert visible_result["ok"] is True
    assert 'text="1"' in background_result["results"][0]["value"]
    assert 'text="2"' in visible_result["results"][0]["value"]
    stats = exc.stats_snapshot(reset=False)
    assert stats["dump_background_singleflight_leaders"] == 1
    assert stats["dump_visible_singleflight_leaders"] == 1
    assert stats["dump_singleflight_joins"] == 0
    assert stats["hierarchy_background_requests"] == 1
    assert stats["hierarchy_visible_requests"] == 1
    assert stats["hierarchy_background_success"] == 1
    assert stats["hierarchy_visible_success"] == 1


@pytest.mark.asyncio
async def test_background_dump_deadline_grace_allows_near_complete_singleflight(
    event_loop,
    monkeypatch,
):
    monkeypatch.setattr(u2_exec_mod, "U2_BACKGROUND_DUMP_DEADLINE_GRACE_MS", 200)
    pool = AsyncMock()
    pool.evict = AsyncMock()
    xml = '<?xml version="1.0"?><hierarchy><node /></hierarchy>'
    started = threading.Event()
    release = threading.Event()

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        started.set()
        release.wait(timeout=1.0)
        return xml

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)
    task = asyncio.create_task(
        exc.run_batch(
            "serial",
            [{"op": "dump_hierarchy", "timeout": 5.0}],
            priority="background",
            deadline_ms=20,
        )
    )
    while not started.is_set():
        await asyncio.sleep(0)
    await asyncio.sleep(0.05)
    release.set()

    result = await asyncio.wait_for(task, timeout=1.0)

    assert result["ok"] is True
    assert result["results"][0]["value"] == xml
    stats = exc.stats_snapshot(reset=False)
    assert stats["background_dump_deadline_grace_applied"] == 2
    assert stats["background_deadline_drops"] == 0


@pytest.mark.asyncio
async def test_visible_dump_deadline_is_not_extended_by_background_grace(
    event_loop,
    monkeypatch,
):
    monkeypatch.setattr(u2_exec_mod, "U2_BACKGROUND_DUMP_DEADLINE_GRACE_MS", 200)
    pool = AsyncMock()
    pool.evict = AsyncMock()
    started = threading.Event()
    release = threading.Event()

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        started.set()
        release.wait(timeout=1.0)
        return '<?xml version="1.0"?><hierarchy><node /></hierarchy>'

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)
    task = asyncio.create_task(
        exc.run_batch(
            "serial",
            [{"op": "dump_hierarchy", "timeout": 5.0}],
            priority="visible",
            deadline_ms=20,
        )
    )
    while not started.is_set():
        await asyncio.sleep(0)

    result = await asyncio.wait_for(task, timeout=1.0)
    release.set()

    assert result["ok"] is False
    assert "deadline exceeded while waiting for dump_hierarchy" in result["error"]
    stats = exc.stats_snapshot(reset=False)
    assert stats["background_dump_deadline_grace_applied"] == 0
    assert stats["visible_deadline_drops"] == 1


def test_background_dump_deadline_grace_scales_with_waiting_backlog(
    event_loop,
    monkeypatch,
):
    monkeypatch.setattr(u2_exec_mod, "U2_BACKGROUND_DUMP_DEADLINE_GRACE_MS", 100)
    monkeypatch.setattr(
        u2_exec_mod,
        "U2_BACKGROUND_DUMP_DEADLINE_GRACE_PER_WAVE_MS",
        10,
    )
    monkeypatch.setattr(u2_exec_mod, "U2_EXECUTOR_BACKGROUND_CONCURRENCY", 4)
    monkeypatch.setattr(u2_exec_mod, "U2_EXECUTOR_CONCURRENCY", 8)
    pool = AsyncMock()
    pool.evict = AsyncMock()
    exc = U2Executor(pool=pool, loop=event_loop)
    exc._background_waiting = 9

    deadline = exc._single_dump_deadline_ms(1000, priority="background")

    assert deadline == 1130
    stats = exc.stats_snapshot(reset=False)
    assert stats["background_dump_deadline_grace_applied"] == 1


@pytest.mark.asyncio
async def test_concurrent_wait_exists_same_selector_coalesces_xml_poll(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="Ready" resource-id="com.app:id/ready" />
    </hierarchy>
    """
    started = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal calls
        with calls_lock:
            calls += 1
        started.set()
        release.wait(timeout=1.0)
        return xml

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)
    action = {
        "op": "wait_exists",
        "selector": {"resourceId": "com.app:id/ready"},
        "timeout": 5.0,
    }
    first = asyncio.create_task(exc.run_batch("serial", [action], priority="visible"))
    while not started.is_set():
        await asyncio.sleep(0)
    joined = [
        asyncio.create_task(exc.run_batch("serial", [action], priority="visible"))
        for _index in range(5)
    ]
    await asyncio.sleep(0)
    release.set()

    results = await asyncio.gather(first, *joined)

    assert calls == 1
    assert all(result["ok"] is True for result in results)
    assert all(result["results"][0]["value"] is True for result in results)
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["xml_poll_coalesced_leaders"] == 1
    assert stats["xml_poll_coalesced_joins"] == 5
    assert stats["http_wait_batches"] == 6
    assert stats["http_wait_polls"] == 1


@pytest.mark.asyncio
async def test_visible_wait_does_not_coalesce_with_background_wait(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="Ready" resource-id="com.app:id/ready" />
    </hierarchy>
    """
    started = threading.Event()
    release = threading.Event()

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        started.set()
        release.wait(timeout=1.0)
        return xml

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)
    action = {
        "op": "wait_exists",
        "selector": {"resourceId": "com.app:id/ready"},
        "timeout": 5.0,
    }
    visible = asyncio.create_task(exc.run_batch("serial", [action], priority="visible"))
    while not started.is_set():
        await asyncio.sleep(0)
    background = asyncio.create_task(exc.run_batch("serial", [action], priority="background"))
    await asyncio.sleep(0)
    release.set()

    results = await asyncio.gather(visible, background)

    assert all(result["ok"] is True for result in results)
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["xml_poll_coalesced_leaders"] == 2
    assert stats["xml_poll_coalesced_joins"] == 0


@pytest.mark.asyncio
async def test_dump_hierarchy_cache_reuses_short_ttl(event_loop):
    pool = AsyncMock()
    pool.evict = AsyncMock()
    calls = 0

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal calls
        calls += 1
        return f"<?xml version='1.0'?><hierarchy><node text='{calls}' /></hierarchy>"

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)

    first = await exc.run_batch("serial", [{"op": "dump_hierarchy"}])
    second = await exc.run_batch("serial", [{"op": "dump_hierarchy"}])

    assert calls == 1
    assert first["results"][0]["value"] == second["results"][0]["value"]
    stats = exc.stats_snapshot(reset=False)
    assert stats["dump_cache_hits"] == 1
    assert stats["dump_cache_stores"] >= 1


@pytest.mark.asyncio
async def test_dump_hierarchy_force_fresh_bypasses_short_ttl_cache(event_loop):
    pool = AsyncMock()
    pool.evict = AsyncMock()
    calls = 0

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal calls
        calls += 1
        return f"<?xml version='1.0'?><hierarchy><node text='{calls}' /></hierarchy>"

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)

    first = await exc.run_batch("serial", [{"op": "dump_hierarchy"}])
    second = await exc.run_batch("serial", [{"op": "dump_hierarchy", "force_fresh_xml": True}])

    assert calls == 2
    assert first["results"][0]["value"] != second["results"][0]["value"]
    stats = exc.stats_snapshot(reset=False)
    assert stats["dump_cache_hits"] == 0
    assert stats["dump_cache_stores"] >= 2


@pytest.mark.asyncio
async def test_dump_then_exists_get_text_reuses_xml_without_u2_lock(event_loop):
    pool = AsyncMock()
    pool.evict = AsyncMock()
    calls = 0
    xml = """<?xml version='1.0'?>
    <hierarchy>
      <node index="0" text="Login" resource-id="com.app:id/login" class="android.widget.TextView" />
      <node index="1" text="Cancel" content-desc="Cancel button" enabled="true" />
    </hierarchy>
    """

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal calls
        calls += 1
        return xml

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)

    result = await exc.run_batch(
        "serial",
        [
            {"op": "dump_hierarchy"},
            {"op": "exists", "selector": {"text": "Login"}},
            {"op": "get_text", "selector": {"resourceId": "com.app:id/login"}},
            {"op": "exists", "selector": {"descriptionContains": "Cancel"}},
        ],
    )

    assert result["ok"] is True
    assert calls == 1
    assert result["results"][1]["value"] is True
    assert result["results"][2]["value"] == "Login"
    assert result["results"][3]["value"] is True
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["xml_batch_optimized"] == 1
    assert stats["xml_parse_lxml"] == 1
    assert stats["xml_index_builds"] == 1
    assert stats["xml_u2_calls_avoided"] == 3
    assert stats["xml_selector_hits"] == 3


@pytest.mark.asyncio
async def test_xml_selector_lookup_cache_reuses_same_selector_on_same_index(event_loop):
    pool = AsyncMock()
    pool.evict = AsyncMock()
    xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="Login" resource-id="com.app:id/login" class="android.widget.TextView" />
    </hierarchy>
    """

    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=lambda _s, _t, _c: xml,
    )

    result = await exc.run_batch(
        "serial",
        [
            {"op": "dump_hierarchy"},
            {"op": "exists", "selector": {"resourceId": "com.app:id/login"}},
            {"op": "get_text", "selector": {"resourceId": "com.app:id/login"}},
            {"op": "exists", "selector": {"resourceId": "com.app:id/login"}},
        ],
    )

    assert result["ok"] is True
    assert result["results"][1]["value"] is True
    assert result["results"][2]["value"] == "Login"
    assert result["results"][3]["value"] is True
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["xml_selector_cache_stores"] == 1
    assert stats["xml_selector_cache_hits"] == 2


@pytest.mark.asyncio
async def test_xml_index_cache_reuses_parsed_dump_across_batches(event_loop):
    pool = AsyncMock()
    pool.evict = AsyncMock()
    dump_calls = 0
    xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="Login" resource-id="com.app:id/login" bounds="[100,200][200,250]" />
    </hierarchy>
    """

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal dump_calls
        dump_calls += 1
        return xml

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)
    actions = [
        {"op": "dump_hierarchy"},
        {"op": "exists", "selector": {"resourceId": "com.app:id/login"}},
    ]

    first = await exc.run_batch("serial", actions)
    second = await exc.run_batch("serial", actions)

    assert first["ok"] is True
    assert second["ok"] is True
    assert dump_calls == 1
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["dump_cache_hits"] == 1
    assert stats["xml_parse_lxml"] == 1
    assert stats["xml_index_builds"] == 1
    assert stats["xml_index_cache_hits"] == 1
    assert stats["xml_index_cache_stores"] == 1


@pytest.mark.asyncio
async def test_xml_index_cache_survives_bypass_when_dump_content_same(event_loop):
    pool = AsyncMock()
    pool.evict = AsyncMock()
    dump_calls = 0
    xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="Ready" resource-id="com.app:id/ready" />
    </hierarchy>
    """

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal dump_calls
        dump_calls += 1
        return xml

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)
    act = {"op": "dump_hierarchy", "timeout": 0.1}
    key = exc._single_dump_cache_key("serial", act)

    first = await exc._run_single_dump_batch(
        serial="serial",
        act=act,
        early_exit=True,
        priority="visible",
        deadline_ms=None,
        batch_started=0.0,
        bypass_cache=True,
    )
    first_index = exc._xml_index_from_dump(
        key,
        str(first["results"][0]["value"] or ""),
        priority="visible",
    )
    second = await exc._run_single_dump_batch(
        serial="serial",
        act=act,
        early_exit=True,
        priority="visible",
        deadline_ms=None,
        batch_started=0.0,
        bypass_cache=True,
    )
    second_index = exc._xml_index_from_dump(
        key,
        str(second["results"][0]["value"] or ""),
        priority="visible",
    )

    assert first_index is second_index
    assert dump_calls == 2
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["xml_parse_lxml"] == 1
    assert stats["xml_index_builds"] == 1
    assert stats["xml_index_cache_hits"] == 1


@pytest.mark.asyncio
async def test_dump_then_click_selector_uses_xml_bounds_http_direct(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    dump_calls = 0
    rpc_calls: list[dict] = []
    xml = """<?xml version='1.0'?>
    <hierarchy>
      <node index="0" text="Login" resource-id="com.app:id/login"
            class="android.widget.Button" clickable="true" bounds="[100,200][200,250]" />
    </hierarchy>
    """

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal dump_calls
        dump_calls += 1
        return xml

    def http_rpc(_serial: str, payload: dict, _timeout: float) -> tuple[bool, str]:
        rpc_calls.append(payload)
        return True, ""

    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=http_dump,
        http_rpc=http_rpc,
    )

    result = await exc.run_batch(
        "serial",
        [
            {"op": "dump_hierarchy"},
            {"op": "exists", "selector": {"text": "Login"}},
            {"op": "click_selector", "selector": {"resourceId": "com.app:id/login"}},
        ],
    )

    assert result["ok"] is True
    assert result["results"][1]["value"] is True
    assert result["results"][2]["value"] is True
    assert dump_calls == 1
    assert rpc_calls == [
        {"jsonrpc": "2.0", "method": "click", "id": 1, "params": [150, 225]}
    ]
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["xml_batch_optimized"] == 1
    assert stats["xml_click_fused"] == 1
    assert stats["http_direct_actions"] == 1
    assert stats["xml_u2_calls_avoided"] == 2
    assert exc.ui_generation("serial") == 2


@pytest.mark.asyncio
async def test_dump_then_click_selector_missing_returns_false_without_rpc(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    rpc_calls: list[dict] = []

    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=lambda _s, _t, _c: "<?xml version='1.0'?><hierarchy />",
        http_rpc=lambda _s, payload, _t: (rpc_calls.append(payload) is None, ""),
    )

    result = await exc.run_batch(
        "serial",
        [
            {"op": "dump_hierarchy"},
            {"op": "click_selector", "selector": {"text": "Missing"}},
        ],
    )

    assert result["ok"] is True
    assert result["results"][1]["value"] is False
    assert rpc_calls == []
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["xml_click_misses"] == 1


@pytest.mark.asyncio
async def test_dump_then_click_spec_uses_xml_index_and_http_direct(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    rpc_calls: list[dict] = []
    xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="Confirm" class="android.widget.Button" clickable="true"
            bounds="[40,1000][240,1080]" />
    </hierarchy>
    """

    def http_rpc(_serial: str, payload: dict, _timeout: float) -> tuple[bool, str]:
        rpc_calls.append(payload)
        return True, ""

    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=lambda _s, _t, _c: xml,
        http_rpc=http_rpc,
    )

    result = await exc.run_batch(
        "serial",
        [
            {"op": "dump_hierarchy"},
            {"op": "click_spec", "spec": {"by": "text", "value": "Confirm"}},
        ],
    )

    assert result["ok"] is True
    assert result["results"][1]["value"] is True
    assert rpc_calls == [
        {"jsonrpc": "2.0", "method": "click", "id": 1, "params": [140, 1040]}
    ]
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["xml_click_fused"] == 1
    assert stats["click_spec_http_direct"] == 1
    assert stats["click_spec_http_direct_bounds"] == 0
    assert stats["xml_selector_hits"] == 1


@pytest.mark.asyncio
async def test_wait_exists_uses_http_dump_poll_without_u2_lock(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    dump_calls = 0
    xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="Ready" resource-id="com.app:id/ready" bounds="[10,20][110,60]" />
    </hierarchy>
    """

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal dump_calls
        dump_calls += 1
        return xml

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)

    result = await exc.run_batch(
        "serial",
        [{"op": "wait_exists", "selector": {"resourceId": "com.app:id/ready"}, "timeout": 0.1}],
    )

    assert result["ok"] is True
    assert result["results"][0]["value"] is True
    assert result["results"][0]["polls"] == 1
    assert dump_calls == 1
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["http_wait_batches"] == 1
    assert stats["http_wait_hits"] == 1
    assert stats["http_wait_polls"] == 1


@pytest.mark.asyncio
async def test_wait_exists_spec_uses_http_dump_poll_without_u2_lock(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="Confirm" class="android.widget.Button" bounds="[40,1000][240,1080]" />
    </hierarchy>
    """

    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=lambda _s, _t, _c: xml,
    )

    result = await exc.run_batch(
        "serial",
        [{"op": "wait_exists_spec", "spec": {"by": "text", "value": "Confirm"}, "timeout": 0.1}],
    )

    assert result["ok"] is True
    assert result["results"][0]["value"] is True
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["http_wait_batches"] == 1
    assert stats["http_wait_hits"] == 1


@pytest.mark.asyncio
async def test_wait_exists_http_poll_returns_false_on_timeout(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()

    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=lambda _s, _t, _c: "<?xml version='1.0'?><hierarchy />",
    )

    result = await exc.run_batch(
        "serial",
        [{"op": "wait_exists", "selector": {"text": "Missing"}, "timeout": 0.0}],
    )

    assert result["ok"] is True
    assert result["results"][0]["value"] is False
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["http_wait_misses"] == 1


@pytest.mark.asyncio
async def test_wait_gone_uses_http_dump_poll_without_u2_lock(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    xmls = [
        """<?xml version='1.0'?>
        <hierarchy>
          <node text="Loading" resource-id="com.app:id/loading" />
        </hierarchy>
        """,
        "<?xml version='1.0'?><hierarchy />",
    ]
    dump_calls = 0

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal dump_calls
        dump_calls += 1
        return xmls[min(dump_calls - 1, len(xmls) - 1)]

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)

    result = await exc.run_batch(
        "serial",
        [
            {
                "op": "wait_gone",
                "selector": {"resourceId": "com.app:id/loading"},
                "timeout": 0.15,
            }
        ],
        priority="visible",
    )

    assert result["ok"] is True
    assert result["results"][0]["value"] is True
    assert result["results"][0]["polls"] == 2
    assert dump_calls == 2
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["http_wait_batches"] == 1
    assert stats["http_wait_hits"] == 1
    assert stats["http_wait_polls"] == 2


@pytest.mark.asyncio
async def test_wait_exists_poll_bypasses_cache_after_first_poll(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    xmls = [
        "<?xml version='1.0'?><hierarchy />",
        """<?xml version='1.0'?>
        <hierarchy>
          <node text="Ready" resource-id="com.app:id/ready" />
        </hierarchy>
        """,
    ]
    dump_calls = 0

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal dump_calls
        dump_calls += 1
        return xmls[min(dump_calls - 1, len(xmls) - 1)]

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)

    result = await exc.run_batch(
        "serial",
        [
            {
                "op": "wait_exists",
                "selector": {"resourceId": "com.app:id/ready"},
                "timeout": 0.15,
            }
        ],
        priority="visible",
    )

    assert result["ok"] is True
    assert result["results"][0]["value"] is True
    assert result["results"][0]["polls"] == 2
    assert dump_calls == 2
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["http_wait_hits"] == 1
    assert stats["dump_cache_hits"] == 0


@pytest.mark.asyncio
async def test_xml_batch_optimizer_falls_back_for_xpath_selector(event_loop, mock_device):
    pool = AsyncMock()

    async def _run_locked(serial: str, fn):
        return fn(mock_device)

    pool.run_locked = AsyncMock(side_effect=_run_locked)
    pool.evict = AsyncMock()
    mock_device.dump_hierarchy.return_value = "<hierarchy />"
    xpath_obj = MagicMock()
    xpath_obj.exists = True
    mock_device.xpath.return_value = xpath_obj

    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=lambda _s, _t, _c: "<hierarchy />",
    )

    result = await exc.run_batch(
        "serial",
        [
            {"op": "dump_hierarchy"},
            {"op": "exists", "selector": {"xpath": "//node"}},
        ],
    )

    assert result["ok"] is True
    assert pool.run_locked.await_count == 1
    mock_device.xpath.assert_called_once_with("//node")
    stats = exc.stats_snapshot(reset=False)
    assert stats["xml_optimizer_fallbacks"] == 1
    assert stats["xml_batch_optimized"] == 0


@pytest.mark.asyncio
async def test_xml_batch_get_text_missing_respects_early_exit(event_loop):
    pool = AsyncMock()
    pool.evict = AsyncMock()
    xml = "<?xml version='1.0'?><hierarchy><node text='Login' /></hierarchy>"

    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=lambda _s, _t, _c: xml,
    )

    result = await exc.run_batch(
        "serial",
        [
            {"op": "dump_hierarchy"},
            {"op": "get_text", "selector": {"text": "Missing"}},
            {"op": "exists", "selector": {"text": "Login"}},
        ],
    )

    assert result["ok"] is False
    assert result["stopped_at"] == 1
    assert len(result["results"]) == 2
    assert result["results"][1]["error"] == "selector not found"
    pool.run_locked.assert_not_called()


@pytest.mark.asyncio
async def test_ui_mutation_invalidates_dump_hierarchy_cache(event_loop, mock_device):
    pool = AsyncMock()

    async def _run_locked(serial: str, fn):
        return fn(mock_device)

    pool.run_locked = AsyncMock(side_effect=_run_locked)
    pool.evict = AsyncMock()
    calls = 0

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal calls
        calls += 1
        return f"<?xml version='1.0'?><hierarchy><node text='{calls}' /></hierarchy>"

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)

    first = await exc.run_batch("serial", [{"op": "dump_hierarchy"}])
    await exc.run_batch("serial", [{"op": "click", "x": 1, "y": 2}])
    second = await exc.run_batch("serial", [{"op": "dump_hierarchy"}])

    assert calls == 2
    assert first["results"][0]["value"] != second["results"][0]["value"]


@pytest.mark.asyncio
async def test_dump_hierarchy_breaker_drops_background_visible_bypasses(event_loop):
    pool = AsyncMock()
    pool.evict = AsyncMock()
    calls = 0

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal calls
        calls += 1
        raise TimeoutError("read timeout")

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)

    for _index in range(3):
        result = await exc.run_batch("serial", [{"op": "dump_hierarchy"}])
        assert result["ok"] is False

    dropped = await exc.run_batch("serial", [{"op": "dump_hierarchy"}])
    visible = await exc.run_batch(
        "serial",
        [{"op": "dump_hierarchy"}],
        priority="visible",
    )

    assert calls == 4
    assert dropped["ok"] is False
    assert "breaker open" in dropped["error"]
    assert visible["ok"] is False
    assert "read timeout" in visible["error"]
    stats = exc.stats_snapshot(reset=False)
    assert stats["breaker_drops"] == 1
    assert stats["breaker_opens"] >= 1


@pytest.mark.asyncio
async def test_screenshot_returns_base64(executor):
    exc, dev, pool = executor
    dev.screenshot.return_value = b"\x89PNG\r\n"

    result = await exc.run_batch("serial", [
        {"op": "screenshot"},
    ])
    assert result["ok"] is True
    b64_val = result["results"][0]["value"]
    assert base64.b64decode(b64_val) == b"\x89PNG\r\n"


@pytest.mark.asyncio
async def test_open_url_uses_uiautomator_device_open_url(executor):
    exc, dev, pool = executor

    result = await exc.run_batch("serial", [
        {"op": "open_url", "url": "https://example.com/path?q=1"},
    ])

    assert result["ok"] is True
    assert result["results"][0]["op"] == "open_url"
    dev.open_url.assert_called_once_with("https://example.com/path?q=1")


def test_selector_normalizes_description_startswith_alias(mock_device):
    _resolve(mock_device, {"descriptionStartswith": "Nút Thích"})

    mock_device.assert_called_once_with(descriptionStartsWith="Nút Thích")


@pytest.mark.asyncio
async def test_click_selector_default_timeout_is_fast(executor):
    exc, dev, pool = executor
    ui_obj = MagicMock()
    ui_obj.click_exists.return_value = False
    dev.return_value = ui_obj

    result = await exc.run_batch("serial", [
        {"op": "click_selector", "selector": {"text": "missing"}},
    ])

    assert result["ok"] is True
    ui_obj.click_exists.assert_called_once_with(timeout=0.35)


@pytest.mark.asyncio
async def test_click_spec_default_timeout_is_fast(executor):
    exc, dev, pool = executor
    ui_obj = MagicMock()
    ui_obj.click_exists.return_value = False
    dev.return_value = ui_obj

    result = await exc.run_batch("serial", [
        {"op": "click_spec", "spec": {"by": "text", "value": "missing"}},
    ])

    assert result["ok"] is True
    ui_obj.click_exists.assert_called_once_with(timeout=0.35)


@pytest.mark.asyncio
async def test_swipe_default_duration_is_fast(executor):
    exc, dev, pool = executor

    result = await exc.run_batch("serial", [
        {"op": "swipe", "fx": 100, "fy": 1000, "tx": 100, "ty": 300},
    ])

    assert result["ok"] is True
    dev.swipe.assert_called_once_with(100, 1000, 100, 300, duration=0.12)


@pytest.mark.asyncio
async def test_run_batch_sleep_op_is_bounded(executor, monkeypatch):
    exc, dev, pool = executor
    calls: list[float] = []
    monkeypatch.setattr("relay.u2_executor.time.sleep", calls.append)

    result = await exc.run_batch("serial", [{"op": "sleep", "seconds": 9.0}])

    assert result["ok"] is True
    assert calls == [3.0]


@pytest.mark.asyncio
async def test_wait_and_click_default_timeout_is_bounded(executor):
    exc, dev, pool = executor
    ui_obj = MagicMock()
    ui_obj.wait.return_value = False
    dev.return_value = ui_obj

    result = await exc.execute_flow("serial", "wait_and_click", {"selector": {"text": "missing"}})

    assert result["ok"] is True
    ui_obj.wait.assert_called_once_with(timeout=3.0)


@pytest.mark.asyncio
async def test_find_click_wait_default_timeouts_are_bounded(executor):
    exc, dev, pool = executor
    ui_obj = MagicMock()
    ui_obj.wait.return_value = True
    ui_obj.wait_gone.return_value = False
    dev.return_value = ui_obj

    result = await exc.execute_flow("serial", "find_click_wait", {"selector": {"text": "OK"}})

    assert result["ok"] is True
    ui_obj.wait.assert_called_once_with(timeout=3.0)
    ui_obj.wait_gone.assert_called_once_with(timeout=1.0)


@pytest.mark.asyncio
async def test_swipe_until_found_default_budget_is_bounded(executor):
    exc, dev, pool = executor
    ui_obj = MagicMock()
    ui_obj.exists = False
    dev.return_value = ui_obj
    dev.window_size.return_value = (1080, 2340)

    result = await exc.execute_flow("serial", "swipe_until_found", {"selector": {"text": "missing"}})

    assert result["ok"] is True
    assert result["value"]["swipes"] == 5
    assert dev.swipe.call_count == 5
    assert dev.swipe.call_args.kwargs == {"duration": 0.12}


# ── Selector resolution ──────────────────────────────────────────────────────


def test_selector_xpath_dispatch():
    dev = MagicMock()
    _resolve(dev, {"xpath": "//View"})
    dev.xpath.assert_called_once_with("//View")


def test_selector_kwargs_dispatch():
    dev = MagicMock()
    _resolve(dev, {"text": "OK"})
    dev.assert_called_once_with(text="OK")


def test_selector_empty_raises():
    dev = MagicMock()
    with pytest.raises(ValueError, match="selector required"):
        _resolve(dev, {})


def test_selector_unknown_keys_raises():
    dev = MagicMock()
    with pytest.raises(ValueError, match="unrecognised"):
        _resolve(dev, {"bogusKey": "val"})
