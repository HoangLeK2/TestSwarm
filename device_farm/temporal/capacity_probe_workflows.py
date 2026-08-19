"""Capacity / DB-pool probe workflows for Temporal load tests."""
from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn(name="CapacityProbeWorkflow")
class CapacityProbeWorkflow:
    @workflow.run
    async def run(self, arg: int | dict = 50) -> dict:
        """Occupy one activity slot for delay_ms.

        Accepts a bare int (delay) or {"delay_ms", "task_queue"}. The dict form
        exists so a load test can send the activity to the control queue while
        the workflow itself still runs on the device queue — the same shape the
        real control activities use, and the only way to measure that queue
        without registering workflows on the control workers.
        """
        if isinstance(arg, dict):
            delay_ms = int(arg.get("delay_ms", 50))
            task_queue = arg.get("task_queue") or None
        else:
            delay_ms = int(arg)
            task_queue = None
        return await workflow.execute_activity(
            "capacity_probe",
            delay_ms,
            task_queue=task_queue,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )


@workflow.defn(name="DbHoldProbeWorkflow")
class DbHoldProbeWorkflow:
    """Production-like DB pool stress: hold activity_session for hold_ms."""

    @workflow.run
    async def run(self, hold_ms: int = 500) -> dict:
        return await workflow.execute_activity(
            "db_hold_probe",
            hold_ms,
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
