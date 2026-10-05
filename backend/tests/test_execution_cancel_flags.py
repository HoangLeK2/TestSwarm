"""Tests for cooperative execution cancel flags."""
from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.execution_pause_flags import (
    clear_execution_cancelled,
    clear_execution_paused,
    is_execution_cancelled_async,
    is_execution_cancelled_local,
    set_execution_paused,
    set_execution_cancelled,
)
from temporal.activities import _to_thread_with_heartbeat


@pytest.mark.asyncio
async def test_set_and_check_execution_cancelled_local():
    await set_execution_cancelled("exec-1")
    assert is_execution_cancelled_local("exec-1") is True
    await clear_execution_cancelled("exec-1")
    assert is_execution_cancelled_local("exec-1") is False


@pytest.mark.asyncio
async def test_successful_thread_lifecycle_is_debug_only():
    with (
        patch("temporal.activities.trace_log") as trace_log,
        patch("temporal.activities.activity") as mock_activity,
    ):
        mock_activity.heartbeat = MagicMock()
        mock_activity.is_cancelled = MagicMock(return_value=False)

        result = await _to_thread_with_heartbeat(
            lambda: "done",
            heartbeat_interval=0.05,
        )

    assert result == "done"
    assert [call.args[0] for call in trace_log.debug.call_args_list] == [
        "temporal_thread_start",
        "temporal_thread_end",
    ]
    trace_log.info.assert_not_called()
    trace_log.warning.assert_not_called()


@pytest.mark.asyncio
async def test_to_thread_with_heartbeat_stops_on_execution_cancel_flag():
    cancel_event = threading.Event()
    started = threading.Event()
    poll_count = 0

    def _slow_work() -> str:
        started.set()
        while not cancel_event.is_set():
            time.sleep(0.05)
        return "stopped"

    async def _cancelled_after_polls(_execution_id: str) -> bool:
        nonlocal poll_count
        poll_count += 1
        return poll_count >= 2

    with patch("temporal.activities.activity") as mock_activity:
        mock_activity.heartbeat = MagicMock()
        mock_activity.is_cancelled = MagicMock(return_value=False)

        with patch(
            "services.execution_pause_flags.is_execution_cancelled_async",
            side_effect=_cancelled_after_polls,
        ):
            result = await _to_thread_with_heartbeat(
                _slow_work,
                cooperative_cancel_event=cancel_event,
                execution_id="exec-cancel-1",
                heartbeat_interval=0.05,
                cancel_grace_s=2.0,
            )

    assert started.is_set()
    assert cancel_event.is_set()
    assert result == "stopped"


@pytest.mark.asyncio
async def test_to_thread_with_heartbeat_stops_on_execution_pause_flag():
    cancel_event = threading.Event()
    started = threading.Event()

    def _slow_work() -> str:
        started.set()
        while not cancel_event.is_set():
            time.sleep(0.05)
        return "paused"

    try:
        await set_execution_paused("exec-pause-1")
        with patch("temporal.activities.activity") as mock_activity:
            mock_activity.heartbeat = MagicMock()
            mock_activity.is_cancelled = MagicMock(return_value=False)

            with patch(
                "services.execution_pause_flags.is_execution_cancelled_async",
                AsyncMock(return_value=False),
            ):
                result = await _to_thread_with_heartbeat(
                    _slow_work,
                    cooperative_cancel_event=cancel_event,
                    execution_id="exec-pause-1",
                    heartbeat_interval=0.05,
                    cancel_grace_s=2.0,
                    stop_on_pause=True,
                )
    finally:
        await clear_execution_paused("exec-pause-1")

    assert started.is_set()
    assert cancel_event.is_set()
    assert result == "paused"


@pytest.mark.asyncio
async def test_to_thread_with_heartbeat_stops_on_temporal_activity_cancel():
    started = threading.Event()

    def _slow_work() -> str:
        started.set()
        time.sleep(10.0)
        return "done"

    with patch("temporal.activities.activity") as mock_activity:
        mock_activity.heartbeat = MagicMock()
        mock_activity.is_cancelled = MagicMock(side_effect=[False, True])

        with pytest.raises(asyncio.CancelledError):
            await _to_thread_with_heartbeat(
                _slow_work,
                heartbeat_interval=0.05,
                cancel_grace_s=0.2,
            )

    assert started.is_set()
