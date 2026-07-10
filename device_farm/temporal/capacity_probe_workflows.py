"""Capacity / DB-pool probe workflows for Temporal load tests."""
from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn(name="CapacityProbeWorkflow")
class CapacityProbeWorkflow:
    @workflow.run
    async def run(self, delay_ms: int = 50) -> dict:
        return await workflow.execute_activity(
            "capacity_probe",
            delay_ms,
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
