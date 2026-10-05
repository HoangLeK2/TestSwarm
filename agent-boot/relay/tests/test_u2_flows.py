"""Tests for relay.u2_executor — named flow functions."""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from relay import u2_executor
from relay.u2_executor import U2Executor


@pytest.fixture
def executor_with_device(event_loop):
    pool = AsyncMock()
    dev = MagicMock()
    pool.get_session = AsyncMock(return_value=dev)

    async def _run_locked(_serial, fn):
        return fn(dev)

    pool.run_locked = AsyncMock(side_effect=_run_locked)
    exc = U2Executor(pool=pool, loop=event_loop)
    return exc, dev


# ── find_click_wait ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_find_click_wait_happy(executor_with_device):
    exc, dev = executor_with_device
    sel = MagicMock()
    sel.wait.return_value = True
    sel.wait_gone.return_value = True
    dev.return_value = sel

    result = await exc.execute_flow("serial", "find_click_wait", {
        "selector": {"text": "OK"},
        "click_timeout": 5.0,
        "gone_timeout": 2.0,
    })

    assert result["ok"] is True
    v = result["value"]
    assert v["found"] is True
    assert v["clicked"] is True
    assert v["gone"] is True
    sel.click.assert_called_once()


@pytest.mark.asyncio
async def test_find_click_wait_not_found(executor_with_device):
    exc, dev = executor_with_device
    sel = MagicMock()
    sel.wait.return_value = False
    dev.return_value = sel

    result = await exc.execute_flow("serial", "find_click_wait", {
        "selector": {"text": "OK"},
    })

    assert result["ok"] is True
    v = result["value"]
    assert v["found"] is False
    assert v["clicked"] is False
    sel.click.assert_not_called()


@pytest.mark.asyncio
async def test_find_click_wait_clicked_not_gone(executor_with_device):
    exc, dev = executor_with_device
    sel = MagicMock()
    sel.wait.return_value = True
    sel.wait_gone.return_value = False
    dev.return_value = sel

    result = await exc.execute_flow("serial", "find_click_wait", {
        "selector": {"text": "OK"},
    })

    v = result["value"]
    assert v["found"] is True
    assert v["clicked"] is True
    assert v["gone"] is False


@pytest.mark.asyncio
async def test_find_click_wait_uses_http_flow_without_u2_lock(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    xmls = [
        """<?xml version='1.0'?>
        <hierarchy>
          <node text="OK" resource-id="com.app:id/ok" bounds="[100,200][200,260]" />
        </hierarchy>
        """,
        "<?xml version='1.0'?><hierarchy />",
    ]
    dump_calls = 0
    rpc_calls: list[dict] = []

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal dump_calls
        dump_calls += 1
        return xmls[min(dump_calls - 1, len(xmls) - 1)]

    def http_rpc(_serial: str, payload: dict, _timeout: float) -> tuple[bool, str]:
        rpc_calls.append(payload)
        return True, ""

    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=http_dump,
        http_rpc=http_rpc,
    )

    result = await exc.execute_flow(
        "serial",
        "find_click_wait",
        {
            "selector": {"resourceId": "com.app:id/ok"},
            "click_timeout": 0.1,
            "gone_timeout": 0.1,
        },
        priority="visible",
    )

    assert result["ok"] is True
    assert result["value"] == {"found": True, "clicked": True, "gone": True}
    assert rpc_calls == [
        {"jsonrpc": "2.0", "method": "click", "id": 1, "params": [150, 230]}
    ]
    assert dump_calls == 2
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["http_flow_fastpaths"] == 1
    assert stats["http_flow_hits"] == 1
    assert stats["http_flow_polls"] == 2
    assert stats["http_direct_actions"] == 1


# ── wait_and_click ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wait_and_click_found(executor_with_device):
    exc, dev = executor_with_device
    sel = MagicMock()
    sel.wait.return_value = True
    dev.return_value = sel

    result = await exc.execute_flow("serial", "wait_and_click", {
        "selector": {"text": "Continue"},
    })

    assert result["ok"] is True
    assert result["value"]["found"] is True
    assert result["value"]["clicked"] is True
    sel.click.assert_called_once()


@pytest.mark.asyncio
async def test_wait_and_click_not_found(executor_with_device):
    exc, dev = executor_with_device
    sel = MagicMock()
    sel.wait.return_value = False
    dev.return_value = sel

    result = await exc.execute_flow("serial", "wait_and_click", {
        "selector": {"text": "Missing"},
    })

    assert result["value"]["found"] is False
    sel.click.assert_not_called()


@pytest.mark.asyncio
async def test_wait_and_click_uses_http_flow_without_u2_lock(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    rpc_calls: list[dict] = []
    xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="Continue" resource-id="com.app:id/continue" bounds="[20,40][120,90]" />
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

    result = await exc.execute_flow(
        "serial",
        "wait_and_click",
        {"selector": {"resourceId": "com.app:id/continue"}, "wait_timeout": 0.1},
        priority="visible",
    )

    assert result["ok"] is True
    assert result["value"] == {"found": True, "clicked": True}
    assert rpc_calls == [
        {"jsonrpc": "2.0", "method": "click", "id": 1, "params": [70, 65]}
    ]
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["http_flow_fastpaths"] == 1
    assert stats["http_flow_hits"] == 1
    assert stats["http_flow_polls"] == 1


# ── find_get_text ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_find_get_text_found(executor_with_device):
    exc, dev = executor_with_device
    sel = MagicMock()
    sel.wait.return_value = True
    sel.get_text.return_value = "hello"
    dev.return_value = sel

    result = await exc.execute_flow("serial", "find_get_text", {
        "selector": {"resourceId": "com.app:id/title"},
    })

    assert result["value"]["found"] is True
    assert result["value"]["text"] == "hello"


@pytest.mark.asyncio
async def test_find_get_text_not_found(executor_with_device):
    exc, dev = executor_with_device
    sel = MagicMock()
    sel.wait.return_value = False
    dev.return_value = sel

    result = await exc.execute_flow("serial", "find_get_text", {
        "selector": {"text": "gone"},
    })

    assert result["value"]["found"] is False
    assert result["value"]["text"] is None


# ── swipe_until_found ─────────────────────────────────────────────────────────


def _wire_scroll_device(dev, target, *, forward_results=None):
    """Route dev(scrollable=True) to a container mock, everything else to the
    target — the executor resolves those two separately."""
    container = MagicMock()
    if forward_results is None:
        container.scroll.vert.forward = MagicMock(return_value=True)
    else:
        container.scroll.vert.forward = MagicMock(side_effect=forward_results)

    def _dispatch(**kwargs):
        return container if kwargs.get("scrollable") else target

    dev.side_effect = _dispatch
    dev.window_size.return_value = (1080, 1920)
    return container


@pytest.mark.asyncio
async def test_swipe_until_found_on_third(executor_with_device):
    exc, dev = executor_with_device
    sel = MagicMock()

    exists_sequence = [False, False, True]
    type(sel).exists = property(lambda self, _seq=iter(exists_sequence): next(_seq))
    container = _wire_scroll_device(dev, sel)

    result = await exc.execute_flow("serial", "swipe_until_found", {
        "selector": {"text": "Target"},
        "max_swipes": 5,
    })

    assert result["value"]["found"] is True
    assert result["value"]["swipes"] == 2
    assert result["value"]["driver"] == "uiscrollable"
    assert container.scroll.vert.forward.call_count == 2
    dev.swipe.assert_not_called()


@pytest.mark.asyncio
async def test_swipe_until_found_uses_non_blocking_exists(executor_with_device):
    exc, dev = executor_with_device
    sel = MagicMock()
    sel.exists = MagicMock(side_effect=[False, True])
    container = _wire_scroll_device(dev, sel)

    result = await exc.execute_flow("serial", "swipe_until_found", {
        "selector": {"text": "Target"},
        "max_swipes": 5,
    })

    assert result["value"]["found"] is True
    assert result["value"]["swipes"] == 1
    assert sel.exists.call_args_list == [call(timeout=0), call(timeout=0)]
    assert container.scroll.vert.forward.call_count == 1


@pytest.mark.asyncio
async def test_swipe_until_found_exhausts(executor_with_device):
    exc, dev = executor_with_device
    sel = MagicMock()
    type(sel).exists = property(lambda self: False)
    _wire_scroll_device(dev, sel)

    result = await exc.execute_flow("serial", "swipe_until_found", {
        "selector": {"text": "Nope"},
        "max_swipes": 3,
    })

    assert result["value"]["found"] is False
    assert result["value"]["swipes"] == 3


@pytest.mark.asyncio
async def test_swipe_until_found_stops_when_list_cannot_advance(executor_with_device):
    """UiScrollable reports the list is at its end. Every further swipe would
    scroll an unchanged screen, so the loop must stop instead of burning
    max_swipes on wall-clock."""
    exc, dev = executor_with_device
    sel = MagicMock()
    type(sel).exists = property(lambda self: False)
    container = _wire_scroll_device(dev, sel, forward_results=[True, False])

    result = await exc.execute_flow("serial", "swipe_until_found", {
        "selector": {"text": "Nope"},
        "max_swipes": 10,
    })

    assert result["value"]["found"] is False
    assert result["value"]["swipes"] == 2
    assert result["value"]["exhausted"] is True
    assert container.scroll.vert.forward.call_count == 2


@pytest.mark.asyncio
async def test_swipe_until_found_falls_back_to_blind_swipe_for_xpath(executor_with_device):
    """UiScrollable takes a UiSelector; an xpath target cannot be handed to it,
    so that screen keeps the old swipe loop."""
    exc, dev = executor_with_device
    sel = MagicMock()
    type(sel).exists = property(lambda self: False)
    dev.xpath.return_value = sel
    dev.window_size.return_value = (1080, 1920)

    result = await exc.execute_flow("serial", "swipe_until_found", {
        "selector": {"xpath": "//*[@text='Target']"},
        "max_swipes": 2,
    })

    assert result["value"]["driver"] == "blind_swipe"
    assert dev.swipe.call_count == 2


@pytest.mark.asyncio
async def test_swipe_until_found_falls_back_when_no_scrollable_container(executor_with_device):
    exc, dev = executor_with_device
    sel = MagicMock()
    type(sel).exists = property(lambda self: False)
    container = _wire_scroll_device(dev, sel)
    container.scroll.vert.forward = MagicMock(side_effect=RuntimeError("no scrollable"))

    result = await exc.execute_flow("serial", "swipe_until_found", {
        "selector": {"text": "Nope"},
        "max_swipes": 2,
    })

    assert result["value"]["driver"] == "blind_swipe"
    assert dev.swipe.call_count == 2


@pytest.mark.asyncio
async def test_swipe_until_found_zero_swipes(executor_with_device):
    exc, dev = executor_with_device
    sel = MagicMock()
    type(sel).exists = property(lambda self: True)
    container = _wire_scroll_device(dev, sel)

    result = await exc.execute_flow("serial", "swipe_until_found", {
        "selector": {"text": "Here"},
        "max_swipes": 0,
    })

    assert result["value"]["found"] is True
    assert result["value"]["swipes"] == 0
    dev.swipe.assert_not_called()
    container.scroll.vert.forward.assert_not_called()


@pytest.mark.asyncio
async def test_swipe_until_found_uses_http_flow_without_u2_lock(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    rpc_calls: list[dict] = []
    exists_results = [False, False, True]

    def http_rpc(_serial: str, payload: dict, _timeout: float) -> tuple[bool, str, bool]:
        rpc_calls.append(payload)
        if payload["method"] == "exist":
            return True, "", exists_results.pop(0)
        return True, "", True

    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=lambda *_args: pytest.fail("exists RPC should avoid XML dump"),
        http_rpc=http_rpc,
    )

    result = await exc.execute_flow(
        "serial",
        "swipe_until_found",
        {
            "selector": {"resourceId": "com.app:id/target"},
            "max_swipes": 5,
            "width": 1080,
            "height": 1920,
        },
        priority="visible",
    )

    assert result["ok"] is True
    assert result["value"] == {"found": True, "swipes": 2, "driver": "uiscrollable"}
    assert [call["method"] for call in rpc_calls] == [
        "exist",
        "scrollForward",
        "exist",
        "scrollForward",
        "exist",
    ]
    assert rpc_calls[0]["params"][0]["resourceId"] == "com.app:id/target"
    # Container is the scrollable node, scrolled vertically at the library's
    # own 55-step granularity — not a screen-centre fling.
    assert rpc_calls[1]["method"] == "scrollForward"
    assert rpc_calls[1]["params"][0]["scrollable"] is True
    assert rpc_calls[1]["params"][1] is True
    assert rpc_calls[1]["params"][2] == 55
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["http_flow_fastpaths"] == 1
    assert stats["http_flow_hits"] == 1
    assert stats["http_flow_polls"] == 3
    assert stats["http_flow_swipes"] == 2
    assert stats["http_direct_actions"] == 2
    assert stats["http_exists_rpcs"] == 3
    assert stats["http_exists_hits"] == 1
    assert stats["http_exists_misses"] == 2


@pytest.mark.asyncio
async def test_swipe_until_found_http_flow_accepts_simple_spec(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    rpc_calls: list[dict] = []

    def http_rpc(_serial: str, payload: dict, _timeout: float) -> tuple[bool, str, bool]:
        rpc_calls.append(payload)
        return True, "", True

    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=lambda *_args: pytest.fail("simple spec should use exists RPC"),
        http_rpc=http_rpc,
    )

    result = await exc.execute_flow(
        "serial",
        "swipe_until_found",
        {
            "selector": {
                "spec": {
                    "by": "description",
                    "value": "Bình luận",
                    "conditions": {"packageName": "com.example.app"},
                }
            },
            "max_swipes": 5,
            "width": 1080,
            "height": 1920,
        },
        priority="visible",
    )

    assert result["ok"] is True
    assert result["value"] == {"found": True, "swipes": 0, "driver": "uiscrollable"}
    assert [call["method"] for call in rpc_calls] == ["exist"]
    assert rpc_calls[0]["params"][0]["description"] == "Bình luận"
    assert rpc_calls[0]["params"][0]["packageName"] == "com.example.app"
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["http_exists_rpcs"] == 1
    assert stats["http_exists_hits"] == 1


@pytest.mark.asyncio
async def test_swipe_until_found_http_flow_confirms_spec_with_xml_before_scroll(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    rpc_calls: list[dict] = []
    dumps: list[tuple] = []
    hierarchy = """<hierarchy rotation="0">
      <node class="android.widget.FrameLayout" package="com.example.app">
        <node class="androidx.recyclerview.widget.RecyclerView" package="com.example.app"
              scrollable="true" bounds="[0,308][1260,434]"/>
        <node text="Cộng Đồng Claude &amp; OpenClaw &amp; AI Agent Việt Nam&#160;· Tham&#160;gia"
              class="android.view.View" package="com.example.app"
              content-desc="Cộng Đồng Claude &amp; OpenClaw &amp; AI Agent Việt Nam &#160;·  Tham&#160;gia"
              visible-to-user="true" bounds="[294,478][1218,610]"/>
      </node>
    </hierarchy>"""

    def http_rpc(_serial: str, payload: dict, _timeout: float) -> tuple[bool, str, bool]:
        rpc_calls.append(payload)
        return True, "", False

    def http_dump(*args):
        dumps.append(args)
        return hierarchy

    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=http_dump,
        http_rpc=http_rpc,
    )

    result = await exc.execute_flow(
        "serial",
        "swipe_until_found",
        {
            "selector": {
                "spec": {
                    "by": "description",
                    "value": "Cộng Đồng Claude & OpenClaw & AI Agent Việt Nam \u00a0·  Tham\u00a0gia",
                    "conditions": {"packageName": "com.example.app"},
                }
            },
            "max_swipes": 5,
            "width": 1080,
            "height": 1920,
        },
        priority="visible",
    )

    assert result["ok"] is True
    assert result["value"] == {"found": True, "swipes": 0, "driver": "uiscrollable"}
    assert [call["method"] for call in rpc_calls] == ["exist"]
    assert dumps
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["http_flow_hits"] == 1
    assert stats["http_flow_swipes"] == 0


@pytest.mark.asyncio
async def test_swipe_until_found_http_flow_uses_vertical_scroll_container(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    rpc_calls: list[dict] = []
    exists_results = [False, False, True]
    hierarchy = """<hierarchy rotation="0">
      <node class="android.widget.FrameLayout" package="com.example.app">
        <node class="androidx.recyclerview.widget.RecyclerView" package="com.example.app"
              scrollable="true" visible-to-user="true" bounds="[0,308][1260,434]"/>
        <node class="androidx.recyclerview.widget.StaggeredGridLayoutManager"
              package="com.example.app" scrollable="true" visible-to-user="true"
              bounds="[0,469][1260,2800]"/>
      </node>
    </hierarchy>"""

    def http_rpc(_serial: str, payload: dict, _timeout: float) -> tuple[bool, str, bool]:
        rpc_calls.append(payload)
        if payload["method"] == "exist":
            return True, "", exists_results.pop(0)
        return True, "", True

    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=lambda *_args: hierarchy,
        http_rpc=http_rpc,
    )

    result = await exc.execute_flow(
        "serial",
        "swipe_until_found",
        {
            "selector": {
                "spec": {
                    "by": "description",
                    "value": "Cộng Đồng OpenClaw \u00a0· Tham\u00a0gia",
                    "conditions": {"packageName": "com.example.app"},
                }
            },
            "max_swipes": 5,
            "width": 1080,
            "height": 1920,
        },
        priority="visible",
    )

    assert result["ok"] is True
    assert result["value"] == {"found": True, "swipes": 2, "driver": "uiscrollable"}
    scroll_calls = [call for call in rpc_calls if call["method"] == "scrollForward"]
    assert len(scroll_calls) == 2
    for call in scroll_calls:
        container = call["params"][0]
        assert container["scrollable"] is True
        assert container["packageName"] == "com.example.app"
        assert container["className"] == "androidx.recyclerview.widget.StaggeredGridLayoutManager"
    pool.run_locked.assert_not_called()


@pytest.mark.asyncio
async def test_swipe_until_found_http_flow_exhausts(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    rpc_calls: list[dict] = []

    def http_rpc(_serial: str, payload: dict, _timeout: float) -> tuple[bool, str, bool]:
        rpc_calls.append(payload)
        # exist → never found; scrollForward → list still has room.
        return True, "", payload["method"] == "scrollForward"

    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=lambda *_args: pytest.fail("exists RPC should avoid XML dump"),
        http_rpc=http_rpc,
    )

    result = await exc.execute_flow(
        "serial",
        "swipe_until_found",
        {
            "selector": {"text": "Missing"},
            "max_swipes": 3,
            "window_size": [1080, 1920],
        },
    )

    assert result["ok"] is True
    assert result["value"] == {"found": False, "swipes": 3, "driver": "uiscrollable"}
    assert [call["method"] for call in rpc_calls] == [
        "exist",
        "scrollForward",
        "exist",
        "scrollForward",
        "exist",
        "scrollForward",
        "exist",
    ]
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["http_flow_misses"] == 1
    assert stats["http_flow_swipes"] == 3
    assert stats["http_exists_misses"] == 4


@pytest.mark.asyncio
async def test_swipe_until_found_http_flow_stops_when_list_cannot_advance(event_loop):
    """scrollForward returning False means the list is spent. Polling an
    unchanged screen for the remaining budget is wasted wall-clock."""
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    rpc_calls: list[dict] = []

    def http_rpc(_serial: str, payload: dict, _timeout: float) -> tuple[bool, str, bool]:
        rpc_calls.append(payload)
        return True, "", False

    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=lambda *_args: pytest.fail("exists RPC should avoid XML dump"),
        http_rpc=http_rpc,
    )

    result = await exc.execute_flow(
        "serial",
        "swipe_until_found",
        {
            "selector": {"text": "Missing"},
            "max_swipes": 20,
            "window_size": [1080, 1920],
        },
    )

    assert result["ok"] is True
    assert result["value"]["found"] is False
    assert result["value"]["exhausted"] is True
    assert result["value"]["swipes"] == 1
    assert [call["method"] for call in rpc_calls] == ["exist", "scrollForward"]


@pytest.mark.asyncio
async def test_swipe_until_found_http_flow_degrades_to_swipe_without_scrollable(event_loop):
    """No scrollable container on this screen — keep the fast path, but stop
    pretending UiScrollable can drive it."""
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    rpc_calls: list[dict] = []

    def http_rpc(_serial: str, payload: dict, _timeout: float) -> tuple[bool, str, bool]:
        rpc_calls.append(payload)
        if payload["method"] == "scrollForward":
            return False, "UiObjectNotFoundError", None
        return True, "", False

    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=lambda *_args: pytest.fail("exists RPC should avoid XML dump"),
        http_rpc=http_rpc,
    )

    result = await exc.execute_flow(
        "serial",
        "swipe_until_found",
        {
            "selector": {"text": "Missing"},
            "max_swipes": 2,
            "window_size": [1080, 1920],
        },
    )

    assert result["ok"] is True
    assert result["value"]["driver"] == "blind_swipe"
    methods = [call["method"] for call in rpc_calls]
    # Tries UiScrollable once, then falls back to swipes for the rest.
    assert methods == ["exist", "scrollForward", "swipe", "exist", "swipe", "exist"]


@pytest.mark.asyncio
async def test_swipe_until_found_settles_between_scrolls(executor_with_device, monkeypatch):
    """Probing before the list stops moving misses the target and burns every
    swipe as one uninterrupted burst."""
    exc, dev = executor_with_device
    events: list[str] = []
    sel = MagicMock()
    sel.exists = MagicMock(side_effect=lambda **_kw: events.append("exists") or False)
    container = _wire_scroll_device(dev, sel)
    container.scroll.vert.forward = MagicMock(
        side_effect=lambda: events.append("scroll") or True
    )
    monkeypatch.setattr(
        u2_executor.time, "sleep", lambda s: events.append(f"sleep:{s}")
    )

    result = await exc.execute_flow("serial", "swipe_until_found", {
        "selector": {"text": "Missing"},
        "max_swipes": 2,
        "settle_s": 0.4,
    })

    assert result["value"]["found"] is False
    assert events == [
        "exists", "scroll", "sleep:0.4",
        "exists", "scroll", "sleep:0.4",
        "exists",
    ]


@pytest.mark.asyncio
async def test_swipe_until_found_waits_for_still_rendering_screen(executor_with_device):
    """The target is already on screen but the frame has not landed yet.
    Probing at timeout=0 would scroll a present target out of view."""
    exc, dev = executor_with_device
    sel = MagicMock()
    sel.exists = MagicMock(return_value=False)
    sel.wait = MagicMock(return_value=True)
    container = _wire_scroll_device(dev, sel)

    result = await exc.execute_flow("serial", "swipe_until_found", {
        "selector": {"text": "Target"},
        "max_swipes": 5,
        "first_wait_s": 8.0,
    })

    assert result["value"]["found"] is True
    assert result["value"]["swipes"] == 0
    sel.wait.assert_called_once_with(timeout=8.0)
    dev.swipe.assert_not_called()
    container.scroll.vert.forward.assert_not_called()


@pytest.mark.asyncio
async def test_swipe_until_found_first_wait_defaults_off(executor_with_device):
    exc, dev = executor_with_device
    sel = MagicMock()
    sel.exists = MagicMock(return_value=True)
    sel.wait = MagicMock(return_value=True)
    _wire_scroll_device(dev, sel)

    result = await exc.execute_flow("serial", "swipe_until_found", {
        "selector": {"text": "Target"},
        "max_swipes": 5,
    })

    assert result["value"]["found"] is True
    assert result["value"]["swipes"] == 0
    sel.wait.assert_not_called()


@pytest.mark.asyncio
async def test_swipe_until_found_http_flow_waits_on_first_probe(event_loop, monkeypatch):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    events: list[str] = []
    exists_results = iter([False, False, True])

    def http_rpc(_serial: str, payload: dict, _timeout: float):
        events.append(payload["method"])
        if payload["method"] == "exist":
            return True, "", next(exists_results)
        return True, "", False

    real_sleep = asyncio.sleep

    async def fake_sleep(seconds, *args, **kwargs):
        events.append(f"sleep:{seconds}")
        return await real_sleep(0, *args, **kwargs)

    monkeypatch.setattr(u2_executor.asyncio, "sleep", fake_sleep)

    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=lambda *_args: pytest.fail("exists RPC should avoid XML dump"),
        http_rpc=http_rpc,
    )

    result = await exc.execute_flow(
        "serial",
        "swipe_until_found",
        {
            "selector": {"text": "Target"},
            "max_swipes": 3,
            "first_wait_s": 8.0,
            "window_size": [1080, 1920],
        },
    )

    # Found on the third poll of the FIRST probe — nothing was scrolled.
    assert result["value"] == {"found": True, "swipes": 0, "driver": "uiscrollable"}
    assert events == ["exist", "sleep:0.2", "exist", "sleep:0.2", "exist"]
    assert "swipe" not in events
    assert "scrollForward" not in events


@pytest.mark.asyncio
async def test_swipe_until_found_http_flow_settles_between_swipes(event_loop, monkeypatch):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    events: list[str] = []

    def http_rpc(_serial: str, payload: dict, _timeout: float) -> tuple[bool, str, bool]:
        events.append(payload["method"])
        return True, "", payload["method"] == "scrollForward"

    real_sleep = asyncio.sleep

    async def fake_sleep(seconds, *args, **kwargs):
        events.append(f"sleep:{seconds}")
        return await real_sleep(0, *args, **kwargs)

    monkeypatch.setattr(u2_executor.asyncio, "sleep", fake_sleep)

    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=lambda *_args: pytest.fail("exists RPC should avoid XML dump"),
        http_rpc=http_rpc,
    )

    result = await exc.execute_flow(
        "serial",
        "swipe_until_found",
        {
            "selector": {"text": "Missing"},
            "max_swipes": 2,
            "settle_s": 0.4,
            "window_size": [1080, 1920],
        },
    )

    assert result["value"] == {"found": False, "swipes": 2, "driver": "uiscrollable"}
    assert events == [
        "exist", "scrollForward", "sleep:0.4",
        "exist", "scrollForward", "sleep:0.4",
        "exist",
    ]


@pytest.mark.asyncio
async def test_swipe_until_found_http_flow_falls_back_without_window_size(
    executor_with_device,
):
    exc, dev = executor_with_device
    exc._http_dump = lambda _s, _t, _c: "<?xml version='1.0'?><hierarchy />"
    exc._http_rpc = lambda _s, _p, _t: (True, "")
    sel = MagicMock()
    type(sel).exists = property(lambda self: True)
    _wire_scroll_device(dev, sel)

    result = await exc.execute_flow(
        "serial",
        "swipe_until_found",
        {"selector": {"text": "Target"}, "max_swipes": 1},
    )

    assert result["ok"] is True
    assert result["value"]["found"] is True
    assert result["value"]["swipes"] == 0
    stats = exc.stats_snapshot(reset=False)
    assert stats["http_flow_fallbacks"] == 1


# ── input_and_confirm ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_input_and_confirm_success(executor_with_device):
    exc, dev = executor_with_device
    inp_sel = MagicMock()
    inp_sel.wait.return_value = True
    btn_sel = MagicMock()
    btn_sel.wait.return_value = True

    call_map = {"input": inp_sel, "confirm": btn_sel}
    def selector_dispatch(**kwargs):
        if kwargs.get("resourceId") == "input":
            return inp_sel
        return btn_sel
    dev.side_effect = selector_dispatch

    result = await exc.execute_flow("serial", "input_and_confirm", {
        "input_selector": {"resourceId": "input"},
        "text": "hello",
        "confirm_selector": {"resourceId": "confirm"},
    })

    assert result["value"]["found_input"] is True
    assert result["value"]["found_confirm"] is True
    assert result["value"]["clicked"] is True
    inp_sel.set_text.assert_called_once_with("hello")
    btn_sel.click.assert_called_once()


@pytest.mark.asyncio
async def test_input_and_confirm_no_input(executor_with_device):
    exc, dev = executor_with_device
    inp_sel = MagicMock()
    inp_sel.wait.return_value = False
    dev.return_value = inp_sel

    result = await exc.execute_flow("serial", "input_and_confirm", {
        "input_selector": {"resourceId": "input"},
        "text": "hello",
        "confirm_selector": {"resourceId": "confirm"},
    })

    assert result["value"]["found_input"] is False


@pytest.mark.asyncio
async def test_input_and_confirm_no_confirm(executor_with_device):
    exc, dev = executor_with_device

    inp_sel = MagicMock()
    inp_sel.wait.return_value = True
    btn_sel = MagicMock()
    btn_sel.wait.return_value = False

    calls = [0]
    def selector_dispatch(**kwargs):
        calls[0] += 1
        return inp_sel if calls[0] == 1 else btn_sel
    dev.side_effect = selector_dispatch

    result = await exc.execute_flow("serial", "input_and_confirm", {
        "input_selector": {"resourceId": "input"},
        "text": "hello",
        "confirm_selector": {"resourceId": "confirm"},
    })

    assert result["value"]["found_input"] is True
    assert result["value"]["found_confirm"] is False


# ── Unknown flow ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_flow_returns_error(executor_with_device):
    exc, _dev = executor_with_device
    result = await exc.execute_flow("serial", "nonexistent", {})

    assert result["ok"] is False
    assert "unknown flow" in result["error"]
