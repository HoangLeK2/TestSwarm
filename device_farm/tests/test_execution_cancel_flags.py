"""Tests for cooperative execution cancel flags."""
from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.execution_pause_flags import (
    clear_execution_cancelled,
    is_execution_cancelled_async,
    is_execution_cancelled_local,
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
