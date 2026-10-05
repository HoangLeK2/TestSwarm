"""A pause that lands inside a touch batch must suspend, not fail the run.

`u2_batch` reports a mid-flight cancellation two different ways, and only one of
them was handled:

  * it raises U2BatchError(cancelled=True) — covered by
    test_temporal_batch_cancel.py, handled by the `except BaseException` arm;
  * it *returns* a result list whose entries are {"ok": False,
    "error": "cancelled"} — what the relay transport actually produces, and
    what _to_thread_with_heartbeat hands back rather than raising.

On the returning path those entries were mapped straight into step outcomes.
The first one set first_failure_index and broke out of the batch loop, so the
paused_mid_batch check sitting a few lines below was unreachable in the one
situation it exists for. The scenario failed, the execution went to the DLQ, and
Resume had nothing left to resume: pressing pause ended the run.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from temporal.shared import DeviceActionBatchInput


def _batch_input() -> DeviceActionBatchInput:
    return DeviceActionBatchInput(
        device_serial="SN001",
        steps=[
            {"type": "tap_position", "pos": "middle_center"},
            {"type": "tap_position", "pos": "bottom_center"},
        ],
        step_indices=[10, 11],
        execution_id="exec-1",
        scenario_config={"primitive_touch_batch_size": 2},
    )


def _mock_device(side_effect) -> MagicMock:
    device = MagicMock()
    device.model = "test"
    device.screen_width = 1000
    device.screen_height = 2000
    device.ensure_u2_healthy = MagicMock()
    device._batch_enabled = MagicMock(return_value=True)
    device.u2_batch = MagicMock(side_effect=side_effect)
    return device


async def _run(*, cancelled: bool, paused: bool):
    from temporal.activities import DeviceActivities

    def _stop_mid_batch(*_args, **kwargs):
        # The transport returns rather than raises: cancel_event was tripped
        # while the actions were in flight, so each one comes back cancelled.
        kwargs["cancel_event"].set()
        return [
            {"ok": False, "error": "cancelled"},
            {"ok": False, "error": "cancelled"},
        ]

    activities = DeviceActivities()
    emit_events = AsyncMock()
    with (
        patch("temporal.activities._get_device", return_value=_mock_device(_stop_mid_batch)),
        patch("temporal.activities._validate_serial"),
        patch("temporal.activities._heartbeat_campaign_device_claim", AsyncMock()),
        patch("temporal.activities._emit_step_events_for_activity", emit_events),
        patch("temporal.activities.activity") as mock_activity,
        patch(
            "services.execution_pause_flags.is_execution_cancelled_async",
            AsyncMock(return_value=cancelled),
        ),
        patch(
            "services.execution_pause_flags.is_execution_cancelled_local",
            MagicMock(return_value=False),
        ),
        patch(
            "services.execution_pause_flags.is_execution_paused_async",
            AsyncMock(return_value=paused),
        ),
        patch(
            "services.execution_pause_flags.is_execution_paused_local",
            MagicMock(return_value=False),
        ),
    ):
        mock_activity.heartbeat = MagicMock()
        mock_activity.is_cancelled = MagicMock(return_value=False)
        return await activities.execute_device_action_batch(_batch_input())


@pytest.mark.asyncio
async def test_pause_inside_a_batch_suspends_instead_of_failing():
    result = await _run(cancelled=False, paused=True)

    assert result.paused_mid_batch is True
    assert result.cancelled_mid_batch is False
    # -1 is what keeps the scenario alive: any real index is a failed step,
    # which fails the scenario and drops the run into the DLQ.
    assert result.first_failure_index == -1


@pytest.mark.asyncio
async def test_cancel_inside_a_batch_is_not_mistaken_for_a_pause():
    """Cancel must win over pause; a cancelled run must not be retried."""
    result = await _run(cancelled=True, paused=True)

    assert result.paused_mid_batch is False
    assert result.cancelled_mid_batch is True


@pytest.mark.asyncio
async def test_genuine_action_failures_still_fail_the_batch():
    """Only a pause is a suspend — ordinary errors must stay failures."""
    from temporal.activities import DeviceActivities

    def _fail_without_cancel(*_args, **_kwargs):
        return [
            {"ok": False, "error": "element not found"},
            {"ok": False, "error": "element not found"},
        ]

    activities = DeviceActivities()
    with (
        patch(
            "temporal.activities._get_device",
            return_value=_mock_device(_fail_without_cancel),
        ),
        patch("temporal.activities._validate_serial"),
        patch("temporal.activities._heartbeat_campaign_device_claim", AsyncMock()),
        patch("temporal.activities._emit_step_events_for_activity", AsyncMock()),
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
        result = await activities.execute_device_action_batch(_batch_input())

    assert result.paused_mid_batch is False
    assert result.first_failure_index == 0
