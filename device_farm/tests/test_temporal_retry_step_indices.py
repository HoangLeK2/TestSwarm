"""Retrying a paused step must not restart the step numbering.

Same defect as the history-threshold continuation, on a different path:
continue_as_new used to slice the step list, so the retried run re-enumerated
from 0. execution_steps is keyed on (execution_id, step_index), so everything
after a retry overwrote the rows written before it.

Drives the real workflow through a pause -> retry_step -> continuation instead
of asserting on the arithmetic, which is what let the sibling bug ship green.
"""
from __future__ import annotations

import asyncio

import pytest

from temporal.shared import (
    CONTROL_TASK_QUEUE_NAME,
    DeviceActionBatchResult,
    StepsInput,
    TASK_QUEUE_NAME,
)
from temporal.workflows import ScenarioStepsWorkflow


async def _poll_until(pred, timeout: float = 5.0) -> None:
    waited = 0.0
    while waited < timeout:
        if pred():
            return
        await asyncio.sleep(0.05)
        waited += 0.05
    raise AssertionError(f"poll timeout after {timeout}s")


def _activities_with_telemetry(temporal_activity, *activities):
    @temporal_activity.defn(name="emit_execution_events_batch")
    async def mock_emit_events_batch(_inp):
        return None

    return [*activities, mock_emit_events_batch]


@pytest.mark.asyncio
async def test_retried_run_keeps_absolute_step_indices():
    try:
        from temporalio import activity as temporal_activity
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker as TemporalWorker
    except ImportError:  # pragma: no cover
        pytest.skip("temporalio not installed")

    seen_indices: list[int] = []
    fail_once = {"done": False}

    @temporal_activity.defn(name="execute_device_action_batch")
    async def mock_batch(inp):
        indices = list(
            (inp.get("step_indices") if isinstance(inp, dict) else inp.step_indices) or []
        )
        seen_indices.extend(indices)
        # Fail step 3 exactly once so the workflow pauses there and we can retry.
        if 3 in indices and not fail_once["done"]:
            fail_once["done"] = True
            return DeviceActionBatchResult(
                results=[
                    {"index": i, "type": "wait", "ok": i != 3, "message": "boom"}
                    for i in indices
                ],
                first_failure_index=indices.index(3),
            )
        return DeviceActionBatchResult(
            results=[
                {"index": i, "type": "wait", "ok": True, "message": "ok"}
                for i in indices
            ],
            first_failure_index=-1,
        )

    steps_inp = StepsInput(
        device_serial="emulator-5554",
        # on_error=pause is what gives us a retry_step to send; the policy is
        # read per step (_error_policy), not from scenario_config.
        steps=[
            {"type": "wait", "seconds": 0, "on_error": "pause"} for _ in range(8)
        ],
        scenario_config={"batch_size": 1},
        execution_id="exec-retry",
    )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with TemporalWorker(
            env.client,
            task_queue=TASK_QUEUE_NAME,
            workflows=[ScenarioStepsWorkflow],
            activities=_activities_with_telemetry(temporal_activity, mock_batch),
        ), TemporalWorker(
            env.client,
            task_queue=CONTROL_TASK_QUEUE_NAME,
            activities=_activities_with_telemetry(temporal_activity),
        ):
            handle = await env.client.start_workflow(
                ScenarioStepsWorkflow.run,
                steps_inp,
                id="test-retry-absolute-indices",
                task_queue=TASK_QUEUE_NAME,
            )
            await _poll_until(lambda: fail_once["done"])
            await handle.signal("retry_step")
            await handle.result()

    assert 3 in seen_indices, "step 3 never ran"
    after_retry = [i for i in seen_indices[seen_indices.index(3) + 1:]]
    assert after_retry, "nothing ran after the retry"

    # The proof: once the retried step is re-run, numbering continues upward.
    # Restarting at 0 is what silently overwrote the earlier execution_steps rows.
    assert min(after_retry) >= 3, (
        f"indices restarted after retry: {seen_indices}"
    )
    assert max(seen_indices) == 7
