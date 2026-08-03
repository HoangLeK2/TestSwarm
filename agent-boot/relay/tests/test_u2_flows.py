"""Tests for relay.u2_executor — named flow functions."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, call

import pytest

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


@pytest.mark.asyncio
async def test_swipe_until_found_on_third(executor_with_device):
    exc, dev = executor_with_device
    sel = MagicMock()

    exists_sequence = [False, False, True]
    type(sel).exists = property(lambda self, _seq=iter(exists_sequence): next(_seq))
    dev.return_value = sel
    dev.window_size.return_value = (1080, 1920)

    result = await exc.execute_flow("serial", "swipe_until_found", {
        "selector": {"text": "Target"},
        "max_swipes": 5,
    })

    assert result["value"]["found"] is True
    assert result["value"]["swipes"] == 2
    assert dev.swipe.call_count == 2


@pytest.mark.asyncio
async def test_swipe_until_found_uses_non_blocking_exists(executor_with_device):
    exc, dev = executor_with_device
    sel = MagicMock()
    sel.exists = MagicMock(side_effect=[False, True])
    dev.return_value = sel
    dev.window_size.return_value = (1080, 1920)

    result = await exc.execute_flow("serial", "swipe_until_found", {
        "selector": {"text": "Target"},
        "max_swipes": 5,
    })

    assert result["value"]["found"] is True
    assert result["value"]["swipes"] == 1
    assert sel.exists.call_args_list == [call(timeout=0), call(timeout=0)]
    assert dev.swipe.call_count == 1


@pytest.mark.asyncio
async def test_swipe_until_found_exhausts(executor_with_device):
    exc, dev = executor_with_device
    sel = MagicMock()
    type(sel).exists = property(lambda self: False)
    dev.return_value = sel
    dev.window_size.return_value = (1080, 1920)

    result = await exc.execute_flow("serial", "swipe_until_found", {
        "selector": {"text": "Nope"},
        "max_swipes": 3,
    })

    assert result["value"]["found"] is False
    assert result["value"]["swipes"] == 3


@pytest.mark.asyncio
async def test_swipe_until_found_zero_swipes(executor_with_device):
    exc, dev = executor_with_device
    sel = MagicMock()
    type(sel).exists = property(lambda self: True)
    dev.return_value = sel
    dev.window_size.return_value = (1080, 1920)

    result = await exc.execute_flow("serial", "swipe_until_found", {
        "selector": {"text": "Here"},
        "max_swipes": 0,
    })

    assert result["value"]["found"] is True
    assert result["value"]["swipes"] == 0
    dev.swipe.assert_not_called()


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
    assert result["value"] == {"found": True, "swipes": 2}
    assert [call["method"] for call in rpc_calls] == [
        "exist",
        "swipe",
        "exist",
        "swipe",
        "exist",
    ]
    assert rpc_calls[0]["params"][0]["resourceId"] == "com.app:id/target"
    assert rpc_calls[1] == {
        "jsonrpc": "2.0",
        "method": "swipe",
        "id": 1,
        "params": [540, 1536, 540, 384, 4],
    }
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
                    "conditions": {"packageName": "com.facebook.katana"},
                }
            },
            "max_swipes": 5,
            "width": 1080,
            "height": 1920,
        },
        priority="visible",
    )

    assert result["ok"] is True
    assert result["value"] == {"found": True, "swipes": 0}
    assert [call["method"] for call in rpc_calls] == ["exist"]
    assert rpc_calls[0]["params"][0]["description"] == "Bình luận"
    assert rpc_calls[0]["params"][0]["packageName"] == "com.facebook.katana"
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["http_exists_rpcs"] == 1
    assert stats["http_exists_hits"] == 1


@pytest.mark.asyncio
async def test_swipe_until_found_http_flow_exhausts(event_loop):
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
            "max_swipes": 3,
            "window_size": [1080, 1920],
        },
    )

    assert result["ok"] is True
    assert result["value"] == {"found": False, "swipes": 3}
    assert [call["method"] for call in rpc_calls] == [
        "exist",
        "swipe",
        "exist",
        "swipe",
        "exist",
        "swipe",
        "exist",
    ]
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["http_flow_misses"] == 1
    assert stats["http_flow_swipes"] == 3
    assert stats["http_exists_misses"] == 4


@pytest.mark.asyncio
async def test_swipe_until_found_http_flow_falls_back_without_window_size(
    executor_with_device,
):
    exc, dev = executor_with_device
    exc._http_dump = lambda _s, _t, _c: "<?xml version='1.0'?><hierarchy />"
    exc._http_rpc = lambda _s, _p, _t: (True, "")
    sel = MagicMock()
    type(sel).exists = property(lambda self: True)
    dev.return_value = sel
    dev.window_size.return_value = (1080, 1920)

    result = await exc.execute_flow(
        "serial",
        "swipe_until_found",
        {"selector": {"text": "Target"}, "max_swipes": 1},
    )

    assert result["ok"] is True
    assert result["value"] == {"found": True, "swipes": 0}
    dev.window_size.assert_called_once()
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
    exc, dev = executor_with_device
    result = await exc.execute_flow("serial", "nonexistent", {})

    assert result["ok"] is False
    assert "unknown flow" in result["error"]
