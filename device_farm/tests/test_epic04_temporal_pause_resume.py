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


def test_temporal_error_policy_defaults_run_scenario_to_stop():
    from temporal.workflows import _error_policy

    assert _error_policy({"type": "run_scenario"}, {}) == "stop"
    assert _error_policy({"type": "tap"}, {}) == "stop"


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        ({"type": "run_scenario", "on_error": "stop"}, "stop"),
        ({"type": "run_scenario", "on_error": "pause"}, "pause"),
        ({"type": "run_scenario", "ignore_error": True}, "continue"),
        ({"type": "run_scenario", "error_policy": "stop"}, "stop"),
        ({"type": "run_scenario", "error_policy": "ignore"}, "continue"),
        ({"type": "run_scenario", "error_policy": "continue"}, "continue"),
    ],
)
def test_temporal_error_policy_honors_parent_step_policy(step, expected):
    from temporal.workflows import _error_policy

    assert _error_policy(step, {}) == expected


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
async def test_batch_activity_exception_returns_failed_step_instead_of_child_workflow_error():
    try:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker as TemporalWorker
        from temporalio import activity as temporal_activity
    except ImportError:
        pytest.skip("temporalio not installed")

    from temporal.workflows import ScenarioStepsWorkflow

    @temporal_activity.defn(name="execute_device_action_batch")
    async def mock_batch(_inp):
        raise RuntimeError("adb relay timed out")

    steps_inp = StepsInput(
        device_serial="V2352A",
        steps=[{"type": "wait", "seconds": 0}],
        scenario_config={"batch_size": 1},
        execution_id="exec-batch-error-test",
    )

    try:
        env = await WorkflowEnvironment.start_time_skipping()
    except RuntimeError as exc:
        if "Operation not permitted" in str(exc):
            pytest.skip("Temporal test server blocked by sandbox")
        raise

    async with env:
        async with TemporalWorker(
            env.client,
            task_queue=TASK_QUEUE_NAME,
            workflows=[ScenarioStepsWorkflow],
            activities=[mock_batch],
        ):
            result = await env.client.execute_workflow(
                ScenarioStepsWorkflow.run,
                steps_inp,
                id="test-batch-activity-exception-step-result",
                task_queue=TASK_QUEUE_NAME,
            )

    assert result.success is False
    assert result.step_results
    assert result.step_results[0]["index"] == 0
    assert result.step_results[0]["type"] == "wait"
    assert result.step_results[0]["ok"] is False
    assert "adb relay timed out" in result.step_results[0]["message"]
    assert "Child Workflow execution failed" not in result.failed_message
    assert "Workflow error" not in result.failed_message


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
async def test_resume_replays_unfinished_steps_after_partial_paused_batch(pause_coord):
    """Pause after a partial batch result must not drop unfinished pending steps."""
    try:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker as TemporalWorker
        from temporalio import activity as temporal_activity
    except ImportError:
        pytest.skip("temporalio not installed")

    from temporal.workflows import ScenarioStepsWorkflow

    coord = pause_coord
    first_batch_release = asyncio.Event()
    seen_batches: list[list[int]] = []

    @temporal_activity.defn(name="execute_device_action_batch")
    async def mock_batch(inp):
        indices = _batch_indices(inp)
        seen_batches.append(indices)
        if len(seen_batches) == 1:
            coord["step0_started"].set()
            await first_batch_release.wait()
            coord["executed_indices"].append(indices[0])
            return DeviceActionBatchResult(
                results=[
                    {"index": indices[0], "type": "wait", "ok": True, "message": "ok"}
                ],
                first_failure_index=-1,
                paused_mid_batch=True,
            )
        coord["executed_indices"].extend(indices)
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
        scenario_config={"batch_size": 3, "on_error": "continue"},
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
                id="test-partial-paused-batch-resume",
                task_queue=TASK_QUEUE_NAME,
            )

            await asyncio.wait_for(coord["step0_started"].wait(), timeout=5.0)
            await handle.signal(ScenarioStepsWorkflow.pause)
            first_batch_release.set()
            await _poll_until(lambda: coord["executed_indices"] == [0])
            await asyncio.sleep(0.15)
            assert seen_batches == [[0, 1, 2]]

            await handle.signal(ScenarioStepsWorkflow.resume)
            result = await asyncio.wait_for(handle.result(), timeout=10.0)

    assert result.success is True
    assert seen_batches == [[0, 1, 2], [1, 2]]
    assert coord["executed_indices"] == [0, 1, 2]
    assert [r["index"] for r in result.step_results] == [0, 1, 2]


@pytest.mark.asyncio
async def test_partial_paused_batch_waits_for_resume_without_pause_signal(pause_coord):
    """A paused batch result is authoritative even if the pause signal races behind it."""
    try:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker as TemporalWorker
        from temporalio import activity as temporal_activity
    except ImportError:
        pytest.skip("temporalio not installed")

    from temporal.workflows import ScenarioStepsWorkflow

    coord = pause_coord
    first_batch_release = asyncio.Event()
    seen_batches: list[list[int]] = []

    @temporal_activity.defn(name="execute_device_action_batch")
    async def mock_batch(inp):
        indices = _batch_indices(inp)
        seen_batches.append(indices)
        if len(seen_batches) == 1:
            coord["step0_started"].set()
            await first_batch_release.wait()
            coord["executed_indices"].append(indices[0])
            return DeviceActionBatchResult(
                results=[
                    {"index": indices[0], "type": "wait", "ok": True, "message": "ok"}
                ],
                first_failure_index=-1,
                paused_mid_batch=True,
            )
        coord["executed_indices"].extend(indices)
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
        scenario_config={"batch_size": 3, "on_error": "continue"},
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
                id="test-partial-paused-batch-racy-signal",
                task_queue=TASK_QUEUE_NAME,
            )

            await asyncio.wait_for(coord["step0_started"].wait(), timeout=5.0)
            first_batch_release.set()
            await _poll_until(lambda: coord["executed_indices"][:1] == [0])
            await asyncio.sleep(0.15)
            assert seen_batches == [[0, 1, 2]]

            await handle.signal(ScenarioStepsWorkflow.resume)
            result = await asyncio.wait_for(handle.result(), timeout=10.0)

    assert result.success is True
    assert seen_batches == [[0, 1, 2], [1, 2]]
    assert coord["executed_indices"] == [0, 1, 2]
    assert [r["index"] for r in result.step_results] == [0, 1, 2]


@pytest.mark.asyncio
async def test_partial_paused_batch_does_not_hide_failed_result(pause_coord):
    """A failed partial result must win over pause and stop the workflow."""
    try:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker as TemporalWorker
        from temporalio import activity as temporal_activity
    except ImportError:
        pytest.skip("temporalio not installed")

    from temporal.workflows import ScenarioStepsWorkflow

    seen_batches: list[list[int]] = []

    @temporal_activity.defn(name="execute_device_action_batch")
    async def mock_batch(inp):
        indices = _batch_indices(inp)
        seen_batches.append(indices)
        return DeviceActionBatchResult(
            results=[
                {
                    "index": indices[0],
                    "type": "wait",
                    "ok": False,
                    "message": "touch failed",
                }
            ],
            first_failure_index=-1,
            paused_mid_batch=True,
        )

    steps_inp = StepsInput(
        device_serial="emulator-5554",
        steps=_wait_steps(3),
        depth=0,
        scenario_config={"batch_size": 3, "on_error": "stop"},
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
                id="test-partial-paused-batch-failure-wins",
                task_queue=TASK_QUEUE_NAME,
            )
            result = await asyncio.wait_for(handle.result(), timeout=10.0)

    assert result.success is False
    assert result.failed_message == "touch failed"
    assert seen_batches == [[0, 1, 2]]
    assert [r["index"] for r in result.step_results] == [0]
    assert result.step_results[0]["ok"] is False


@pytest.mark.asyncio
async def test_batch_failure_continue_replays_unfinished_batch_steps():
    """on_error=continue must continue with unexecuted steps from the failed batch."""
    try:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker as TemporalWorker
        from temporalio import activity as temporal_activity
    except ImportError:
        pytest.skip("temporalio not installed")

    from temporal.workflows import ScenarioStepsWorkflow

    seen_batches: list[list[int]] = []

    @temporal_activity.defn(name="execute_device_action_batch")
    async def mock_batch(inp):
        indices = _batch_indices(inp)
        seen_batches.append(indices)
        if len(seen_batches) == 1:
            return DeviceActionBatchResult(
                results=[
                    {
                        "index": indices[0],
                        "type": "wait",
                        "ok": False,
                        "message": "step failed",
                    }
                ],
                first_failure_index=0,
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
        steps=_wait_steps(3),
        depth=0,
        scenario_config={"batch_size": 3, "on_error": "continue"},
    )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with TemporalWorker(
            env.client,
            task_queue=TASK_QUEUE_NAME,
            workflows=[ScenarioStepsWorkflow],
            activities=[mock_batch],
        ):
            result = await env.client.execute_workflow(
                ScenarioStepsWorkflow.run,
                steps_inp,
                id="test-batch-failure-continue-replays-rest",
                task_queue=TASK_QUEUE_NAME,
            )

    assert result.success is True
    assert seen_batches == [[0, 1, 2], [1, 2]]
    assert [r["index"] for r in result.step_results] == [0, 1, 2]
    assert [r["ok"] for r in result.step_results] == [False, True, True]


@pytest.mark.asyncio
async def test_batch_failure_continue_drains_requeued_steps_before_control_flow():
    """A control-flow boundary must not run before requeued batch remainder."""
    try:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker as TemporalWorker
        from temporalio import activity as temporal_activity
    except ImportError:
        pytest.skip("temporalio not installed")

    from temporal.workflows import ScenarioStepsWorkflow

    seen_batches: list[list[int]] = []

    @temporal_activity.defn(name="execute_device_action_batch")
    async def mock_batch(inp):
        indices = _batch_indices(inp)
        seen_batches.append(indices)
        if len(seen_batches) == 1:
            return DeviceActionBatchResult(
                results=[
                    {
                        "index": indices[0],
                        "type": "wait",
                        "ok": False,
                        "message": "step failed",
                    }
                ],
                first_failure_index=0,
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
        steps=[
            *_wait_steps(3),
            {"type": "set_variable", "name": "marker", "value": "done"},
        ],
        depth=0,
        scenario_config={"batch_size": 10, "on_error": "continue"},
    )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with TemporalWorker(
            env.client,
            task_queue=TASK_QUEUE_NAME,
            workflows=[ScenarioStepsWorkflow],
            activities=[mock_batch],
        ):
            result = await env.client.execute_workflow(
                ScenarioStepsWorkflow.run,
                steps_inp,
                id="test-batch-failure-continue-drains-before-control",
                task_queue=TASK_QUEUE_NAME,
            )

    assert result.success is True
    assert seen_batches == [[0, 1, 2], [1, 2]]
    assert [r["index"] for r in result.step_results] == [0, 1, 2, 3]
    assert [r["type"] for r in result.step_results] == [
        "wait",
        "wait",
        "wait",
        "set_variable",
    ]
    assert result.runtime_vars["marker"] == "done"


@pytest.mark.asyncio
async def test_partial_paused_batch_cancel_stops_without_executing_requeued_steps(pause_coord):
    """Cancel while paused must not execute requeued steps."""
    try:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker as TemporalWorker
        from temporalio import activity as temporal_activity
    except ImportError:
        pytest.skip("temporalio not installed")

    from temporal.workflows import ScenarioStepsWorkflow

    coord = pause_coord
    first_batch_release = asyncio.Event()
    cancel_requested = asyncio.Event()
    seen_batches: list[list[int]] = []

    @temporal_activity.defn(name="execute_device_action_batch")
    async def mock_batch(inp):
        indices = _batch_indices(inp)
        seen_batches.append(indices)
        if cancel_requested.is_set():
            return DeviceActionBatchResult(
                results=[],
                first_failure_index=-1,
                cancelled_mid_batch=True,
            )
        coord["step0_started"].set()
        await first_batch_release.wait()
        coord["executed_indices"].append(indices[0])
        return DeviceActionBatchResult(
            results=[
                {"index": indices[0], "type": "wait", "ok": True, "message": "ok"}
            ],
            first_failure_index=-1,
            paused_mid_batch=True,
        )

    steps_inp = StepsInput(
        device_serial="emulator-5554",
        steps=_wait_steps(3),
        depth=0,
        scenario_config={"batch_size": 3, "on_error": "continue"},
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
                id="test-partial-paused-batch-cancel-no-replay",
                task_queue=TASK_QUEUE_NAME,
            )

            await asyncio.wait_for(coord["step0_started"].wait(), timeout=5.0)
            first_batch_release.set()
            await _poll_until(lambda: coord["executed_indices"] == [0])

            async def workflow_is_paused():
                state = await handle.query(ScenarioStepsWorkflow.get_control_state)
                return state["paused"] is True

            await _poll_until(workflow_is_paused)
            assert seen_batches == [[0, 1, 2]]
            cancel_requested.set()
            await handle.signal("cancel_scenario")
            result = await asyncio.wait_for(handle.result(), timeout=10.0)

    assert result.success is False
    assert result.failed_message == "Cancelled during execution"
    assert [r["index"] for r in result.step_results] == [0]
    assert coord["executed_indices"] == [0]


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


@pytest.mark.asyncio
async def test_scenario_workflow_treats_child_temporal_cancel_as_cancelled(pause_coord):
    """External child workflow cancel should not be finalized as a workflow error."""
    try:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker as TemporalWorker
        from temporalio import activity as temporal_activity
    except ImportError:
        pytest.skip("temporalio not installed")

    from temporal.workflows import ScenarioStepsWorkflow, ScenarioWorkflow

    coord = pause_coord
    finalize_payloads: list[dict] = []

    @temporal_activity.defn(name="execute_device_action_batch")
    async def mock_batch(inp):
        indices = _batch_indices(inp)
        coord["executed_indices"].extend(indices)
        coord["step0_started"].set()
        return DeviceActionBatchResult(
            results=[
                {"index": i, "type": "wait", "ok": True, "message": "ok"}
                for i in indices
            ],
            first_failure_index=-1,
            paused_mid_batch=True,
        )

    @temporal_activity.defn(name="finalize_campaign")
    async def mock_finalize(inp):
        finalize_payloads.append(dict(inp))
        return None

    scenario_inp = ScenarioInput(
        campaign_id="camp-child-cancel",
        device_serial="emulator-5554",
        steps=_wait_steps(1),
        scenario_config={"batch_size": 1, "on_error": "continue"},
        execution_id="exec-child-cancel-test",
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
                id="test-parent-child-temporal-cancel",
                task_queue=TASK_QUEUE_NAME,
            )

            await asyncio.wait_for(coord["step0_started"].wait(), timeout=5.0)
            child_handle = env.client.get_workflow_handle(
                "test-parent-child-temporal-cancel:steps"
            )

            async def child_is_paused():
                state = await child_handle.query(ScenarioStepsWorkflow.get_control_state)
                return state["paused"] is True

            await _poll_until(child_is_paused)
            await child_handle.cancel()
            result = await asyncio.wait_for(handle.result(), timeout=10.0)

    assert result.success is False
    assert result.failed_message == "Cancelled by Temporal"
    assert finalize_payloads
    assert finalize_payloads[-1]["failed_message"] == "Cancelled by Temporal"
    assert "Workflow error" not in finalize_payloads[-1]["failed_message"]
