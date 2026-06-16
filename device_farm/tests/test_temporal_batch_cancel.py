"""Tests for cooperative batch activity cancellation."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from temporal.shared import DeviceActionBatchInput, DeviceActionBatchResult


def test_device_action_batch_temporal_retry_is_single_attempt():
    """Device actions are side-effectful; Temporal must not replay a timed-out batch."""
    import ast
    from pathlib import Path

    from temporal import workflows
    from temporal.workflows import _DEVICE_ACTION_RETRY

    assert _DEVICE_ACTION_RETRY.maximum_attempts == 1

    source = Path(workflows.__file__).read_text()
    module = ast.parse(source)
    batch_calls = [
        node
        for node in ast.walk(module)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", "") == "execute_activity"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "execute_device_action_batch"
    ]
    assert batch_calls, "execute_device_action_batch call site not found"
    for call in batch_calls:
        retry_kw = next((kw for kw in call.keywords if kw.arg == "retry_policy"), None)
        assert retry_kw is not None
        assert isinstance(retry_kw.value, ast.Name)
        assert retry_kw.value.id == "_DEVICE_ACTION_RETRY"


@pytest.mark.asyncio
async def test_execute_device_action_batch_returns_cancelled_mid_batch():
    from temporal.activities import DeviceActivities

    activities = DeviceActivities()
    inp = DeviceActionBatchInput(
        device_serial="SN001",
        steps=[{"type": "wait", "seconds": 1}],
        step_indices=[0],
        execution_id="exec-1",
    )

    mock_device = MagicMock()
    mock_device.model = "test"
    mock_device.ensure_u2_healthy = MagicMock()

    with (
        patch("temporal.activities._get_device", return_value=mock_device),
        patch("temporal.activities._validate_serial"),
        patch("temporal.activities._prepare_activity_step", side_effect=lambda s: s),
        patch("temporal.activities._build_activity_mini_scenario", return_value={"steps": []}),
        patch("temporal.activities._emit_step_events_for_activity", AsyncMock()),
        patch("temporal.activities.activity") as mock_activity,
        patch(
            "services.execution_pause_flags.is_execution_cancelled_async",
            AsyncMock(return_value=True),
        ),
        patch(
            "services.execution_pause_flags.is_execution_paused_async",
            AsyncMock(return_value=False),
        ),
    ):
        mock_activity.heartbeat = MagicMock()
        mock_activity.is_cancelled = MagicMock(return_value=False)
        result = await activities.execute_device_action_batch(inp)

    assert isinstance(result, DeviceActionBatchResult)
    assert result.cancelled_mid_batch is True
    assert result.results == []
