"""Tests for relay.u2_executor — batch executor + primitive ops."""
from __future__ import annotations

import asyncio
import base64
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from relay.u2_executor import U2Executor, _resolve


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
