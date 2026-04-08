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
    pool.get_session = AsyncMock(return_value=mock_device)
    exc = U2Executor(pool=pool, loop=event_loop)
    return exc, mock_device, pool


# ── Batch tests ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_batch_empty(executor):
    exc, dev, pool = executor
    result = await exc.run_batch("serial", [], early_exit=True)
    assert result["ok"] is True
    assert result["results"] == []
    pool.get_session.assert_not_called()


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


@pytest.mark.asyncio
async def test_session_unavailable(event_loop):
    pool = AsyncMock()
    pool.get_session = AsyncMock(side_effect=RuntimeError("no device"))
    exc = U2Executor(pool=pool, loop=event_loop)

    result = await exc.run_batch("serial", [{"op": "click", "x": 1, "y": 2}])
    assert result["ok"] is False
    assert result["stopped_at"] == 0
    assert "session unavailable" in result["error"]


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
