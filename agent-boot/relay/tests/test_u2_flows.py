"""Tests for relay.u2_executor — named flow functions."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from relay.u2_executor import U2Executor


@pytest.fixture
def executor_with_device(event_loop):
    pool = AsyncMock()
    dev = MagicMock()
    pool.get_session = AsyncMock(return_value=dev)
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
