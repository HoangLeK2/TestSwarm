"""
temporal/schedule_workflow.py — ScheduleRunWorkflow (DF-008).

Executed when a Temporal Schedule fires (or via run-now trigger).

Architecture:
- Workflow is deterministic: no I/O, no random calls, no direct DB access
- All side effects (DB reads/writes, dispatch) happen in activities
- random_delay applied via workflow.sleep() (durable, survives worker restart)

Security:
- schedule_id validated via activity (raises ValueError → non-retryable)
- No secrets stored in workflow state
"""
from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from temporal.schedule_shared import (
        ScheduleDispatchResult,
        ScheduleRunInput,
        ScheduleRunOutput,
    )


_DB_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_attempts=5,
    non_retryable_error_types=["ValueError"],
)

_DISPATCH_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(minutes=2),
    backoff_coefficient=2.0,
    maximum_attempts=3,
    non_retryable_error_types=["ValueError"],
)

_FINALIZE_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_attempts=10,
)

_SHORT = timedelta(seconds=30)
_MEDIUM = timedelta(seconds=120)
_LONG = timedelta(minutes=30)



@workflow.defn
class ScheduleRunWorkflow:
    """
    Executes one scheduled run: load config → create run record →
    optional random delay → dispatch → finalize.

    Triggered by Temporal Schedule (cron) or manual trigger (run-now).
    """

    @workflow.run
    async def run(self, inp: ScheduleRunInput) -> ScheduleRunOutput:
        schedule_id = inp.schedule_id

        schedule_config: dict = await workflow.execute_activity(
            "load_schedule",
            schedule_id,
            start_to_close_timeout=_SHORT,
            retry_policy=_DB_RETRY,
        )

        if not schedule_config.get("is_enabled", True):
            return ScheduleRunOutput(
                schedule_id=schedule_id,
                run_id="",
                status="skipped",
                error="Schedule is disabled",
            )

        run_id: str = await workflow.execute_activity(
            "create_run_record",
            schedule_id,
            start_to_close_timeout=_SHORT,
            retry_policy=_DB_RETRY,
        )

        delay_min = int(schedule_config.get("random_delay_min", 0))
        delay_max = int(schedule_config.get("random_delay_max", 0))
        if delay_max > 0 and delay_max >= delay_min:
            delay_seconds = workflow.random().randint(delay_min, delay_max)
            if delay_seconds > 0:
                await workflow.sleep(timedelta(seconds=delay_seconds))

        dispatch_result: ScheduleDispatchResult = await workflow.execute_activity(
            "dispatch_schedule",
            args=[schedule_config, run_id],
            start_to_close_timeout=_LONG,
            retry_policy=_DISPATCH_RETRY,
            heartbeat_timeout=timedelta(seconds=30),
        )

        await workflow.execute_activity(
            "finalize_schedule_run",
            args=[
                run_id,
                schedule_id,
                dispatch_result,
                schedule_config.get("cron_expression", ""),
                schedule_config.get("timezone", "Asia/Ho_Chi_Minh"),
            ],
            start_to_close_timeout=_MEDIUM,
            retry_policy=_FINALIZE_RETRY,
        )

        status = "failed" if dispatch_result.error else "completed"
        return ScheduleRunOutput(
            schedule_id=schedule_id,
            run_id=run_id,
            status=status,
            devices_dispatched=dispatch_result.devices_dispatched,
            error=dispatch_result.error,
        )
