from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from db.models.ai_device_lab_billing import (
    PaymentEvent,
    PaymentIntent,
    PaymentReconciliationJob,
    ServiceEntitlement,
    ServiceOrder,
)
from services.ai_device_lab.billing import (
    AcceptPaymentEvent,
    CreateOrder,
    PriceSnapshot,
    accept_payment_event,
    create_order,
)
from services.ai_device_lab.billing_reconciliation import (
    PaymentProviderSnapshot,
    enqueue_payment_reconciliation,
    run_payment_reconciliation_batch,
)
from services.ai_device_lab.service_campaigns import (
    CreateServiceCampaign,
    create_service_campaign,
)
from tenancy.context import tenant_context
from tests.tenancy_test_support import (
    ORG_A,
    ORG_B,
    USER_A,
    USER_B,
    api_client_for_user,
    build_tenancy_api_app,
    seed_two_org_fixture,
)


class SnapshotAdapter:
    def __init__(
        self,
        snapshots: list[PaymentProviderSnapshot],
        *,
        failures: int = 0,
        delay: float = 0,
    ) -> None:
        self.snapshots = snapshots
        self.failures = failures
        self.delay = delay
        self.calls: list[tuple[str, str]] = []
        self.active = 0
        self.peak = 0

    async def fetch_payment(
        self,
        *,
        provider_reference: str,
        idempotency_key: str,
    ) -> PaymentProviderSnapshot:
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            self.calls.append((provider_reference, idempotency_key))
            if self.failures:
                self.failures -= 1
                raise RuntimeError("provider details must not be persisted")
            return self.snapshots.pop(0)
        finally:
            self.active -= 1


def _price() -> PriceSnapshot:
    return PriceSnapshot(
        plan_version="adl-14d-v1",
        pricing_version="pricing-v1",
        policy_version="refund-v1",
        amount_minor=129900,
        currency="USD",
        quota={"device_minutes": 2520, "slots": 168},
    )


async def _seed_order(session_factory, *, now: datetime, suffix: str) -> str:
    seeded = await seed_two_org_fixture(session_factory)
    with tenant_context(ORG_A):
        async with session_factory() as db:
            campaign = await create_service_campaign(
                db,
                CreateServiceCampaign(
                    org_id=ORG_A,
                    owner_id=USER_A,
                    runtime_campaign_id=seeded["campaign_a"],
                    package_name=f"com.example.{suffix}",
                    timezone="UTC",
                    plan_version="adl-14d-v1",
                ),
            )
            order = await create_order(
                db,
                CreateOrder(
                    org_id=ORG_A,
                    service_campaign_id=campaign.id,
                    idempotency_key=f"order-{suffix}",
                    created_by=USER_A,
                    price=_price(),
                ),
            )
            db.add(
                PaymentIntent(
                    id=f"intent-{suffix}",
                    org_id=ORG_A,
                    order_id=order.id,
                    provider="sandbox",
                    provider_reference=f"provider-{suffix}",
                    idempotency_key=f"intent-key-{suffix}",
                    amount_minor=order.amount_minor,
                    currency=order.currency,
                    status="uncertain",
                    created_at=now,
                )
            )
            await db.commit()
            return order.id


@pytest.mark.asyncio
async def test_amount_mismatch_enqueues_one_durable_reconciliation_job(
    tenancy_session_factory,
) -> None:
    now = datetime(2026, 10, 5, tzinfo=UTC)
    order_id = await _seed_order(tenancy_session_factory, now=now, suffix="mismatch")
    command = AcceptPaymentEvent(
        org_id=ORG_A,
        order_id=order_id,
        provider="sandbox",
        provider_event_id="evt-mismatch",
        event_type="payment.settled",
        source_occurred_at=now,
        signature_verified=True,
        amount_minor=1,
        currency="USD",
    )
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            event, entitlement = await accept_payment_event(db, command)
            duplicate, _ = await accept_payment_event(db, command)
            await db.commit()
            jobs = list((await db.execute(select(PaymentReconciliationJob))).scalars())

    assert event.id == duplicate.id
    assert entitlement is None
    assert event.processing_state == "pending_reconciliation"
    assert event.reason_code == "AMOUNT_OR_CURRENCY_MISMATCH"
    assert len(jobs) == 1
    assert jobs[0].provider_reference == "provider-mismatch"


@pytest.mark.asyncio
async def test_reconciliation_paid_snapshot_grants_once_and_resolves_atomically(
    tenancy_session_factory,
) -> None:
    now = datetime(2026, 10, 5, tzinfo=UTC)
    order_id = await _seed_order(tenancy_session_factory, now=now, suffix="paid")
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            job = await enqueue_payment_reconciliation(
                db,
                org_id=ORG_A,
                order_id=order_id,
                provider="sandbox",
                reason_code="CHECKOUT_RESPONSE_LOST",
                idempotency_key="reconcile-paid",
                now=now,
            )
            await db.commit()
    adapter = SnapshotAdapter(
        [
            PaymentProviderSnapshot(
                state="paid",
                version="provider-version-1",
                observed_at=now + timedelta(seconds=5),
                amount_minor=129900,
                currency="USD",
            )
        ]
    )

    result = await run_payment_reconciliation_batch(
        tenancy_session_factory,
        adapters={"sandbox": adapter},
        now=now + timedelta(seconds=5),
    )
    replay = await run_payment_reconciliation_batch(
        tenancy_session_factory,
        adapters={"sandbox": adapter},
        now=now + timedelta(seconds=6),
    )

    assert result.resolved == 1
    assert replay.claimed == 0
    assert adapter.calls == [("provider-paid", job.idempotency_key)]
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            order = await db.get(ServiceOrder, order_id)
            stored_job = await db.get(PaymentReconciliationJob, job.id)
            grants = await db.scalar(
                select(func.count()).select_from(ServiceEntitlement)
            )
            events = await db.scalar(select(func.count()).select_from(PaymentEvent))
    assert order is not None and order.status == "paid"
    assert stored_job is not None and stored_job.status == "resolved"
    assert grants == 1
    assert events == 1


@pytest.mark.asyncio
async def test_reconciliation_retry_is_fenced_and_does_not_persist_provider_error(
    tenancy_session_factory,
) -> None:
    now = datetime(2026, 10, 5, tzinfo=UTC)
    order_id = await _seed_order(tenancy_session_factory, now=now, suffix="retry")
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            job = await enqueue_payment_reconciliation(
                db,
                org_id=ORG_A,
                order_id=order_id,
                provider="sandbox",
                reason_code="PROVIDER_TIMEOUT",
                idempotency_key="reconcile-retry",
                now=now,
            )
            await db.commit()
    adapter = SnapshotAdapter(
        [
            PaymentProviderSnapshot(
                state="refunded",
                version="provider-version-2",
                observed_at=now + timedelta(seconds=2),
                amount_minor=129900,
                currency="USD",
            )
        ],
        failures=1,
    )

    failed = await run_payment_reconciliation_batch(
        tenancy_session_factory,
        adapters={"sandbox": adapter},
        now=now,
        max_attempts=3,
    )
    too_early = await run_payment_reconciliation_batch(
        tenancy_session_factory,
        adapters={"sandbox": adapter},
        now=now + timedelta(milliseconds=999),
        max_attempts=3,
    )
    recovered = await run_payment_reconciliation_batch(
        tenancy_session_factory,
        adapters={"sandbox": adapter},
        now=now + timedelta(seconds=1),
        max_attempts=3,
    )

    assert failed.retry_scheduled == 1
    assert too_early.claimed == 0
    assert recovered.resolved == 1
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            stored = await db.get(PaymentReconciliationJob, job.id)
            order = await db.get(ServiceOrder, order_id)
    assert stored is not None
    assert stored.last_error_code is None
    assert "provider details" not in repr(stored.__dict__)
    assert order is not None and order.status == "refunded"


@pytest.mark.asyncio
async def test_missing_adapter_or_provider_reference_blocks_without_false_grant(
    tenancy_session_factory,
) -> None:
    now = datetime(2026, 10, 5, tzinfo=UTC)
    order_id = await _seed_order(tenancy_session_factory, now=now, suffix="blocked")
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            intent = await db.get(PaymentIntent, "intent-blocked")
            assert intent is not None
            intent.provider_reference = None
            job = await enqueue_payment_reconciliation(
                db,
                org_id=ORG_A,
                order_id=order_id,
                provider="sandbox",
                reason_code="PROVIDER_TIMEOUT",
                idempotency_key="reconcile-blocked",
                now=now,
            )
            await db.commit()

    result = await run_payment_reconciliation_batch(
        tenancy_session_factory,
        adapters={},
        now=now,
    )

    assert result.blocked == 1
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            stored = await db.get(PaymentReconciliationJob, job.id)
            grants = await db.scalar(
                select(func.count()).select_from(ServiceEntitlement)
            )
    assert stored is not None
    assert stored.status == "blocked"
    assert stored.last_error_code == "PROVIDER_REFERENCE_MISSING"
    assert grants == 0


@pytest.mark.asyncio
async def test_reconciliation_queue_api_is_tenant_scoped_and_never_returns_provider_ref(
    tenancy_session_factory,
) -> None:
    now = datetime(2026, 10, 5, tzinfo=UTC)
    order_id = await _seed_order(tenancy_session_factory, now=now, suffix="api")
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            await enqueue_payment_reconciliation(
                db,
                org_id=ORG_A,
                order_id=order_id,
                provider="sandbox",
                reason_code="PROVIDER_TIMEOUT",
                idempotency_key="reconcile-api",
                now=now,
            )
            order = await db.get(ServiceOrder, order_id)
            assert order is not None
            campaign_id = order.service_campaign_id
            await db.commit()
    app = build_tenancy_api_app(tenancy_session_factory)

    async with api_client_for_user(app, USER_A, ORG_A) as client:
        response = await client.get(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}/payment-reconciliations"
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["status"] == "pending"
    assert "provider_reference" not in payload["items"][0]
    assert "provider-api" not in response.text

    async with api_client_for_user(app, USER_B, ORG_B) as client:
        cross_tenant = await client.get(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}/payment-reconciliations"
        )
    assert cross_tenant.status_code == 404


@pytest.mark.asyncio
async def test_reconciliation_batch_and_provider_concurrency_are_bounded(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 5, tzinfo=UTC)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign = await create_service_campaign(
                db,
                CreateServiceCampaign(
                    org_id=ORG_A,
                    owner_id=USER_A,
                    runtime_campaign_id=seeded["campaign_a"],
                    package_name="com.example.reconciliation-scale",
                    timezone="UTC",
                    plan_version="adl-14d-v1",
                ),
            )
            for index in range(6):
                order = await create_order(
                    db,
                    CreateOrder(
                        org_id=ORG_A,
                        service_campaign_id=campaign.id,
                        idempotency_key=f"scale-order-{index}",
                        created_by=USER_A,
                        price=_price(),
                    ),
                )
                db.add(
                    PaymentIntent(
                        org_id=ORG_A,
                        order_id=order.id,
                        provider="sandbox",
                        provider_reference=f"scale-provider-{index}",
                        idempotency_key=f"scale-intent-{index}",
                        amount_minor=order.amount_minor,
                        currency=order.currency,
                        status="uncertain",
                        created_at=now,
                    )
                )
                await db.flush()
                await enqueue_payment_reconciliation(
                    db,
                    org_id=ORG_A,
                    order_id=order.id,
                    provider="sandbox",
                    reason_code="PROVIDER_TIMEOUT",
                    idempotency_key=f"scale-reconcile-{index}",
                    now=now,
                )
            await db.commit()
    adapter = SnapshotAdapter(
        [
            PaymentProviderSnapshot(
                state="pending",
                version=f"pending-{index}",
                observed_at=now,
                amount_minor=129900,
                currency="USD",
            )
            for index in range(3)
        ],
        delay=0.01,
    )

    result = await run_payment_reconciliation_batch(
        tenancy_session_factory,
        adapters={"sandbox": adapter},
        now=now,
        batch_size=3,
        concurrency=2,
    )

    assert result.claimed == 3
    assert result.retry_scheduled == 3
    assert len(adapter.calls) == 3
    assert adapter.peak == 2
