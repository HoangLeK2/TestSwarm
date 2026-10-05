"""Workflow-level durable step retry (DF-T-04-011) — survives worker restart between attempts."""
from __future__ import annotations

import pytest

from services.execution.retry_policy import parse_step_retry_policy, step_for_single_attempt
from temporal.shared import StepsInput, StepResult, TASK_QUEUE_NAME


@pytest.mark.asyncio
async def test_workflow_retries_leaf_step_with_durable_sleep():
    try:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker as TemporalWorker
        from temporalio import activity as temporal_activity
    except ImportError:
        pytest.skip("temporalio not installed")

    from temporal.workflows import ScenarioStepsWorkflow

    calls = {"n": 0}

    @temporal_activity.defn(name="execute_device_action")
    async def mock_execute_device_action(inp) -> StepResult:
        calls["n"] += 1
        step_index = getattr(inp, "step_index", inp.get("step_index", 0))
        step = getattr(inp, "step", inp.get("step", {}))
        if calls["n"] < 3:
            return StepResult(
                index=step_index,
                step_type=str(step.get("type") or "wait"),
                ok=False,
                message="timeout",
                details={"reason_code": "timeout"},
            )
        return StepResult(
            index=step_index,
            step_type=str(step.get("type") or "wait"),
            ok=True,
            message="ok",
        )

    steps_inp = StepsInput(
        device_serial="emulator-5554",
        steps=[
            {
                "type": "wait",
                "seconds": 0,
                "retry": {
                    "max_attempts": 3,
                    "backoff_ms": 0,
                    "retryable_reasons": ["timeout"],
                },
            }
        ],
        depth=0,
    )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with TemporalWorker(
            env.client,
            task_queue=TASK_QUEUE_NAME,
            workflows=[ScenarioStepsWorkflow],
            activities=[mock_execute_device_action],
        ):
            result = await env.client.execute_workflow(
                ScenarioStepsWorkflow.run,
                steps_inp,
                id="test-durable-step-retry",
                task_queue=TASK_QUEUE_NAME,
            )

    assert result.success is True
    assert calls["n"] == 3
    assert len(result.step_results) == 1
    attempts = result.step_results[0].get("retry_attempts") or []
    assert len(attempts) == 3
    assert result.step_results[0]["ok"] is True


def test_step_for_single_attempt_strips_retry_block():
    step = {
        "type": "wait",
        "seconds": 1,
        "retry": {"max_attempts": 3, "retryable_reasons": ["timeout"]},
    }
    assert "retry" not in step_for_single_attempt(step)
    assert parse_step_retry_policy(step) is not None


@pytest.mark.asyncio
async def test_workflow_no_retry_when_step_omits_retry_config():
    try:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker as TemporalWorker
        from temporalio import activity as temporal_activity
    except ImportError:
        pytest.skip("temporalio not installed")

    from temporal.workflows import ScenarioStepsWorkflow

    batch_calls = {"n": 0}

    @temporal_activity.defn(name="execute_device_action_batch")
    async def mock_batch(inp):
        from temporal.shared import DeviceActionBatchResult

        batch_calls["n"] += 1
        indices = getattr(inp, "step_indices", inp.get("step_indices", []))
        idx = indices[0] if indices else 0
        return DeviceActionBatchResult(
            results=[
                {
                    "index": idx,
                    "type": "wait",
                    "ok": False,
                    "message": "timeout",
                    "reason_code": "timeout",
                }
            ],
            first_failure_index=0,
        )

    steps_inp = StepsInput(
        device_serial="emulator-5554",
        steps=[{"type": "wait", "seconds": 0}],
        depth=0,
        scenario_config={"on_error": "continue"},
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
                id="test-no-implicit-retry",
                task_queue=TASK_QUEUE_NAME,
            )

    assert batch_calls["n"] == 1
    assert result.success is True
