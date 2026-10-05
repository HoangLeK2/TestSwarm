from __future__ import annotations

from datetime import datetime, timezone

import pytest

from db.models.ai_device_lab_delivery import FarmJob
from services.ai_device_lab.delivery import (
    AcceptFarmEvent,
    CreateFarmJob,
    DeliveryInvariantError,
    accept_farm_event,
    create_farm_job,
)
from services.operation_policy import OperationPolicy
from tenancy.context import tenant_context
from tests.tenancy_test_support import ORG_A, seed_two_org_fixture


def _policy() -> OperationPolicy:
    return OperationPolicy(
        version="policy-v1",
        app_package="com.example.app",
        allowed_actions=frozenset({"navigation.open"}),
        allowed_targets=frozenset({"com.example.app"}),
    )


@pytest.mark.asyncio
async def test_farm_job_replay_requires_the_same_delivery_contract(
    tenancy_session_factory,
) -> None:
    await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 5, tzinfo=timezone.utc)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            job = FarmJob(
                id="job-idempotency-1",
                org_id=ORG_A,
                run_attempt_id="attempt-1",
                reservation_id="reservation-1",
                scenario_approval_id="approval-1",
                schema_version="adl-farm-job-v1",
                idempotency_key="job-contract-key",
                device_id="device-1",
                deadline_at=now,
                payload={
                    "policy_version": "policy-v1",
                    "package_name": "com.example.app",
                    "secret_capability_ref": None,
                },
            )
            db.add(job)
            await db.flush()
            command = CreateFarmJob(
                org_id=ORG_A,
                run_attempt_id="attempt-1",
                reservation_id="reservation-1",
                approval_id="approval-1",
                idempotency_key="job-contract-key",
                deadline_at=now,
                active_policy=_policy(),
            )
            repeated = await create_farm_job(db, command)
            with pytest.raises(DeliveryInvariantError, match="farm job idempotency key"):
                await create_farm_job(
                    db,
                    CreateFarmJob(
                        org_id=ORG_A,
                        run_attempt_id="attempt-1",
                        reservation_id="reservation-different",
                        approval_id="approval-1",
                        idempotency_key="job-contract-key",
                        deadline_at=now,
                        active_policy=_policy(),
                    ),
                )

    assert repeated.id == job.id


@pytest.mark.asyncio
async def test_late_pass_cannot_override_assertion_failure_and_duplicate_is_deduped(
    tenancy_session_factory,
) -> None:
    await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 5, tzinfo=timezone.utc)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            job = FarmJob(
                id="job-reducer-1",
                org_id=ORG_A,
                run_attempt_id="attempt-1",
                reservation_id="reservation-1",
                scenario_approval_id="approval-1",
                schema_version="adl-farm-job-v1",
                idempotency_key="job-key-1",
                device_id="device-1",
                deadline_at=now,
                payload={"schema_version": "adl-farm-job-v1", "execution_id": "execution-1"},
            )
            db.add(job)
            await db.flush()
            failed_command = AcceptFarmEvent(
                org_id=ORG_A,
                job_id=job.id,
                schema_version="adl-farm-event-v1",
                execution_id="execution-1",
                source="relay-1",
                event_id="event-fail",
                event_type="assertion",
                occurred_at=now,
                assertion_passed=False,
                reason_code="HOME_MISSING",
            )
            failed, _ = await accept_farm_event(db, failed_command)
            duplicate, _ = await accept_farm_event(db, failed_command)
            with pytest.raises(DeliveryInvariantError, match="farm event id"):
                await accept_farm_event(
                    db,
                    AcceptFarmEvent(
                        org_id=ORG_A,
                        job_id=job.id,
                        schema_version="adl-farm-event-v1",
                        execution_id="execution-1",
                        source="relay-1",
                        event_id="event-fail",
                        event_type="completed",
                        occurred_at=now,
                        assertion_passed=True,
                    ),
                )
            _, reduced = await accept_farm_event(
                db,
                AcceptFarmEvent(
                    org_id=ORG_A,
                    job_id=job.id,
                    schema_version="adl-farm-event-v1",
                    execution_id="execution-1",
                    source="relay-1",
                    event_id="event-late-pass",
                    event_type="completed",
                    occurred_at=now,
                    assertion_passed=True,
                ),
            )

    assert duplicate.id == failed.id
    assert reduced.status == "failed"
    assert reduced.verdict == "fail"
    assert reduced.terminal_reason == "HOME_MISSING"
