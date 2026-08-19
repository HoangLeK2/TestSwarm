"""Drive a real continue_as_new and watch what the checkpoint receives.

execution_steps carries UNIQUE (execution_id, step_index). If a continuation
re-enumerates its steps from 0, everything after the checkpoint collides with
the rows the checkpoint just wrote and the upsert overwrites them — the audit
trail the checkpoint exists to preserve is destroyed.

This runs the actual ScenarioStepsWorkflow through a continuation instead of
re-implementing its arithmetic in the test, which is how the bug slipped past
the first attempt at covering it.
"""
from __future__ import annotations

import pytest

from temporal.shared import DeviceActionBatchResult, StepsInput, TASK_QUEUE_NAME
from temporal.workflows import ScenarioStepsWorkflow


def _steps(n: int) -> list[dict]:
    return [{"type": "wait", "seconds": 0} for _ in range(n)]


@pytest.mark.asyncio
async def test_indices_stay_absolute_across_a_checkpointed_continuation():
    try:
        from temporalio import activity as temporal_activity
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import (
            UnsandboxedWorkflowRunner,
            Worker as TemporalWorker,
        )
    except ImportError:  # pragma: no cover
        pytest.skip("temporalio not installed")

    checkpointed: list[list[dict]] = []
    seen_batch_indices: list[int] = []

    @temporal_activity.defn(name="execute_device_action_batch")
    async def mock_batch(inp):
        indices = list(
            (inp.get("step_indices") if isinstance(inp, dict) else inp.step_indices) or []
        )
        seen_batch_indices.extend(indices)
        return DeviceActionBatchResult(
            results=[
                {"index": i, "type": "wait", "ok": True, "message": "ok"}
                for i in indices
            ],
            first_failure_index=-1,
        )

    @temporal_activity.defn(name="persist_step_checkpoint")
    async def mock_checkpoint(inp: dict) -> int:
        checkpointed.append(list(inp.get("step_results") or []))
        # Let exactly one continuation happen: with the threshold pinned at 1
        # the guard would fire on every pass and the run would never advance.
        ScenarioStepsWorkflow._HISTORY_CONTINUE_THRESHOLD = 10**9
        return len(inp.get("step_results") or [])

    steps_inp = StepsInput(
        device_serial="emulator-5554",
        steps=_steps(60),
        scenario_config={"batch_size": 1},
        execution_id="exec-continuation",
    )

    # The guard only looks every 25 steps; a threshold of 1 makes the very first
    # look trigger, so the run continues at step 25.
    original_threshold = ScenarioStepsWorkflow._HISTORY_CONTINUE_THRESHOLD
    ScenarioStepsWorkflow._HISTORY_CONTINUE_THRESHOLD = 1
    try:
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with TemporalWorker(
                env.client,
                task_queue=TASK_QUEUE_NAME,
                workflows=[ScenarioStepsWorkflow],
                activities=[mock_batch, mock_checkpoint],
                # Unsandboxed so the lowered threshold below actually reaches the
                # workflow: the sandbox re-imports the module, which is why
                # patching it from the host process has no effect.
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                await env.client.execute_workflow(
                    ScenarioStepsWorkflow.run,
                    steps_inp,
                    id="test-checkpoint-continuation",
                    task_queue=TASK_QUEUE_NAME,
                )
    finally:
        ScenarioStepsWorkflow._HISTORY_CONTINUE_THRESHOLD = original_threshold

    assert checkpointed, "the run never checkpointed — the guard did not fire"

    flushed = [int(r["index"]) for r in checkpointed[0]]
    assert flushed == list(range(len(flushed))), flushed

    # The proof: after the continuation the workflow must keep numbering where
    # it left off. Restarting at 0 is what silently overwrote the flushed rows.
    after = [i for i in seen_batch_indices if i >= len(flushed)]
    assert after, (
        "no steps ran after the checkpoint; "
        f"flushed={flushed[:3]}..{flushed[-1:]} seen={sorted(set(seen_batch_indices))[:40]}"
    )
    assert min(after) == len(flushed), (
        f"steps resumed at {min(after)} instead of {len(flushed)} — "
        "indices restarted and would overwrite the checkpointed rows"
    )

    # Every step index across the whole run is distinct, so no upsert collides.
    assert len(seen_batch_indices) == len(set(seen_batch_indices))
    assert max(seen_batch_indices) == 59
