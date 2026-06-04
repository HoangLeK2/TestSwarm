"""Temporal integration tests for pause/resume control (DF-T-04-016).

Uses temporalio.testing.WorkflowEnvironment (time-skipping test server).
"""
from __future__ import annotations

import asyncio
import time

import pytest

from temporal.shared import (
    DeviceActionBatchResult,
    ScenarioInput,
    StepsInput,
    TASK_QUEUE_NAME,
)


def _wait_steps(count: int) -> list[dict]:
    return [{"type": "wait", "seconds": 0} for _ in range(count)]


def _batch_indices(inp) -> list[int]:
    raw = getattr(inp, "step_indices", None)
    if raw is None and isinstance(inp, dict):
        raw = inp.get("step_indices")
    return list(raw or [])


async def _poll_until(condition, *, timeout: float = 5.0, interval: float = 0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = condition()
        if asyncio.iscoroutine(result):
            result = await result
        if result:
            return
        await asyncio.sleep(interval)
    raise AssertionError(f"poll timeout after {timeout}s")


@pytest.fixture
def pause_coord():
    """Mutable coordination state reset per test."""
    return {
        "executed_indices": [],
        "step0_started": asyncio.Event(),
        "step0_release": asyncio.Event(),
        "step1_running": asyncio.Event(),
        "step1_finish_allowed": asyncio.Event(),
    }


@pytest.mark.asyncio
async def test_pause_finishes_atomic_step_before_blocking_next(pause_coord):
    """Pause during step 0: step 0 completes; step 1 does not start until resume."""
    try:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker as TemporalWorker
        from temporalio import activity as temporal_activity
    except ImportError:
        pytest.skip("temporalio not installed")

    from temporal.workflows import ScenarioStepsWorkflow

    coord = pause_coord

    @temporal_activity.defn(name="execute_device_action_batch")
    async def mock_batch(inp):
        for idx in _batch_indices(inp):
            coord["executed_indices"].append(idx)
            if idx == 0:
                coord["step0_started"].set()
                await coord["step0_release"].wait()
        indices = _batch_indices(inp)
        return DeviceActionBatchResult(
            results=[
                {"index": i, "type": "wait", "ok": True, "message": "ok"}
                for i in indices
            ],
            first_failure_index=-1,
        )

    steps_inp = StepsInput(
        device_serial="emulator-5554",
        steps=_wait_steps(3),
        depth=0,
        scenario_config={"batch_size": 1, "on_error": "continue"},
    )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with TemporalWorker(
            env.client,
            task_queue=TASK_QUEUE_NAME,
            workflows=[ScenarioStepsWorkflow],
            activities=[mock_batch],
        ):
            handle = await env.client.start_workflow(
                ScenarioStepsWorkflow.run,
                steps_inp,
                id="test-pause-atomic-step",
                task_queue=TASK_QUEUE_NAME,
            )

            await asyncio.wait_for(coord["step0_started"].wait(), timeout=5.0)
            await handle.signal(ScenarioStepsWorkflow.pause)
            coord["step0_release"].set()

            await _poll_until(
                lambda: len(coord["executed_indices"]) >= 1,
            )
            await asyncio.sleep(0.15)
            assert coord["executed_indices"] == [0]

            await handle.signal(ScenarioStepsWorkflow.resume)
            result = await asyncio.wait_for(handle.result(), timeout=10.0)

    assert result.success is True
    assert coord["executed_indices"] == [0, 1, 2]
    assert [r["index"] for r in result.step_results] == [0, 1, 2]


@pytest.mark.asyncio
async def test_resume_continues_from_checkpoint_without_rerunning_steps(pause_coord):
    """Pause after step 1 completes; resume runs steps 2-3 without re-running 0-1."""
    try:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker as TemporalWorker
        from temporalio import activity as temporal_activity
    except ImportError:
        pytest.skip("temporalio not installed")

    from temporal.workflows import ScenarioStepsWorkflow

    coord = pause_coord

    @temporal_activity.defn(name="execute_device_action_batch")
    async def mock_batch(inp):
        for idx in _batch_indices(inp):
            coord["executed_indices"].append(idx)
            if idx == 1:
                coord["step1_running"].set()
                await coord["step1_finish_allowed"].wait()
        indices = _batch_indices(inp)
        return DeviceActionBatchResult(
            results=[
                {"index": i, "type": "wait", "ok": True, "message": "ok"}
                for i in indices
            ],
            first_failure_index=-1,
        )

    steps_inp = StepsInput(
        device_serial="emulator-5554",
        steps=_wait_steps(4),
        depth=0,
        scenario_config={"batch_size": 1, "on_error": "continue"},
    )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with TemporalWorker(
            env.client,
            task_queue=TASK_QUEUE_NAME,
            workflows=[ScenarioStepsWorkflow],
            activities=[mock_batch],
        ):
            handle = await env.client.start_workflow(
                ScenarioStepsWorkflow.run,
                steps_inp,
                id="test-resume-checkpoint",
                task_queue=TASK_QUEUE_NAME,
            )

            await asyncio.wait_for(coord["step1_running"].wait(), timeout=5.0)
            await handle.signal(ScenarioStepsWorkflow.pause)
            coord["step1_finish_allowed"].set()

            await _poll_until(
                lambda: coord["executed_indices"] == [0, 1],
            )
            await asyncio.sleep(0.15)
            assert coord["executed_indices"] == [0, 1]

            await handle.signal(ScenarioStepsWorkflow.resume)
            result = await asyncio.wait_for(handle.result(), timeout=10.0)

    assert result.success is True
    assert coord["executed_indices"] == [0, 1, 2, 3]
    assert coord["executed_indices"].count(0) == 1
    assert coord["executed_indices"].count(1) == 1
    assert [r["index"] for r in result.step_results] == [0, 1, 2, 3]


@pytest.mark.asyncio
async def test_scenario_workflow_forwards_pause_and_resume_to_child(pause_coord):
    """Parent ScenarioWorkflow pause/resume signals reach the child steps workflow."""
    try:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker as TemporalWorker
        from temporalio import activity as temporal_activity
    except ImportError:
        pytest.skip("temporalio not installed")

    from temporal.workflows import ScenarioStepsWorkflow, ScenarioWorkflow

    coord = pause_coord

    @temporal_activity.defn(name="execute_device_action_batch")
    async def mock_batch(inp):
        for idx in _batch_indices(inp):
            coord["executed_indices"].append(idx)
            if idx == 0:
                coord["step0_started"].set()
                await coord["step0_release"].wait()
        indices = _batch_indices(inp)
        return DeviceActionBatchResult(
            results=[
                {"index": i, "type": "wait", "ok": True, "message": "ok"}
                for i in indices
            ],
            first_failure_index=-1,
        )

    @temporal_activity.defn(name="finalize_campaign")
    async def mock_finalize(_inp):
        return None

    scenario_inp = ScenarioInput(
        campaign_id="camp-pause",
        device_serial="emulator-5554",
        steps=_wait_steps(2),
        scenario_config={"batch_size": 1, "on_error": "continue"},
        execution_id="exec-pause-test",
    )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with TemporalWorker(
            env.client,
            task_queue=TASK_QUEUE_NAME,
            workflows=[ScenarioWorkflow, ScenarioStepsWorkflow],
            activities=[mock_batch, mock_finalize],
        ):
            handle = await env.client.start_workflow(
                ScenarioWorkflow.run,
                scenario_inp,
                id="test-parent-pause-forward",
                task_queue=TASK_QUEUE_NAME,
            )

            await asyncio.wait_for(coord["step0_started"].wait(), timeout=5.0)
            await handle.signal(ScenarioWorkflow.pause)
            coord["step0_release"].set()

            await _poll_until(
                lambda: len(coord["executed_indices"]) >= 1,
            )
            assert coord["executed_indices"] == [0]

            await handle.signal(ScenarioWorkflow.resume)
            result = await asyncio.wait_for(handle.result(), timeout=10.0)

    assert result.success is True
    assert coord["executed_indices"] == [0, 1]
