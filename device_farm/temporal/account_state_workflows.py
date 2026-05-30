"""Temporal workflow: periodic cooldown expiry (DF-T-07-005)."""
from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from temporal.account_state_activities import AccountStateActivities


@workflow.defn(name="AccountCooldownTickWorkflow")
class AccountCooldownTickWorkflow:
    @workflow.run
    async def run(self) -> int:
        return await workflow.execute_activity(
            AccountStateActivities.process_expired_account_cooldowns,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
