"""Tests for cooperative batch activity cancellation."""
from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from temporal.shared import DeviceActionBatchInput, DeviceActionBatchResult


@pytest.fixture(autouse=True)
def _isolate_campaign_claim_database():
    """These batch-unit tests do not exercise campaign claim persistence."""
    with patch(
        "temporal.activities._heartbeat_campaign_device_claim",
        AsyncMock(),
    ):
        yield


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


def test_device_action_batch_timeout_includes_recovery_deadline_margin():
    """Recovery-enabled batches need enough Temporal time to return the step failure."""
    from temporal.workflows import _batch_start_to_close_timeout

    assert _batch_start_to_close_timeout(4, {}) == timedelta(seconds=480)

    timeout = _batch_start_to_close_timeout(
        4,
        {
            "recovery_policy": {
                "enabled": True,
                "rules": [
                    {
                        "id": "stuck-screen",
                        "incident_type": "stuck_screen",
                        "scenario_id": "recover",
                        "timeout_ms": 480_000,
                    }
                ],
            },
        },
    )

    assert timeout == timedelta(seconds=990)


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


@pytest.mark.asyncio
async def test_execute_device_action_batch_uses_single_u2_batch_for_touch_primitives():
    from temporal.activities import DeviceActivities

    activities = DeviceActivities()
    inp = DeviceActionBatchInput(
        device_serial="SN001",
        steps=[
            {"type": "tap_position", "pos": "top_center"},
            {
                "type": "swipe_ratio",
                "x1": 0.5,
                "y1": 0.8,
                "x2": 0.5,
                "y2": 0.2,
                "duration_ms": 400,
            },
        ],
        step_indices=[3, 4],
        execution_id="exec-1",
    )

    mock_device = MagicMock()
    mock_device.model = "test"
    mock_device.screen_width = 1000
    mock_device.screen_height = 2000
    mock_device.ensure_u2_healthy = MagicMock()
    mock_device._batch_enabled = MagicMock(return_value=True)
    mock_device.u2_batch = MagicMock(return_value=[
        {"op": "click", "ok": True},
        {"op": "swipe", "ok": True},
    ])

    with (
        patch("temporal.activities._get_device", return_value=mock_device),
        patch("temporal.activities._validate_serial"),
        patch("temporal.activities._emit_step_events_for_activity", AsyncMock()),
        patch("temporal.activities.activity") as mock_activity,
        patch("tasks.scenario_task.run_scenario_task", MagicMock()) as run_scenario_task,
        patch(
            "services.execution_pause_flags.is_execution_cancelled_async",
            AsyncMock(return_value=False),
        ),
        patch(
            "services.execution_pause_flags.is_execution_paused_async",
            AsyncMock(return_value=False),
        ),
    ):
        mock_activity.heartbeat = MagicMock()
        mock_activity.is_cancelled = MagicMock(return_value=False)
        result = await activities.execute_device_action_batch(inp)

    assert mock_device.u2_batch.call_count == 1
    args, kwargs = mock_device.u2_batch.call_args
    assert args == ([
        {"op": "click", "x": 500, "y": 200},
        {
            "op": "swipe",
            "fx": 500,
            "fy": 1600,
            "tx": 500,
            "ty": 400,
            "duration": 0.4,
        },
    ],)
    assert kwargs["timeout"] == 3.0
    assert "cancel_event" in kwargs
    run_scenario_task.assert_not_called()
    assert result.first_failure_index == -1
    assert [item["index"] for item in result.results] == [3, 4]
    assert all(item["ok"] for item in result.results)


@pytest.mark.asyncio
async def test_execute_device_action_batch_caches_pause_cancel_probes_within_fast_batch():
    from temporal.activities import DeviceActivities

    activities = DeviceActivities()
    inp = DeviceActionBatchInput(
        device_serial="SN001",
        steps=[
            {"type": "tap_position", "pos": "middle_center"},
            {"type": "tap_position", "pos": "bottom_center"},
            {"type": "tap_position", "pos": "top_center"},
        ],
        step_indices=[0, 1, 2],
        execution_id="exec-1",
    )

    mock_device = MagicMock()
    mock_device.model = "test"
    mock_device.screen_width = 1000
    mock_device.screen_height = 2000
    mock_device.ensure_u2_healthy = MagicMock()
    mock_device._batch_enabled = MagicMock(return_value=True)
    mock_device.u2_batch = MagicMock(return_value=[
        {"op": "click", "ok": True},
        {"op": "click", "ok": True},
        {"op": "click", "ok": True},
    ])

    cancelled = AsyncMock(return_value=False)
    paused = AsyncMock(return_value=False)

    with (
        patch("temporal.activities._get_device", return_value=mock_device),
        patch("temporal.activities._validate_serial"),
        patch("temporal.activities._emit_step_events_for_activity", AsyncMock()),
        patch("temporal.activities.activity") as mock_activity,
        patch("services.execution_pause_flags.is_execution_cancelled_local", return_value=False),
        patch("services.execution_pause_flags.is_execution_paused_local", return_value=False),
        patch("services.execution_pause_flags.is_execution_cancelled_async", cancelled),
        patch("services.execution_pause_flags.is_execution_paused_async", paused),
    ):
        mock_activity.heartbeat = MagicMock()
        mock_activity.is_cancelled = MagicMock(return_value=False)
        result = await activities.execute_device_action_batch(inp)

    assert result.first_failure_index == -1
    assert cancelled.await_count == 1
    assert paused.await_count == 1


@pytest.mark.asyncio
async def test_execute_device_action_batch_runs_u2_batch_with_heartbeat_thread():
    from temporal.activities import DeviceActivities

    activities = DeviceActivities()
    inp = DeviceActionBatchInput(
        device_serial="SN001",
        steps=[{"type": "tap_position", "pos": "middle_center"}],
        step_indices=[0],
        execution_id="exec-1",
    )

    mock_device = MagicMock()
    mock_device.model = "test"
    mock_device.screen_width = 1000
    mock_device.screen_height = 2000
    mock_device.ensure_u2_healthy = MagicMock()
    mock_device._batch_enabled = MagicMock(return_value=True)
    mock_device.u2_batch = MagicMock()
    run_with_heartbeat = AsyncMock(return_value=[{"op": "click", "ok": True}])

    with (
        patch("temporal.activities._get_device", return_value=mock_device),
        patch("temporal.activities._validate_serial"),
        patch("temporal.activities._emit_step_events_for_activity", AsyncMock()),
        patch("temporal.activities._to_thread_with_heartbeat", run_with_heartbeat),
        patch("temporal.activities.activity") as mock_activity,
        patch(
            "services.execution_pause_flags.is_execution_cancelled_async",
            AsyncMock(return_value=False),
        ),
        patch(
            "services.execution_pause_flags.is_execution_paused_async",
            AsyncMock(return_value=False),
        ),
    ):
        mock_activity.heartbeat = MagicMock()
        mock_activity.is_cancelled = MagicMock(return_value=False)
        result = await activities.execute_device_action_batch(inp)

    assert result.first_failure_index == -1
    run_with_heartbeat.assert_awaited_once()
    args, kwargs = run_with_heartbeat.await_args
    assert args[0] is mock_device.u2_batch
    assert args[1] == [{"op": "click", "x": 500, "y": 1000}]
    assert kwargs["timeout"] == 1.5
    assert kwargs["execution_id"] == "exec-1"
    assert "cooperative_cancel_event" in kwargs


@pytest.mark.asyncio
async def test_execute_device_action_batch_does_not_fast_path_tap_ratio_post_wait():
    from temporal.activities import DeviceActivities

    activities = DeviceActivities()
    inp = DeviceActionBatchInput(
        device_serial="SN001",
        steps=[{"type": "tap_ratio", "x": 0.5, "y": 0.5}],
        step_indices=[0],
        execution_id="exec-1",
    )

    mock_device = MagicMock()
    mock_device.model = "test"
    mock_device.screen_width = 1000
    mock_device.screen_height = 2000
    mock_device.ensure_u2_healthy = MagicMock()
    mock_device._batch_enabled = MagicMock(return_value=True)
    mock_device.u2_batch = MagicMock()

    with (
        patch("temporal.activities._get_device", return_value=mock_device),
        patch("temporal.activities._validate_serial"),
        patch("temporal.activities._prepare_activity_step", side_effect=lambda s: s),
        patch("temporal.activities._build_activity_mini_scenario", return_value={"steps": []}),
        patch("temporal.activities._emit_step_events_for_activity", AsyncMock()),
        patch("temporal.activities.activity") as mock_activity,
        patch("tasks.scenario_task.run_scenario_task", MagicMock(return_value={
            "step_results": [{"ok": True, "message": ""}],
        })) as run_scenario_task,
        patch(
            "services.execution_pause_flags.is_execution_cancelled_async",
            AsyncMock(return_value=False),
        ),
        patch(
            "services.execution_pause_flags.is_execution_paused_async",
            AsyncMock(return_value=False),
        ),
    ):
        mock_activity.heartbeat = MagicMock()
        mock_activity.is_cancelled = MagicMock(return_value=False)
        result = await activities.execute_device_action_batch(inp)

    mock_device.u2_batch.assert_not_called()
    run_scenario_task.assert_called_once()
    assert result.first_failure_index == -1


@pytest.mark.asyncio
async def test_execute_device_action_batch_maps_u2_batch_failure_to_step_index():
    from temporal.activities import DeviceActivities

    activities = DeviceActivities()
    inp = DeviceActionBatchInput(
        device_serial="SN001",
        steps=[
            {"type": "tap_position", "pos": "middle_center"},
            {"type": "tap_position", "pos": "bottom_center"},
            {"type": "tap_position", "pos": "top_center"},
        ],
        step_indices=[10, 11, 12],
        execution_id="exec-1",
        scenario_config={"primitive_touch_batch_size": 3},
    )

    mock_device = MagicMock()
    mock_device.model = "test"
    mock_device.screen_width = 1000
    mock_device.screen_height = 2000
    mock_device.ensure_u2_healthy = MagicMock()
    mock_device._batch_enabled = MagicMock(return_value=True)
    mock_device.u2_batch = MagicMock(return_value=[
        {"op": "click", "ok": True},
        {"op": "click", "ok": False, "error": "tap failed"},
    ])
    emit_events = AsyncMock()

    with (
        patch("temporal.activities._get_device", return_value=mock_device),
        patch("temporal.activities._validate_serial"),
        patch("temporal.activities._emit_step_events_for_activity", emit_events),
        patch("temporal.activities.activity") as mock_activity,
        patch(
            "services.execution_pause_flags.is_execution_cancelled_async",
            AsyncMock(return_value=False),
        ),
        patch(
            "services.execution_pause_flags.is_execution_paused_async",
            AsyncMock(return_value=False),
        ),
    ):
        mock_activity.heartbeat = MagicMock()
        mock_activity.is_cancelled = MagicMock(return_value=False)
        result = await activities.execute_device_action_batch(inp)

    assert result.first_failure_index == 1
    assert [item["index"] for item in result.results] == [10, 11]
    assert result.results[0]["ok"] is True
    assert result.results[1]["ok"] is False
    assert result.results[1]["message"] == "tap failed"
    assert [call.kwargs["step_index"] for call in emit_events.await_args_list] == [10, 10, 11, 11]
    finished_results = [
        call.kwargs["step_result"]
        for call in emit_events.await_args_list
        if call.kwargs.get("phase") == "finished"
    ]
    assert all(item["duration_ms"] >= 0 for item in finished_results)
    assert all(item["u2_batch_duration_ms"] >= item["duration_ms"] for item in finished_results)
    assert result.results[0]["details"]["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_execute_device_action_batch_maps_raised_u2_batch_action_failure():
    from temporal.activities import DeviceActivities

    activities = DeviceActivities()
    inp = DeviceActionBatchInput(
        device_serial="SN001",
        steps=[
            {"type": "tap_position", "pos": "middle_center"},
            {"type": "tap_position", "pos": "bottom_center"},
            {"type": "tap_position", "pos": "top_center"},
        ],
        step_indices=[10, 11, 12],
        execution_id="exec-1",
        scenario_config={"primitive_touch_batch_size": 3},
    )

    mock_device = MagicMock()
    mock_device.model = "test"
    mock_device.screen_width = 1000
    mock_device.screen_height = 2000
    mock_device.ensure_u2_healthy = MagicMock()
    mock_device._batch_enabled = MagicMock(return_value=True)
    mock_device.u2_batch = MagicMock(side_effect=RuntimeError("action[1] click: tap failed"))
    emit_events = AsyncMock()

    with (
        patch("temporal.activities._get_device", return_value=mock_device),
        patch("temporal.activities._validate_serial"),
        patch("temporal.activities._emit_step_events_for_activity", emit_events),
        patch("temporal.activities.activity") as mock_activity,
        patch(
            "services.execution_pause_flags.is_execution_cancelled_async",
            AsyncMock(return_value=False),
        ),
        patch(
            "services.execution_pause_flags.is_execution_paused_async",
            AsyncMock(return_value=False),
        ),
    ):
        mock_activity.heartbeat = MagicMock()
        mock_activity.is_cancelled = MagicMock(return_value=False)
        result = await activities.execute_device_action_batch(inp)

    assert result.first_failure_index == 1
    assert [item["index"] for item in result.results] == [10, 11]
    assert result.results[0]["ok"] is True
    assert result.results[1]["ok"] is False
    assert result.results[1]["message"] == "action[1] click: tap failed"
    assert [call.kwargs["step_index"] for call in emit_events.await_args_list] == [10, 10, 11, 11]


@pytest.mark.asyncio
async def test_execute_device_action_batch_maps_u2_batch_error_partial_results():
    from runtime.transports.u2_jsonrpc import U2BatchError
    from temporal.activities import DeviceActivities

    activities = DeviceActivities()
    inp = DeviceActionBatchInput(
        device_serial="SN001",
        steps=[
            {"type": "tap_position", "pos": "middle_center"},
            {"type": "tap_position", "pos": "bottom_center"},
            {"type": "tap_position", "pos": "top_center"},
        ],
        step_indices=[10, 11, 12],
        execution_id="exec-1",
        scenario_config={"primitive_touch_batch_size": 3},
    )

    mock_device = MagicMock()
    mock_device.model = "test"
    mock_device.screen_width = 1000
    mock_device.screen_height = 2000
    mock_device.ensure_u2_healthy = MagicMock()
    mock_device._batch_enabled = MagicMock(return_value=True)
    mock_device.u2_batch = MagicMock(side_effect=U2BatchError(
        "tap failed",
        stopped_at=1,
        results=[
            {"op": "click", "ok": True},
            {"op": "click", "ok": False, "error": "tap failed"},
        ],
    ))
    emit_events = AsyncMock()

    with (
        patch("temporal.activities._get_device", return_value=mock_device),
        patch("temporal.activities._validate_serial"),
        patch("temporal.activities._emit_step_events_for_activity", emit_events),
        patch("temporal.activities.activity") as mock_activity,
        patch(
            "services.execution_pause_flags.is_execution_cancelled_async",
            AsyncMock(return_value=False),
        ),
        patch(
            "services.execution_pause_flags.is_execution_paused_async",
            AsyncMock(return_value=False),
        ),
    ):
        mock_activity.heartbeat = MagicMock()
        mock_activity.is_cancelled = MagicMock(return_value=False)
        result = await activities.execute_device_action_batch(inp)

    assert result.first_failure_index == 1
    assert [item["index"] for item in result.results] == [10, 11]
    assert result.results[0]["ok"] is True
    assert result.results[1]["ok"] is False
    assert result.results[1]["message"] == "tap failed"
    assert [call.kwargs["step_index"] for call in emit_events.await_args_list] == [10, 10, 11, 11]


@pytest.mark.asyncio
async def test_execute_device_action_batch_returns_partial_successes_when_paused_during_batch():
    from runtime.transports.u2_jsonrpc import U2BatchError
    from temporal.activities import DeviceActivities

    activities = DeviceActivities()
    inp = DeviceActionBatchInput(
        device_serial="SN001",
        steps=[
            {"type": "tap_position", "pos": "middle_center"},
            {"type": "tap_position", "pos": "bottom_center"},
            {"type": "tap_position", "pos": "top_center"},
        ],
        step_indices=[10, 11, 12],
        execution_id="exec-1",
        scenario_config={"primitive_touch_batch_size": 3},
    )

    def _pause_after_first_action(*_args, **kwargs):
        kwargs["cancel_event"].set()
        raise U2BatchError(
            "cancelled",
            stopped_at=1,
            results=[{"op": "click", "ok": True}],
            cancelled=True,
        )

    mock_device = MagicMock()
    mock_device.model = "test"
    mock_device.screen_width = 1000
    mock_device.screen_height = 2000
    mock_device.ensure_u2_healthy = MagicMock()
    mock_device._batch_enabled = MagicMock(return_value=True)
    mock_device.u2_batch = MagicMock(side_effect=_pause_after_first_action)
    emit_events = AsyncMock()
    paused = AsyncMock(side_effect=[False, True])

    with (
        patch("temporal.activities._get_device", return_value=mock_device),
        patch("temporal.activities._validate_serial"),
        patch("temporal.activities._emit_step_events_for_activity", emit_events),
        patch("temporal.activities.activity") as mock_activity,
        patch(
            "services.execution_pause_flags.is_execution_cancelled_async",
            AsyncMock(return_value=False),
        ),
        patch(
            "services.execution_pause_flags.is_execution_paused_async",
            paused,
        ),
    ):
        mock_activity.heartbeat = MagicMock()
        mock_activity.is_cancelled = MagicMock(return_value=False)
        result = await activities.execute_device_action_batch(inp)

    assert result.paused_mid_batch is True
    assert result.cancelled_mid_batch is False
    assert result.first_failure_index == -1
    assert [item["index"] for item in result.results] == [10]
    assert result.results[0]["ok"] is True
    assert [call.kwargs["step_index"] for call in emit_events.await_args_list] == [10, 10]


@pytest.mark.asyncio
async def test_execute_device_action_batch_returns_partial_successes_when_cancelled_during_batch():
    from runtime.transports.u2_jsonrpc import U2BatchError
    from temporal.activities import DeviceActivities

    activities = DeviceActivities()
    inp = DeviceActionBatchInput(
        device_serial="SN001",
        steps=[
            {"type": "tap_position", "pos": "middle_center"},
            {"type": "tap_position", "pos": "bottom_center"},
        ],
        step_indices=[10, 11],
        execution_id="exec-1",
        scenario_config={"primitive_touch_batch_size": 2},
    )

    def _cancel_after_first_action(*_args, **kwargs):
        kwargs["cancel_event"].set()
        raise U2BatchError(
            "cancelled",
            stopped_at=1,
            results=[{"op": "click", "ok": True}],
            cancelled=True,
        )

    mock_device = MagicMock()
    mock_device.model = "test"
    mock_device.screen_width = 1000
    mock_device.screen_height = 2000
    mock_device.ensure_u2_healthy = MagicMock()
    mock_device._batch_enabled = MagicMock(return_value=True)
    mock_device.u2_batch = MagicMock(side_effect=_cancel_after_first_action)
    emit_events = AsyncMock()

    with (
        patch("temporal.activities._get_device", return_value=mock_device),
        patch("temporal.activities._validate_serial"),
        patch("temporal.activities._emit_step_events_for_activity", emit_events),
        patch("temporal.activities.activity") as mock_activity,
        patch(
            "services.execution_pause_flags.is_execution_cancelled_async",
            AsyncMock(return_value=False),
        ),
        patch(
            "services.execution_pause_flags.is_execution_paused_async",
            AsyncMock(return_value=False),
        ),
    ):
        mock_activity.heartbeat = MagicMock()
        mock_activity.is_cancelled = MagicMock(return_value=False)
        result = await activities.execute_device_action_batch(inp)

    assert result.cancelled_mid_batch is True
    assert result.paused_mid_batch is False
    assert result.first_failure_index == -1
    assert [item["index"] for item in result.results] == [10]
    assert [call.kwargs["step_index"] for call in emit_events.await_args_list] == [10, 10]


@pytest.mark.asyncio
async def test_execute_device_action_batch_emits_finished_event_when_cancelled_after_step():
    import temporal.activities as activities

    class FakeDevice:
        serial = "SN001"
        model = "test"

        def ensure_u2_healthy(self, ping_timeout=2.0):
            return None

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    def fake_run_scenario_task(_device, _scenario, **_kwargs):
        return {
            "success": False,
            "step_results": [
                {
                    "index": 0,
                    "type": "scroll_down",
                    "ok": False,
                    "message": "scroll_down: cancelled by user",
                }
            ],
        }

    inp = DeviceActionBatchInput(
        device_serial="SN001",
        steps=[{"type": "scroll_down"}],
        step_indices=[7],
        execution_id="exec-1",
    )
    emit_events = AsyncMock()

    with (
        patch.object(activities, "_get_device", return_value=FakeDevice()),
        patch.object(activities, "_validate_serial"),
        patch.object(activities, "_prepare_activity_step", side_effect=lambda s: s),
        patch.object(activities, "_build_activity_mini_scenario", return_value={"steps": inp.steps}),
        patch.object(activities, "_emit_step_events_for_activity", emit_events),
        patch.object(activities, "_to_thread_with_heartbeat", side_effect=fake_to_thread),
        patch("tasks.scenario_task.run_scenario_task", side_effect=fake_run_scenario_task),
        patch.object(activities, "activity") as mock_activity,
        patch.object(activities, "_ExecutionFlagProbe") as probe_cls,
    ):
        mock_activity.heartbeat = MagicMock()
        mock_activity.is_cancelled = MagicMock(return_value=False)
        probe_cls.return_value.cancelled = AsyncMock(side_effect=[False, True])
        probe_cls.return_value.paused = AsyncMock(return_value=False)
        result = await activities.DeviceActivities().execute_device_action_batch(inp)

    assert result.cancelled_mid_batch is True
    assert [item["index"] for item in result.results] == [7]
    assert result.results[0]["ok"] is False
    assert result.results[0]["message"] == "scroll_down: cancelled by user"
    assert [call.kwargs["phase"] for call in emit_events.await_args_list] == ["started", "finished"]
    finished_result = emit_events.await_args_list[1].kwargs["step_result"]
    assert finished_result["ok"] is False
    assert finished_result["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_emit_step_events_for_activity_uses_cached_event_context():
    from contextlib import contextmanager

    import temporal.activities as activities

    class FakeDb:
        async def commit(self):
            return None

    class FakeSession:
        async def __aenter__(self):
            return FakeDb()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    @contextmanager
    def fake_tenant_context(_org_id):
        yield

    inp = DeviceActionBatchInput(
        device_serial="SN001",
        steps=[],
        step_indices=[],
        execution_id="exec-1",
        campaign_id="camp-input",
    )
    resolve_context = AsyncMock(side_effect=AssertionError("context should be cached"))
    emit_started = AsyncMock()

    inline_publish = AsyncMock()
    with (
        patch("db.database.activity_session", return_value=FakeSession()),
        patch("services.execution.event_publisher.resolve_execution_event_context", resolve_context),
        patch("services.execution.activity_events.emit_step_started", emit_started),
        patch("services.execution.event_publisher.process_outbox_batch", inline_publish),
        patch("tenancy.context.tenant_context", fake_tenant_context),
    ):
        await activities._emit_step_events_for_activity(
            inp,
            step={"type": "tap_position"},
            step_index=7,
            phase="started",
            event_context=("org-1", "camp-cached"),
        )

    resolve_context.assert_not_awaited()
    emit_started.assert_awaited_once()
    inline_publish.assert_not_awaited()
    assert emit_started.await_args.kwargs["org_id"] == "org-1"
    assert emit_started.await_args.kwargs["campaign_id"] == "camp-cached"


@pytest.mark.asyncio
async def test_execute_device_action_batch_propagates_runtime_context():
    import temporal.activities as activities

    captured_contexts: list[dict[str, Any]] = []

    class FakeDevice:
        serial = "SN001"
        model = "test"

        def ensure_u2_healthy(self, ping_timeout=2.0):
            return None

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    inp = DeviceActionBatchInput(
        device_serial="SN001",
        steps=[{"type": "fb_tap_comment_button", "pre_scroll": True}],
        step_indices=[2],
        context={
            "_active_comment_parent_source": "post_detail",
            "_active_comment_anchor_verified": True,
            "_active_comment_parent_hash": "post-hash-1",
        },
    )

    def fake_run_scenario_task(_device, _scenario, context=None, **_kwargs):
        captured_contexts.append(dict(context or {}))
        ctx = dict(context or {})
        ctx["_fb_comment_filter_applied"] = "all_comments"
        return {
            "success": True,
            "step_results": [
                {
                    "index": 0,
                    "type": "fb_tap_comment_button",
                    "ok": True,
                    "message": "tap ok",
                    "tapped": True,
                }
            ],
            "context": ctx,
        }

    with (
        patch.object(activities, "_get_device", return_value=FakeDevice()),
        patch.object(activities, "_validate_serial"),
        patch.object(activities, "_prepare_activity_step", side_effect=lambda s: s),
        patch.object(activities, "_build_activity_mini_scenario", return_value={"steps": inp.steps}),
        patch.object(activities, "_emit_step_events_for_activity", AsyncMock()),
        patch.object(activities, "_to_thread_with_heartbeat", side_effect=fake_to_thread),
        patch("tasks.scenario_task.run_scenario_task", side_effect=fake_run_scenario_task),
        patch.object(activities, "activity") as mock_activity,
        patch.object(activities, "_ExecutionFlagProbe") as probe_cls,
    ):
        mock_activity.heartbeat = MagicMock()
        mock_activity.is_cancelled = MagicMock(return_value=False)
        probe_cls.return_value.cancelled = AsyncMock(return_value=False)
        probe_cls.return_value.paused = AsyncMock(return_value=False)
        result = await activities.DeviceActivities().execute_device_action_batch(inp)

    assert captured_contexts
    assert captured_contexts[0]["_active_comment_parent_source"] == "post_detail"
    assert captured_contexts[0]["_active_comment_parent_hash"] == "post-hash-1"
    assert result.context["_fb_comment_filter_applied"] == "all_comments"
