from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from db.models.ai_device_lab_delivery import FarmJob, FarmJobOutbox
from services.ai_device_lab.delivery import (
    FarmDeliveryError,
    _acknowledge_farm_delivery,
    claim_farm_job_delivery_batch,
    run_farm_delivery_batch,
)
from tenancy.context import tenant_context
from tests.tenancy_test_support import ORG_A, ORG_B, seed_two_org_fixture


class RecordingSink:
    def __init__(self, *, failures: int = 0, delay: float = 0) -> None:
        self.failures = failures
        self.delay = delay
        self.calls: list[str] = []
        self.active = 0
        self.peak = 0

    async def deliver(self, payload: dict) -> None:
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            self.calls.append(payload["idempotency_key"])
            if self.failures:
                self.failures -= 1
                raise FarmDeliveryError("RELAY_UNAVAILABLE")
        finally:
            self.active -= 1


async def _seed_job(
    session_factory,
    *,
    org_id: str,
    suffix: str,
    now: datetime,
    schema_version: str = "adl-farm-job-v1",
    deadline_at: datetime | None = None,
) -> None:
    with tenant_context(org_id):
        async with session_factory() as db:
            job = FarmJob(
                id=f"job-{suffix}",
                org_id=org_id,
                run_attempt_id=f"attempt-{suffix}",
                reservation_id=f"reservation-{suffix}",
                scenario_approval_id=f"approval-{suffix}",
                schema_version=schema_version,
                idempotency_key=f"delivery-{suffix}",
                device_id=f"device-{suffix}",
                deadline_at=deadline_at or now + timedelta(minutes=5),
                payload={
                    "schema_version": schema_version,
                    "idempotency_key": f"delivery-{suffix}",
                    "secret_capability_ref": None,
                },
            )
            db.add(job)
            await db.flush()
            db.add(
                FarmJobOutbox(
                    id=f"outbox-{suffix}",
                    org_id=org_id,
                    job_id=job.id,
                    status="pending",
                    available_at=now,
                )
            )
            await db.commit()


@pytest.mark.asyncio
async def test_delivery_recovers_expired_lease(
    tenancy_session_factory,
) -> None:
    await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 5, tzinfo=UTC)
    await _seed_job(tenancy_session_factory, org_id=ORG_A, suffix="lease", now=now)

    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            first_claim = await claim_farm_job_delivery_batch(
                db, now=now, limit=1, lease_seconds=30
            )
            await db.commit()

    sink = RecordingSink()
    before_expiry = await run_farm_delivery_batch(
        tenancy_session_factory,
        sink=sink,
        now=now + timedelta(seconds=29),
        batch_size=10,
    )
    recovered = await run_farm_delivery_batch(
        tenancy_session_factory,
        sink=sink,
        now=now + timedelta(seconds=31),
        batch_size=10,
    )

    assert len(first_claim) == 1
    assert before_expiry.claimed == 0
    assert recovered.delivered == 1
    assert sink.calls == ["delivery-lease"]
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            row = await db.get(FarmJobOutbox, "outbox-lease")
            assert row is not None
            assert row.status == "delivered"
            assert row.lease_token is None
            assert row.delivered_at.replace(tzinfo=UTC) == now + timedelta(seconds=31)


@pytest.mark.asyncio
async def test_expired_worker_cannot_acknowledge_after_lease_is_reclaimed(
    tenancy_session_factory,
) -> None:
    await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 5, tzinfo=UTC)
    await _seed_job(tenancy_session_factory, org_id=ORG_A, suffix="fence", now=now)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            first = (
                await claim_farm_job_delivery_batch(
                    db, now=now, limit=1, lease_seconds=30
                )
            )[0]
            await db.commit()
        async with tenancy_session_factory() as db:
            second = (
                await claim_farm_job_delivery_batch(
                    db,
                    now=now + timedelta(seconds=31),
                    limit=1,
                    lease_seconds=30,
                )
            )[0]
            await db.commit()

    stale = await _acknowledge_farm_delivery(
        tenancy_session_factory,
        claim=first,
        outcome="delivered",
        error_code=None,
        now=now + timedelta(seconds=32),
        max_attempts=3,
    )
    current = await _acknowledge_farm_delivery(
        tenancy_session_factory,
        claim=second,
        outcome="delivered",
        error_code=None,
        now=now + timedelta(seconds=32),
        max_attempts=3,
    )

    assert stale == "stale"
    assert current == "delivered"


@pytest.mark.asyncio
async def test_delivery_retry_is_bounded_and_cross_tenant_batch_is_global(
    tenancy_session_factory,
) -> None:
    await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 5, tzinfo=UTC)
    await _seed_job(tenancy_session_factory, org_id=ORG_A, suffix="a", now=now)
    await _seed_job(tenancy_session_factory, org_id=ORG_B, suffix="b", now=now)
    sink = RecordingSink(failures=1)

    first = await run_farm_delivery_batch(
        tenancy_session_factory,
        sink=sink,
        now=now,
        batch_size=1,
        max_attempts=3,
    )
    too_early = await run_farm_delivery_batch(
        tenancy_session_factory,
        sink=sink,
        now=now + timedelta(milliseconds=999),
        batch_size=10,
        max_attempts=3,
    )
    recovered = await run_farm_delivery_batch(
        tenancy_session_factory,
        sink=sink,
        now=now + timedelta(seconds=1),
        batch_size=10,
        max_attempts=3,
    )

    assert first.claimed == 1
    assert first.retry_scheduled == 1
    assert too_early.delivered == 1
    assert recovered.delivered == 1
    assert len(sink.calls) == 3

    for org_id, suffix in ((ORG_A, "a"), (ORG_B, "b")):
        with tenant_context(org_id):
            async with tenancy_session_factory() as db:
                row = await db.get(FarmJobOutbox, f"outbox-{suffix}")
                assert row is not None
                assert row.status == "delivered"


@pytest.mark.asyncio
async def test_delivery_exhaustion_dead_letters_with_symbolic_error_only(
    tenancy_session_factory,
) -> None:
    await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 5, tzinfo=UTC)
    await _seed_job(tenancy_session_factory, org_id=ORG_A, suffix="exhaust", now=now)
    sink = RecordingSink(failures=1)

    result = await run_farm_delivery_batch(
        tenancy_session_factory,
        sink=sink,
        now=now,
        batch_size=1,
        max_attempts=1,
    )

    assert result.dead_lettered == 1
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            row = await db.get(FarmJobOutbox, "outbox-exhaust")
            job = await db.get(FarmJob, "job-exhaust")
            assert row is not None and job is not None
            assert row.last_error_code == "RELAY_UNAVAILABLE"
            assert row.status == "dead_lettered"
            assert job.status == "blocked"
            assert job.verdict == "inconclusive"


@pytest.mark.asyncio
async def test_uncertain_fallback_dispatch_dead_letters_without_retry(
    tenancy_session_factory,
) -> None:
    await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 5, tzinfo=UTC)
    await _seed_job(tenancy_session_factory, org_id=ORG_A, suffix="uncertain", now=now)
    sink = RecordingSink()

    async def uncertain(_payload: dict) -> None:
        raise FarmDeliveryError("FALLBACK_DISPATCH_UNCERTAIN")

    sink.deliver = uncertain
    result = await run_farm_delivery_batch(
        tenancy_session_factory,
        sink=sink,
        now=now,
        batch_size=1,
        max_attempts=8,
    )

    assert result.dead_lettered == 1
    assert result.retry_scheduled == 0
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            job = await db.get(FarmJob, "job-uncertain")
            outbox = await db.get(FarmJobOutbox, "outbox-uncertain")
            assert job is not None and outbox is not None
            assert job.status == "blocked"
            assert job.terminal_reason == "FALLBACK_DISPATCH_UNCERTAIN"
            assert outbox.delivery_attempts == 1


@pytest.mark.asyncio
async def test_delivery_rejects_unknown_schema_and_expired_job_without_sink_call(
    tenancy_session_factory,
) -> None:
    await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 5, tzinfo=UTC)
    await _seed_job(
        tenancy_session_factory,
        org_id=ORG_A,
        suffix="schema",
        now=now,
        schema_version="adl-farm-job-v999",
    )
    await _seed_job(
        tenancy_session_factory,
        org_id=ORG_A,
        suffix="deadline",
        now=now,
        deadline_at=now - timedelta(seconds=1),
    )
    sink = RecordingSink()

    result = await run_farm_delivery_batch(
        tenancy_session_factory,
        sink=sink,
        now=now,
        batch_size=10,
    )

    assert result.claimed == 2
    assert result.dead_lettered == 2
    assert sink.calls == []
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            rows = list(
                (
                    await db.execute(
                        select(FarmJobOutbox).order_by(FarmJobOutbox.id)
                    )
                ).scalars()
            )
            assert [row.status for row in rows] == ["dead_lettered", "dead_lettered"]
            assert {row.last_error_code for row in rows} == {
                "DEADLINE_EXCEEDED",
                "UNSUPPORTED_SCHEMA_VERSION",
            }


@pytest.mark.asyncio
async def test_confirmed_cancel_drains_outbox_without_future_delivery(
    tenancy_session_factory,
) -> None:
    await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 5, tzinfo=UTC)
    await _seed_job(tenancy_session_factory, org_id=ORG_A, suffix="cancel", now=now)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            job = await db.get(FarmJob, "job-cancel")
            assert job is not None
            job.status = "cancelled"
            job.verdict = "inconclusive"
            job.terminal_reason = "CANCELLED"
            await db.commit()
    sink = RecordingSink()

    result = await run_farm_delivery_batch(
        tenancy_session_factory,
        sink=sink,
        now=now,
        batch_size=10,
    )

    assert result.cancelled == 1
    assert sink.calls == []
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            row = await db.get(FarmJobOutbox, "outbox-cancel")
            assert row is not None
            assert row.status == "cancelled"
            assert row.lease_token is None


@pytest.mark.asyncio
async def test_delivery_concurrency_is_bounded(tenancy_session_factory) -> None:
    await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 5, tzinfo=UTC)
    for index in range(6):
        await _seed_job(
            tenancy_session_factory,
            org_id=ORG_A,
            suffix=f"concurrency-{index}",
            now=now,
        )
    sink = RecordingSink(delay=0.01)

    result = await run_farm_delivery_batch(
        tenancy_session_factory,
        sink=sink,
        now=now,
        batch_size=10,
        delivery_concurrency=2,
    )

    assert result.delivered == 6
    assert sink.peak == 2
