"""Tests for relay.u2_executor — named flow functions."""
from __future__ import annotations

import asyncio
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
async def test_swipe_until_found_settles_between_swipes(executor_with_device, monkeypatch):
    """A fling keeps moving after swipe() returns — probing before it stops
    misses the target and burns every swipe as one uninterrupted burst."""
    exc, dev = executor_with_device
    events: list[str] = []
    sel = MagicMock()
    sel.exists = MagicMock(side_effect=lambda **_kw: events.append("exists") or False)
    dev.return_value = sel
    dev.window_size.return_value = (1080, 1920)
    dev.swipe.side_effect = lambda *_a, **_k: events.append("swipe")
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
        "exists", "swipe", "sleep:0.4",
        "exists", "swipe", "sleep:0.4",
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
    dev.return_value = sel
    dev.window_size.return_value = (1080, 1920)

    result = await exc.execute_flow("serial", "swipe_until_found", {
        "selector": {"text": "Target"},
        "max_swipes": 5,
        "first_wait_s": 8.0,
    })

    assert result["value"] == {"found": True, "swipes": 0}
    sel.wait.assert_called_once_with(timeout=8.0)
    dev.swipe.assert_not_called()


@pytest.mark.asyncio
async def test_swipe_until_found_first_wait_defaults_off(executor_with_device):
    exc, dev = executor_with_device
    sel = MagicMock()
    sel.exists = MagicMock(return_value=True)
    sel.wait = MagicMock(return_value=True)
    dev.return_value = sel
    dev.window_size.return_value = (1080, 1920)

    result = await exc.execute_flow("serial", "swipe_until_found", {
        "selector": {"text": "Target"},
        "max_swipes": 5,
    })

    assert result["value"] == {"found": True, "swipes": 0}
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

    # Found on the third poll of the FIRST probe — no swipe was issued.
    assert result["value"] == {"found": True, "swipes": 0}
    assert events == ["exist", "sleep:0.2", "exist", "sleep:0.2", "exist"]
    assert "swipe" not in events


@pytest.mark.asyncio
async def test_swipe_until_found_http_flow_settles_between_swipes(event_loop, monkeypatch):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    events: list[str] = []

    def http_rpc(_serial: str, payload: dict, _timeout: float) -> tuple[bool, str, bool]:
        events.append(payload["method"])
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
            "selector": {"text": "Missing"},
            "max_swipes": 2,
            "settle_s": 0.4,
            "window_size": [1080, 1920],
        },
    )

    assert result["value"] == {"found": False, "swipes": 2}
    assert events == [
        "exist", "swipe", "sleep:0.4",
        "exist", "swipe", "sleep:0.4",
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


# ── Facebook people target resolver ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_fb_select_people_profile_verifies_target_before_friend_request(executor_with_device):
    exc, dev = executor_with_device
    search_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1080,1920]">
        <node text="Hoang Le" clickable="false" bounds="[42,512][420,573]" />
        <node text="" content-desc="Nút Thêm bạn bè" clickable="true" bounds="[584,512][921,573]" />
        <node text="Nguyen Van A" clickable="false" bounds="[42,704][420,765]" />
        <node text="" content-desc="Nút Thêm bạn bè" clickable="true" bounds="[584,704][921,765]" />
      </node>
    </hierarchy>
    """
    profile_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1080,1920]">
        <node text="Hoang Le" clickable="false" bounds="[42,180][600,248]" />
        <node text="" content-desc="Nút Thêm bạn bè" clickable="true" bounds="[42,988][655,1114]" />
      </node>
    </hierarchy>
    """
    dev.dump_hierarchy.side_effect = [search_xml, search_xml, profile_xml]

    result = await exc.execute_flow("serial", "social_select_target", {
        "target_type": "person",
        "display_name": "Hoang Le",
        "required_keywords": ["Hoang Le"],
        "min_score": 80,
    })

    assert result["ok"] is True
    value = result["value"]
    assert value["verified"] is True
    assert value["target_type"] == "person"
    assert value["action_bounds"] == [42, 988, 655, 1114]
    dev.click.assert_called_once_with(82, 542)


@pytest.mark.asyncio
async def test_fb_select_people_profile_rechecks_bounds_before_click(
    executor_with_device,
):
    exc, dev = executor_with_device
    initial_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1080,1920]">
        <node text="Hoang Le" clickable="false" bounds="[42,512][420,573]" />
        <node text="" content-desc="Nút Thêm bạn bè" clickable="true" bounds="[584,512][921,573]" />
      </node>
    </hierarchy>
    """
    shifted_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1080,1920]">
        <node text="Sponsored" clickable="true" bounds="[0,480][1080,650]" />
        <node text="Hoang Le" clickable="false" bounds="[42,704][420,765]" />
        <node text="" content-desc="Nút Thêm bạn bè" clickable="true" bounds="[584,704][921,765]" />
      </node>
    </hierarchy>
    """
    profile_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1080,1920]">
        <node text="Hoang Le" clickable="false" bounds="[42,180][600,248]" />
        <node text="" content-desc="Nút Thêm bạn bè" clickable="true" bounds="[42,988][655,1114]" />
      </node>
    </hierarchy>
    """
    dev.dump_hierarchy.side_effect = [initial_xml, shifted_xml, profile_xml]

    result = await exc.execute_flow(
        "serial",
        "social_select_target",
        {
            "target_type": "person",
            "display_name": "Hoang Le",
            "required_keywords": ["Hoang Le"],
            "min_score": 80,
        },
    )

    assert result["ok"] is True
    assert result["value"]["verified"] is True
    assert result["value"]["selected_bounds"] == [584, 704, 921, 765]
    dev.click.assert_called_once_with(82, 734)


@pytest.mark.asyncio
async def test_fb_select_people_profile_accepts_base_name_on_opened_profile(
    executor_with_device,
):
    exc, dev = executor_with_device
    search_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="Tuan Vu (Tuấn Tattoo Piercing) · Thêm bạn bè" clickable="false" bounds="[294,504][1218,636]" />
        <node text="Thêm bạn bè" clickable="true" bounds="[294,570][631,631]" />
      </node>
    </hierarchy>
    """
    profile_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="Tuan Vu" clickable="true" bounds="[420,505][698,584]" />
        <node text="Thêm bạn bè" clickable="true" bounds="[42,1055][655,1181]" />
      </node>
    </hierarchy>
    """
    dev.dump_hierarchy.side_effect = [search_xml, search_xml, profile_xml]

    result = await exc.execute_flow(
        "serial",
        "social_select_target",
        {
            "target_type": "person",
            "display_name": "Tuan Vu (Tuấn Tattoo Piercing)",
            "required_keywords": ["Tuan Vu (Tuấn Tattoo Piercing)"],
            "min_score": 80,
        },
    )

    assert result["ok"] is True
    assert result["value"]["verified"] is True
    assert result["value"]["action_bounds"] == [42, 1055, 655, 1181]


@pytest.mark.asyncio
async def test_fb_select_people_profile_verifies_already_pending_target(
    executor_with_device,
):
    exc, dev = executor_with_device
    search_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1080,1920]">
        <node text="Nguyễn Tuấn Anh Osana (tũn)" clickable="false" bounds="[42,512][520,573]" />
        <node text="" content-desc="Hủy yêu cầu" clickable="true" bounds="[584,512][921,573]" />
      </node>
    </hierarchy>
    """
    profile_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1080,1920]">
        <node text="Nguyễn Tuấn Anh Osana" clickable="false" bounds="[42,180][700,248]" />
        <node text="" content-desc="Hủy yêu cầu" clickable="true" bounds="[42,988][655,1114]" />
      </node>
    </hierarchy>
    """
    dev.dump_hierarchy.side_effect = [search_xml, search_xml, profile_xml]

    result = await exc.execute_flow(
        "serial",
        "social_select_target",
        {
            "target_type": "person",
            "display_name": "Nguyễn Tuấn Anh Osana",
            "required_keywords": ["Nguyễn Tuấn Anh Osana"],
            "min_score": 80,
        },
    )

    assert result["ok"] is True
    assert result["value"]["verified"] is True
    assert result["value"]["action_bounds"] == [42, 988, 655, 1114]
    dev.click.assert_called_once_with(82, 542)


@pytest.mark.asyncio
async def test_fb_select_people_profile_rejects_ambiguous_people_rows(executor_with_device):
    exc, dev = executor_with_device
    search_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1080,1920]">
        <node text="Hoang Le" clickable="false" bounds="[42,512][420,573]" />
        <node text="" content-desc="Nút Thêm bạn bè" clickable="true" bounds="[584,512][921,573]" />
        <node text="Hoang Le" clickable="false" bounds="[42,704][420,765]" />
        <node text="" content-desc="Nút Thêm bạn bè" clickable="true" bounds="[584,704][921,765]" />
      </node>
    </hierarchy>
    """
    dev.dump_hierarchy.return_value = search_xml

    result = await exc.execute_flow("serial", "social_select_target", {
        "target_type": "person",
        "display_name": "Hoang Le",
        "required_keywords": ["Hoang Le"],
        "min_score": 80,
        "require_unique": True,
    })

    assert result["ok"] is True
    assert result["value"]["verified"] is False
    assert result["value"]["reason"] == "ambiguous_target"
    dev.click.assert_not_called()


@pytest.mark.asyncio
async def test_fb_select_post_target_uses_dump_xml_fixture(executor_with_device):
    exc, dev = executor_with_device
    search_xml = (
        Path(__file__).parent
        / "fixtures"
        / "facebook"
        / "codex_vn_two_post_feed.xml"
    ).read_text(encoding="utf-8")
    detail_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="Các bác cho hỏi claude thì nên dùng opus 4.8 hay sonet 4.6 hơn nhỉ" clickable="true" bounds="[42,400][1218,560]" />
        <node text="" content-desc="Nút Thích" clickable="true" bounds="[42,1505][227,1659]" />
        <node text="" content-desc="Nút Bình luận. Nhấn đúp để xem bình luận." clickable="true" bounds="[227,1505][457,1659]" />
        <node text="" content-desc="Nút Chia sẻ" clickable="true" bounds="[457,1505][690,1659]" />
      </node>
    </hierarchy>
    """
    dev.dump_hierarchy.side_effect = [search_xml, detail_xml]

    result = await exc.execute_flow("serial", "social_select_target", {
        "target_type": "post",
        "display_text": "Các bác cho hỏi claude",
        "required_keywords": ["Các bác cho hỏi claude"],
        "min_score": 80,
    })

    assert result["ok"] is True
    value = result["value"]
    assert value["verified"] is True
    assert value["target_type"] == "post"
    assert value["action_count"] == 3
    assert value["selected_bounds"] == [105, 840, 1155, 1320]
    assert value["expanded_more"] is False
    assert value["expand_bounds"] is None
    dev.click.assert_called_once_with(630, 1080)


@pytest.mark.asyncio
async def test_fb_select_post_target_matches_split_vietnamese_result_without_posts_tab(
    executor_with_device,
):
    exc, dev = executor_with_device
    search_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="Tất cả" clickable="true" bounds="[42,302][214,392]" />
        <node text="Video" clickable="true" bounds="[238,302][410,392]" />
        <node text="Chào mọi người, mình là" clickable="false" bounds="[88,640][1110,710]" />
        <node text="thành viên mới, mình đang tìm hiểu Claude Code" clickable="true" bounds="[88,712][1110,806]" />
        <node text="12 bình luận" clickable="false" bounds="[88,1110][340,1170]" />
      </node>
    </hierarchy>
    """
    detail_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="Chào mọi người, mình là thành viên mới, mình đang tìm hiểu Claude Code" clickable="false" bounds="[42,400][1218,560]" />
        <node text="" content-desc="Nút Thích" clickable="true" bounds="[42,1505][227,1659]" />
        <node text="" content-desc="Nút Bình luận. Nhấn đúp để xem bình luận." clickable="true" bounds="[227,1505][457,1659]" />
      </node>
    </hierarchy>
    """
    dev.dump_hierarchy.side_effect = [search_xml, detail_xml]

    result = await exc.execute_flow(
        "serial",
        "social_select_target",
        {
            "target_type": "post",
            "display_text": "Chào mọi người, mình là thành viên mới",
            "required_keywords": ["Chào mọi người, mình là thành viên mới"],
            "min_score": 80,
        },
    )

    assert result["ok"] is True
    value = result["value"]
    assert value["verified"] is True
    assert value["target_type"] == "post"
    assert value["action_count"] == 2
    assert value["selected_bounds"] == [88, 712, 1110, 806]
    dev.click.assert_called_once_with(599, 759)


@pytest.mark.asyncio
async def test_fb_select_post_target_submits_focused_search_suggestion(
    executor_with_device,
):
    exc, dev = executor_with_device
    suggestion_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="" content-desc="" class="android.widget.Button" clickable="true" bounds="[0,288][1260,428]">
          <node text="anh chị em dùng ai cho những công" content-desc="anh chị em dùng ai cho những công" clickable="false" bounds="[196,329][1204,391]" />
        </node>
        <node text="anh chị em dùng ai cho những công" class="android.widget.EditText" content-desc="Tìm kiếm" clickable="true" focused="true" bounds="[210,133][1064,287]" />
      </node>
    </hierarchy>
    """
    results_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="Anh chị em dùng AI cho những công" clickable="true" bounds="[88,640][1110,734]" />
        <node text="việc nào trong quy trình nhân sự rồi ạ?" clickable="false" bounds="[88,736][1110,806]" />
      </node>
    </hierarchy>
    """
    detail_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="Anh chị em dùng AI cho những công việc nào trong quy trình nhân sự rồi ạ?" clickable="false" bounds="[42,400][1218,560]" />
        <node text="" content-desc="Nút Thích" clickable="true" bounds="[42,1505][227,1659]" />
        <node text="" content-desc="Nút Bình luận. Nhấn đúp để xem bình luận." clickable="true" bounds="[227,1505][457,1659]" />
      </node>
    </hierarchy>
    """
    dev.dump_hierarchy.side_effect = [suggestion_xml, results_xml, detail_xml]

    result = await exc.execute_flow(
        "serial",
        "social_select_target",
        {
            "target_type": "post",
            "display_text": "Anh chị em dùng AI cho những công",
            "required_keywords": ["Anh chị em dùng AI cho những công"],
            "min_score": 80,
        },
    )

    assert result["ok"] is True
    value = result["value"]
    assert value["verified"] is True
    assert value["target_type"] == "post"
    assert value["selected_bounds"] == [88, 640, 1110, 734]
    assert dev.click.call_args_list == [call(630, 358), call(599, 687)]


@pytest.mark.asyncio
async def test_fb_select_post_target_accepts_current_post_detail(executor_with_device):
    exc, dev = executor_with_device
    detail_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="Introducing a new way to edit videos with Meta AI" clickable="false" bounds="[42,400][1218,560]" />
        <node text="" content-desc="Nút Thích" clickable="true" bounds="[42,1505][227,1659]" />
        <node text="" content-desc="Nút Bình luận. Nhấn đúp để xem bình luận." clickable="true" bounds="[227,1505][457,1659]" />
        <node text="" content-desc="Nút Chia sẻ" clickable="true" bounds="[457,1505][690,1659]" />
      </node>
    </hierarchy>
    """
    dev.dump_hierarchy.return_value = detail_xml

    result = await exc.execute_flow("serial", "social_select_target", {
        "target_type": "post",
        "display_text": "Introducing a new way to edit videos with Meta AI",
        "required_keywords": ["Introducing a new way to edit videos with Meta AI"],
        "min_score": 80,
        "current_detail": True,
    })

    assert result["ok"] is True
    value = result["value"]
    assert value["verified"] is True
    assert value["target_type"] == "post"
    assert value["already_open"] is True
    assert value["action_count"] == 3
    dev.click.assert_not_called()


@pytest.mark.asyncio
async def test_fb_select_post_target_clicks_current_post_see_more_bounds(executor_with_device):
    exc, dev = executor_with_device
    search_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="Chắc sẽ có anh em cần cái này… xem thêm" content-desc="Chắc sẽ có anh em cần cái này… xem thêm" clickable="true" bounds="[42,841][1218,926]">
          <node text="xem thêm" content-desc="" clickable="true" bounds="[906,832][1170,898]" />
        </node>
        <node text="" content-desc="Nút Thích. Hãy nhấn đúp và giữ để bày tỏ cảm xúc về bình luận." clickable="true" bounds="[0,2476][225,2630]" />
        <node text="Bình luận" clickable="true" bounds="[225,2476][429,2630]" />
        <node text="" content-desc="Nút Chia sẻ. Nhấn đúp để chia sẻ bài viết." clickable="true" bounds="[429,2476][626,2630]" />
      </node>
    </hierarchy>
    """
    dev.dump_hierarchy.side_effect = [search_xml, search_xml]

    result = await exc.execute_flow("serial", "social_select_target", {
        "target_type": "post",
        "display_text": "Chắc sẽ có anh em cần cái này",
        "required_keywords": ["Chắc sẽ có anh em cần cái này"],
        "min_score": 80,
    })

    assert result["ok"] is True
    value = result["value"]
    assert value["verified"] is True
    assert value["expanded_more"] is True
    assert value["expand_bounds"] == [906, 832, 1170, 898]
    dev.click.assert_called_once_with(1038, 865)


@pytest.mark.asyncio
async def test_fb_select_post_target_rejects_ambiguous_post_rows(executor_with_device):
    exc, dev = executor_with_device
    search_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="same launch text" clickable="true" bounds="[100,400][1000,520]" />
        <node text="same launch text" clickable="true" bounds="[100,900][1000,1020]" />
      </node>
    </hierarchy>
    """
    dev.dump_hierarchy.return_value = search_xml

    result = await exc.execute_flow("serial", "social_select_target", {
        "target_type": "post",
        "display_text": "same launch text",
        "required_keywords": ["same launch text"],
        "min_score": 80,
        "require_unique": True,
    })

    assert result["ok"] is True
    assert result["value"]["verified"] is False
    assert result["value"]["reason"] == "ambiguous_target"
    dev.click.assert_not_called()


@pytest.mark.asyncio
async def test_fb_scan_posts_interact_likes_and_comments_keyword_post(
    executor_with_device,
):
    exc, dev = executor_with_device
    feed_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="Một bài viết về tuyển dụng AI trong doanh nghiệp" clickable="false" bounds="[42,520][1218,690]" />
        <node text="" content-desc="Nút Thích. Hãy nhấn đúp và giữ để bày tỏ cảm xúc về bình luận." clickable="true" bounds="[42,820][227,910]" />
        <node text="" content-desc="Nút Bình luận. Nhấn đúp để xem bình luận." clickable="true" bounds="[227,820][457,910]" />
      </node>
    </hierarchy>
    """
    comment_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node class="android.widget.EditText" text="" content-desc="Viết bình luận công khai" clickable="true" bounds="[42,2470][980,2590]" />
      </node>
    </hierarchy>
    """
    submit_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node class="android.widget.EditText" text="Quan điểm rất hữu ích" content-desc="Viết bình luận công khai" clickable="true" bounds="[42,2470][980,2590]" />
        <node text="Đăng" clickable="true" bounds="[1030,2470][1218,2590]" />
      </node>
    </hierarchy>
    """
    dev.dump_hierarchy.side_effect = [feed_xml, comment_xml, submit_xml]

    result = await exc.execute_flow(
        "serial",
        "social_scan_posts_interact",
        {
            "verify_like": False,
            "keywords": ["tuyển dụng", "AI"],
            "comment_text": "Quan điểm rất hữu ích",
            "target_count": 1,
            "max_scrolls": 0,
        },
    )

    assert result["ok"] is True
    value = result["value"]
    assert value["verified"] is True
    assert value["interacted_count"] == 1
    assert value["liked_count"] == 1
    assert value["commented_count"] == 1
    assert value["actions"][0]["matched_keywords"] == ["tuyen dung", "ai"]
    assert dev.click.call_args_list == [
        call(134, 865),
        call(342, 865),
        call(511, 2530),
        call(1124, 2530),
    ]
    dev.shell.assert_not_called()
    dev.assert_any_call(
        className="android.widget.EditText",
        description="Viết bình luận công khai",
    )
    dev.return_value.set_text.assert_called_once_with("Quan điểm rất hữu ích")


@pytest.mark.asyncio
async def test_fb_scan_posts_interact_closes_comment_overlay_before_scan(
    executor_with_device,
):
    exc, dev = executor_with_device
    overlay_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="Đóng" clickable="true" bounds="[560,133][700,175]" />
        <node class="android.widget.AutoCompleteTextView" text="" content-desc="Viết bình luận..." clickable="true" bounds="[42,2647][1218,2779]" />
      </node>
    </hierarchy>
    """
    feed_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="Một bài viết về tuyển dụng AI trong doanh nghiệp" clickable="false" bounds="[42,520][1218,690]" />
        <node text="" content-desc="Nút Thích. Hãy nhấn đúp và giữ để bày tỏ cảm xúc về bình luận." clickable="true" bounds="[42,820][227,910]" />
        <node text="" content-desc="Nút Bình luận. Nhấn đúp để xem bình luận." clickable="true" bounds="[227,820][457,910]" />
      </node>
    </hierarchy>
    """
    comment_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node class="android.widget.AutoCompleteTextView" text="" content-desc="Viết bình luận công khai" clickable="true" bounds="[42,2470][980,2590]" />
      </node>
    </hierarchy>
    """
    submit_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node class="android.widget.EditText" text="Quan điểm rất hữu ích" content-desc="Viết bình luận công khai" clickable="true" bounds="[42,2470][980,2590]" />
        <node text="Đăng" clickable="true" bounds="[1030,2470][1218,2590]" />
      </node>
    </hierarchy>
    """
    dev.dump_hierarchy.side_effect = [overlay_xml, feed_xml, comment_xml, submit_xml]

    result = await exc.execute_flow(
        "serial",
        "social_scan_posts_interact",
        {
            "verify_like": False,
            "keywords": ["AI"],
            "comment_text": "Quan điểm rất hữu ích",
            "target_count": 1,
            "max_scrolls": 0,
        },
    )

    assert result["ok"] is True
    value = result["value"]
    assert value["verified"] is True
    assert value["overlay_closes"] == 1
    assert value["interacted_count"] == 1
    assert value["commented_count"] == 1
    assert dev.click.call_args_list == [
        call(630, 154),
        call(134, 865),
        call(342, 865),
        call(511, 2530),
        call(1124, 2530),
    ]
    dev.shell.assert_not_called()
    dev.assert_any_call(
        className="android.widget.AutoCompleteTextView",
        description="Viết bình luận công khai",
    )


@pytest.mark.asyncio
async def test_fb_scan_posts_interact_closes_comment_filter_sheet_before_input(
    executor_with_device,
):
    exc, dev = executor_with_device
    feed_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="OpenClaw chia sẻ một ghi chú AI mới" clickable="false" bounds="[42,520][1218,690]" />
        <node text="" content-desc="Nút Thích. Hãy nhấn đúp và giữ để bày tỏ cảm xúc về bình luận." clickable="true" bounds="[42,820][227,910]" />
        <node text="" content-desc="Nút Bình luận. Nhấn đúp để xem bình luận." clickable="true" bounds="[227,820][457,910]" />
      </node>
    </hierarchy>
    """
    filter_sheet_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node class="android.widget.RadioButton" content-desc="Phù hợp nhất, Hiển thị bình luận của bạn bè trước tiên." clickable="true" bounds="[0,1877][1260,2236]" />
        <node class="android.widget.RadioButton" content-desc="Mới nhất, Hiển thị tất cả bình luận, mới nhất trước tiên." clickable="true" bounds="[0,2236][1260,2518]" />
        <node class="android.view.ViewGroup" content-desc="Tất cả bình luận, Hiển thị tất cả bình luận, bao gồm cả nội dung có thể là spam., hiện được chọn" bounds="[0,2518][1260,2800]" />
      </node>
    </hierarchy>
    """
    comment_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="" content-desc="Đang hiển thị Tất cả bình luận bình luận. Nhấn để thay đổi bộ lọc bình luận." clickable="true" bounds="[0,302][1260,470]" />
        <node class="android.widget.AutoCompleteTextView" text="" content-desc="Viết bình luận..." clickable="true" bounds="[42,2362][1218,2494]" />
      </node>
    </hierarchy>
    """
    submit_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node class="android.widget.AutoCompleteTextView" text="Thông tin hữu ích" content-desc="Viết bình luận..." clickable="true" bounds="[42,2362][1218,2494]" />
        <node text="" content-desc="Gửi" clickable="true" bounds="[1106,2501][1246,2641]" />
      </node>
    </hierarchy>
    """
    dev.dump_hierarchy.side_effect = [
        feed_xml,
        filter_sheet_xml,
        comment_xml,
        submit_xml,
    ]

    result = await exc.execute_flow(
        "serial",
        "social_scan_posts_interact",
        {
            "verify_like": False,
            "keywords": ["AI"],
            "comment_text": "Thông tin hữu ích",
            "target_count": 1,
            "max_scrolls": 0,
        },
    )

    assert result["ok"] is True
    value = result["value"]
    assert value["verified"] is True
    assert value["interacted_count"] == 1
    assert value["liked_count"] == 1
    assert value["commented_count"] == 1
    dev.press.assert_called_once_with("back")
    assert dev.click.call_args_list == [
        call(134, 865),
        call(342, 865),
        call(630, 2428),
        call(1176, 2571),
    ]


@pytest.mark.asyncio
async def test_fb_scan_posts_interact_closes_existing_comment_filter_sheet_before_scan(
    executor_with_device,
):
    exc, dev = executor_with_device
    filter_sheet_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node class="android.view.ViewGroup" content-desc="Phù hợp nhất, Hiển thị bình luận của bạn bè trước tiên., hiện được chọn" bounds="[0,1877][1260,2236]" />
        <node class="android.widget.RadioButton" content-desc="Mới nhất, Hiển thị tất cả bình luận, mới nhất trước tiên." clickable="true" bounds="[0,2236][1260,2518]" />
        <node class="android.widget.RadioButton" content-desc="Tất cả bình luận, Hiển thị tất cả bình luận, bao gồm cả nội dung có thể là spam." clickable="true" bounds="[0,2518][1260,2800]" />
      </node>
    </hierarchy>
    """
    feed_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="OpenClaw chia sẻ một ghi chú AI mới" clickable="false" bounds="[42,520][1218,690]" />
        <node text="" content-desc="Nút Thích. Hãy nhấn đúp và giữ để bày tỏ cảm xúc về bình luận." clickable="true" bounds="[42,820][227,910]" />
        <node text="" content-desc="Nút Bình luận. Nhấn đúp để xem bình luận." clickable="true" bounds="[227,820][457,910]" />
      </node>
    </hierarchy>
    """
    comment_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node class="android.widget.AutoCompleteTextView" text="" content-desc="Viết bình luận..." clickable="true" bounds="[42,2362][1218,2494]" />
      </node>
    </hierarchy>
    """
    submit_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node class="android.widget.AutoCompleteTextView" text="Thông tin hữu ích" content-desc="Viết bình luận..." clickable="true" bounds="[42,2362][1218,2494]" />
        <node text="" content-desc="Gửi" clickable="true" bounds="[1106,2501][1246,2641]" />
      </node>
    </hierarchy>
    """
    dev.dump_hierarchy.side_effect = [
        filter_sheet_xml,
        feed_xml,
        comment_xml,
        submit_xml,
    ]

    result = await exc.execute_flow(
        "serial",
        "social_scan_posts_interact",
        {
            "verify_like": False,
            "keywords": ["AI"],
            "comment_text": "Thông tin hữu ích",
            "target_count": 1,
            "max_scrolls": 0,
        },
    )

    assert result["ok"] is True
    value = result["value"]
    assert value["verified"] is True
    assert value["overlay_closes"] == 1
    assert value["commented_count"] == 1
    dev.press.assert_called_once_with("back")


@pytest.mark.asyncio
async def test_fb_scan_posts_interact_ignores_subscribe_text_when_submitting_comment(
    executor_with_device,
):
    exc, dev = executor_with_device
    feed_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="OpenClaw chia sẻ một ghi chú AI mới" clickable="false" bounds="[42,520][1218,690]" />
        <node text="" content-desc="Nút Thích. Hãy nhấn đúp và giữ để bày tỏ cảm xúc về bình luận." clickable="true" bounds="[42,820][227,910]" />
        <node text="" content-desc="Nút Bình luận. Nhấn đúp để xem bình luận." clickable="true" bounds="[227,820][457,910]" />
      </node>
    </hierarchy>
    """
    comment_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node class="android.widget.AutoCompleteTextView" text="" content-desc="Viết bình luận..." clickable="true" bounds="[42,2362][1218,2494]" />
      </node>
    </hierarchy>
    """
    submit_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="Đăng ký theo dõi Maid in Newquay" content-desc="Đăng ký theo dõi Maid in Newquay" clickable="true" bounds="[644,1367][1176,1495]" />
        <node class="android.widget.AutoCompleteTextView" text="Thông tin hữu ích" content-desc="Viết bình luận..." clickable="true" bounds="[42,2362][1218,2494]" />
        <node text="" content-desc="Gửi" clickable="true" bounds="[1106,2501][1246,2641]" />
      </node>
    </hierarchy>
    """
    dev.dump_hierarchy.side_effect = [feed_xml, comment_xml, submit_xml]

    result = await exc.execute_flow(
        "serial",
        "social_scan_posts_interact",
        {
            "verify_like": False,
            "keywords": ["AI"],
            "comment_text": "Thông tin hữu ích",
            "target_count": 1,
            "max_scrolls": 0,
        },
    )

    assert result["ok"] is True
    assert result["value"]["commented_count"] == 1
    assert dev.click.call_args_list[-1] == call(1176, 2571)


@pytest.mark.asyncio
async def test_fb_scan_posts_interact_scrolls_comment_sheet_to_input_node(
    executor_with_device,
):
    exc, dev = executor_with_device
    feed_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="OpenClaw chia sẻ một ghi chú AI mới" clickable="false" bounds="[42,520][1218,690]" />
        <node text="" content-desc="Nút Thích. Hãy nhấn đúp và giữ để bày tỏ cảm xúc về bình luận." clickable="true" bounds="[42,820][227,910]" />
        <node text="" content-desc="Nút Bình luận. Nhấn đúp để xem bình luận." clickable="true" bounds="[227,820][457,910]" />
      </node>
    </hierarchy>
    """
    comment_without_input_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="" content-desc="Đang hiển thị Tất cả bình luận bình luận. Nhấn để thay đổi bộ lọc bình luận." clickable="true" bounds="[0,302][1260,470]" />
        <node class="androidx.recyclerview.widget.RecyclerView" scrollable="true" bounds="[0,470][1260,2400]">
          <node text="Một bình luận dài" bounds="[42,620][1218,900]" />
        </node>
      </node>
    </hierarchy>
    """
    comment_with_input_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="" content-desc="Đang hiển thị Tất cả bình luận bình luận. Nhấn để thay đổi bộ lọc bình luận." clickable="true" bounds="[0,302][1260,470]" />
        <node class="androidx.recyclerview.widget.RecyclerView" scrollable="true" bounds="[0,470][1260,2400]" />
        <node class="android.widget.AutoCompleteTextView" text="" content-desc="Viết bình luận..." clickable="true" bounds="[42,2362][1218,2494]" />
      </node>
    </hierarchy>
    """
    submit_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node class="android.widget.AutoCompleteTextView" text="Thông tin hữu ích" content-desc="Viết bình luận..." clickable="true" bounds="[42,2362][1218,2494]" />
        <node text="" content-desc="Gửi" clickable="true" bounds="[1106,2501][1246,2641]" />
      </node>
    </hierarchy>
    """
    dev.dump_hierarchy.side_effect = [
        feed_xml,
        comment_without_input_xml,
        comment_with_input_xml,
        submit_xml,
    ]

    result = await exc.execute_flow(
        "serial",
        "social_scan_posts_interact",
        {
            "verify_like": False,
            "keywords": ["AI"],
            "comment_text": "Thông tin hữu ích",
            "target_count": 1,
            "max_scrolls": 0,
        },
    )

    assert result["ok"] is True
    assert result["value"]["commented_count"] == 1
    dev.swipe.assert_called()
    assert dev.click.call_args_list[-1] == call(1176, 2571)


@pytest.mark.asyncio
async def test_social_scan_posts_interact_uses_configured_node_terms(
    executor_with_device,
):
    exc, dev = executor_with_device
    feed_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="Release notes for AI workflow automation" clickable="false" bounds="[42,520][1218,690]" />
        <node text="Heart" clickable="true" bounds="[42,820][227,910]" />
        <node text="Reply" clickable="true" bounds="[227,820][457,910]" />
      </node>
    </hierarchy>
    """
    comment_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node class="android.widget.EditText" text="" content-desc="Say something" clickable="true" bounds="[42,2470][980,2590]" />
      </node>
    </hierarchy>
    """
    submit_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node class="android.widget.EditText" text="Useful note" content-desc="Say something" clickable="true" bounds="[42,2470][980,2590]" />
        <node text="Publish" clickable="true" bounds="[1030,2470][1218,2590]" />
      </node>
    </hierarchy>
    """
    dev.dump_hierarchy.side_effect = [feed_xml, comment_xml, submit_xml]

    result = await exc.execute_flow(
        "serial",
        "social_scan_posts_interact",
        {
            "verify_like": False,
            "keywords": ["workflow"],
            "comment_text": "Useful note",
            "target_count": 1,
            "max_scrolls": 0,
            "like_terms": ["Heart"],
            "comment_terms": ["Reply"],
            "comment_input_terms": ["Say something"],
            "comment_submit_terms": ["Publish"],
        },
    )

    assert result["ok"] is True
    value = result["value"]
    assert value["verified"] is True
    assert value["interacted_count"] == 1
    assert value["liked_count"] == 1
    assert value["commented_count"] == 1
    assert value["actions"][0]["matched_keywords"] == ["workflow"]
    assert dev.click.call_args_list == [
        call(134, 865),
        call(342, 865),
        call(511, 2530),
        call(1124, 2530),
    ]
    dev.shell.assert_not_called()
    dev.assert_any_call(
        className="android.widget.EditText",
        description="Say something",
    )


@pytest.mark.asyncio
async def test_fb_scan_posts_interact_expands_see_more_before_keyword_match(
    executor_with_device,
):
    exc, dev = executor_with_device
    truncated_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="Mình đang chia sẻ vài ghi chú dài… xem thêm" clickable="true" bounds="[42,620][1218,720]">
          <node text="xem thêm" clickable="true" bounds="[940,650][1150,710]" />
        </node>
        <node text="" content-desc="Nút Thích. Hãy nhấn đúp và giữ để bày tỏ cảm xúc về bình luận." clickable="true" bounds="[42,820][227,910]" />
        <node text="" content-desc="Nút Bình luận. Nhấn đúp để xem bình luận." clickable="true" bounds="[227,820][457,910]" />
      </node>
    </hierarchy>
    """
    expanded_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="Mình đang chia sẻ vài ghi chú dài về tuyển dụng AI trong doanh nghiệp" clickable="false" bounds="[42,520][1218,720]" />
        <node text="" content-desc="Nút Thích. Hãy nhấn đúp và giữ để bày tỏ cảm xúc về bình luận." clickable="true" bounds="[42,820][227,910]" />
        <node text="" content-desc="Nút Bình luận. Nhấn đúp để xem bình luận." clickable="true" bounds="[227,820][457,910]" />
      </node>
    </hierarchy>
    """
    comment_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node class="android.widget.EditText" text="" content-desc="Viết bình luận công khai" clickable="true" bounds="[42,2470][980,2590]" />
      </node>
    </hierarchy>
    """
    submit_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node class="android.widget.EditText" text="Quan điểm rất hữu ích" content-desc="Viết bình luận công khai" clickable="true" bounds="[42,2470][980,2590]" />
        <node text="Đăng" clickable="true" bounds="[1030,2470][1218,2590]" />
      </node>
    </hierarchy>
    """
    dev.dump_hierarchy.side_effect = [
        truncated_xml,
        expanded_xml,
        comment_xml,
        submit_xml,
    ]

    result = await exc.execute_flow(
        "serial",
        "social_scan_posts_interact",
        {
            "verify_like": False,
            "keywords": ["tuyển dụng AI"],
            "comment_text": "Quan điểm rất hữu ích",
            "target_count": 1,
            "max_scrolls": 0,
        },
    )

    assert result["ok"] is True
    value = result["value"]
    assert value["verified"] is True
    assert value["expanded_more_count"] == 1
    assert value["interacted_count"] == 1
    assert value["actions"][0]["matched_keywords"] == ["tuyen dung ai"]
    assert dev.click.call_args_list == [
        call(1045, 680),
        call(134, 865),
        call(342, 865),
        call(511, 2530),
        call(1124, 2530),
    ]
    dev.shell.assert_not_called()


@pytest.mark.asyncio
async def test_fb_scan_posts_interact_expands_parent_see_more_label(
    executor_with_device,
):
    exc, dev = executor_with_device
    truncated_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="Mình đang chia sẻ vài ghi chú dài… Xem thêm" content-desc="Mình đang chia sẻ vài ghi chú dài… Xem thêm" clickable="true" bounds="[42,620][1218,720]" />
        <node text="" content-desc="Nút Thích. Hãy nhấn đúp và giữ để bày tỏ cảm xúc về bình luận." clickable="true" bounds="[42,820][227,910]" />
        <node text="" content-desc="Nút Bình luận. Nhấn đúp để xem bình luận." clickable="true" bounds="[227,820][457,910]" />
      </node>
    </hierarchy>
    """
    expanded_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="Mình đang chia sẻ vài ghi chú dài về tuyển dụng AI trong doanh nghiệp" clickable="false" bounds="[42,520][1218,720]" />
        <node text="" content-desc="Nút Thích. Hãy nhấn đúp và giữ để bày tỏ cảm xúc về bình luận." clickable="true" bounds="[42,820][227,910]" />
        <node text="" content-desc="Nút Bình luận. Nhấn đúp để xem bình luận." clickable="true" bounds="[227,820][457,910]" />
      </node>
    </hierarchy>
    """
    comment_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node class="android.widget.EditText" text="" content-desc="Viết bình luận công khai" clickable="true" bounds="[42,2470][980,2590]" />
      </node>
    </hierarchy>
    """
    submit_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node class="android.widget.EditText" text="Quan điểm rất hữu ích" content-desc="Viết bình luận công khai" clickable="true" bounds="[42,2470][980,2590]" />
        <node text="Đăng" clickable="true" bounds="[1030,2470][1218,2590]" />
      </node>
    </hierarchy>
    """
    dev.dump_hierarchy.side_effect = [
        truncated_xml,
        expanded_xml,
        comment_xml,
        submit_xml,
    ]

    result = await exc.execute_flow(
        "serial",
        "social_scan_posts_interact",
        {
            "verify_like": False,
            "keywords": ["tuyển dụng AI"],
            "comment_text": "Quan điểm rất hữu ích",
            "target_count": 1,
            "max_scrolls": 0,
        },
    )

    assert result["ok"] is True
    value = result["value"]
    assert value["verified"] is True
    assert value["expanded_more_count"] == 1
    assert value["interacted_count"] == 1
    assert dev.click.call_args_list[0] == call(1058, 670)


@pytest.mark.asyncio
async def test_fb_scan_posts_interact_rejects_profile_surface(
    executor_with_device,
):
    exc, dev = executor_with_device
    profile_xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="Cover Photo" clickable="false" bounds="[0,0][1260,524]" />
        <node text="Chip AI đang được sản xuất nhanh hơn" clickable="false" bounds="[420,503][1218,2306]" />
        <node text="Thêm bạn bè" clickable="true" bounds="[42,2547][1218,2673]" />
        <node text="Chia sẻ trang cá nhân" clickable="true" bounds="[1106,133][1260,287]" />
      </node>
    </hierarchy>
    """
    dev.dump_hierarchy.return_value = profile_xml

    result = await exc.execute_flow(
        "serial",
        "social_scan_posts_interact",
        {
            "verify_like": False,
            "keywords": ["Chip AI"],
            "comment_text": "Quan điểm rất hữu ích",
            "target_count": 1,
            "max_scrolls": 0,
        },
    )

    assert result["ok"] is True
    assert result["value"]["verified"] is False
    # A profile page is not a feed with nothing on topic — it has no post action
    # rows at all. The two used to share one reason, which is how a loop could
    # rescan the wrong screen 88 times and call every attempt normal.
    assert result["value"]["reason"] == "screen_is_not_a_feed"
    assert result["value"]["interacted_count"] == 0
    dev.click.assert_not_called()


# ── Unknown flow ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_flow_returns_error(executor_with_device):
    exc, dev = executor_with_device
    result = await exc.execute_flow("serial", "nonexistent", {})

    assert result["ok"] is False
    assert "unknown flow" in result["error"]


@pytest.mark.asyncio
async def test_fb_scan_posts_interact_stops_on_group_join_questionnaire(
    executor_with_device,
):
    """The screen that stalled a real run for 88 iterations.

    Commenting on a post in a group the account has not joined makes Facebook
    open its join questionnaire — full screen, rules checkbox already ticked,
    Send one tap away. The scan flow did not classify screens at all, so it kept
    rescanning and swiping the form and reported ok every time.
    """
    exc, dev = executor_with_device
    join_form = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="Câu hỏi dành cho người tham gia" clickable="false" bounds="[100,180][1160,260]" />
        <node text="Quy tắc nhóm của quản trị viên" clickable="false" bounds="[40,380][1160,460]" />
        <node text="Tôi đồng ý với các quy tắc nhóm" clickable="true" bounds="[40,520][1160,600]" />
        <node text="Gửi" clickable="true" bounds="[40,2380][1220,2520]" />
      </node>
    </hierarchy>
    """
    dev.dump_hierarchy.return_value = join_form

    result = await exc.execute_flow(
        "serial",
        "social_scan_posts_interact",
        {
            "verify_like": False,
            "keywords": ["ai"],
            "comment_text": "Bài viết rất hữu ích",
            "target_count": 1,
            "max_scrolls": 0,
        },
    )

    value = result["value"]
    assert value["verified"] is False
    # Back never clears it here (the mock keeps returning the same screen), so
    # the flow must say so instead of scrolling a form.
    assert value["reason"] == "surface_not_dismissable"
    assert value["retryable"] is False
    assert value["surface_marker"]
    # Nothing was pressed on that form beyond the single Back attempt.
    assert dev.click.call_count == 0


@pytest.mark.asyncio
async def test_fb_scan_posts_interact_ignores_overlay_shaped_feed(
    executor_with_device,
):
    """Geometry alone must never abort a run.

    _fb_overlay_bounds calls any wide node anchored to the bottom a sheet, and a
    feed's own list container fits that shape. Acting on that reading would stop
    healthy runs, so an unnamed overlay is left alone.
    """
    exc, dev = executor_with_device
    feed = """<?xml version='1.0'?>
    <hierarchy>
      <node text="" content-desc="" clickable="false" bounds="[0,0][1260,2800]">
        <node text="" clickable="false" bounds="[0,900][1260,2800]">
          <node text="Nguyen Van A" clickable="false" bounds="[40,950][400,1010]" />
          <node text="Hom nay troi dep" clickable="false" bounds="[40,1020][900,1090]" />
          <node text="Thích" clickable="true" bounds="[100,1200][250,1280]" />
          <node text="Bình luận" clickable="true" bounds="[300,1200][450,1280]" />
        </node>
      </node>
    </hierarchy>
    """
    dev.dump_hierarchy.return_value = feed

    result = await exc.execute_flow(
        "serial",
        "social_scan_posts_interact",
        {
            "verify_like": False,
            "keywords": ["wordpress"],
            "target_count": 1,
            "max_scrolls": 0,
        },
    )

    value = result["value"]
    # Reached the scanner and reported a keyword miss — not a surface abort.
    assert value["reason"] == "no_matching_post"
    assert dev.press.call_count == 0
