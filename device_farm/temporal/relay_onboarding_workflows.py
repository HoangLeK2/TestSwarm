from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy


_RUN_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(minutes=2),
    backoff_coefficient=2.0,
    maximum_attempts=3,
    non_retryable_error_types=["ValueError"],
)


@workflow.defn
class RelayOnboardingWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> None:
        prepared: dict[str, Any] = await workflow.execute_activity(
            "prepare_relay_onboarding_job",
            payload,
            start_to_close_timeout=timedelta(minutes=2),
            heartbeat_timeout=timedelta(seconds=30),
            retry_policy=_RUN_RETRY,
        )
        item_ids = [str(item_id) for item_id in prepared.get("item_ids", []) if str(item_id)]
        concurrency = max(1, int(prepared.get("concurrency", 1) or 1))

        for i in range(0, len(item_ids), concurrency):
            chunk = item_ids[i:i + concurrency]
            await asyncio.gather(*[
                workflow.execute_activity(
                    "run_relay_onboarding_item",
                    {**payload, "item_id": item_id},
                    start_to_close_timeout=timedelta(minutes=15),
                    heartbeat_timeout=timedelta(seconds=45),
                    retry_policy=_RUN_RETRY,
                )
                for item_id in chunk
            ])

        await workflow.execute_activity(
            "finish_relay_onboarding_job",
            str(payload.get("job_id") or ""),
            start_to_close_timeout=timedelta(minutes=2),
            heartbeat_timeout=timedelta(seconds=30),
            retry_policy=_RUN_RETRY,
        )
