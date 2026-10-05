from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from db.models.ai_device_lab import ServiceCampaign
from db.models.ai_device_lab_billing import (
    PaymentIntent,
    PaymentReconciliationJob,
    RefundDispatchJob,
    ServiceEntitlement,
    ServiceOrder,
    ServiceRefund,
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
    run_payment_reconciliation_batch,
)
from services.ai_device_lab.billing_refunds import (
    RefundInvariantError,
    RefundPolicy,
    RefundProviderReceipt,
    RequestRefund,
    _acknowledge_dispatch,
    claim_refund_dispatch_batch,
    request_refund,
    run_refund_dispatch_batch,
)
from services.ai_device_lab.service_campaigns import (
    CreateServiceCampaign,
    create_service_campaign,
)
from tenancy.context import tenant_context
from tests.tenancy_test_support import ORG_A, USER_A, seed_two_org_fixture


class RefundAdapter:
    def __init__(
        self,
        receipts: list[RefundProviderReceipt],
        *,
        failures: int = 0,
        delay: float = 0,
    ) -> None:
        self.receipts = receipts
        self.failures = failures
        self.delay = delay
        self.calls: list[tuple[str, int, str, str, str]] = []
        self.active = 0
        self.peak = 0

    async def request_refund(
        self,
        *,
        payment_reference: str,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
        reason_code: str,
    ) -> RefundProviderReceipt:
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            self.calls.append(
                (
                    payment_reference,
                    amount_minor,
                    currency,
                    idempotency_key,
                    reason_code,
                )
            )
            if self.failures:
                self.failures -= 1
                raise RuntimeError("provider secret error must not be persisted")
            return self.receipts.pop(0)
        finally:
            self.active -= 1


class ReconciliationAdapter:
    def __init__(self, snapshot: PaymentProviderSnapshot) -> None:
        self.snapshot = snapshot

    async def fetch_payment(
        self,
        *,
        provider_reference: str,
        idempotency_key: str,
    ) -> PaymentProviderSnapshot:
        return self.snapshot


def _price() -> PriceSnapshot:
    return PriceSnapshot(
        plan_version="adl-14d-v1",
        pricing_version="pricing-v1",
        policy_version="refund-v1",
        amount_minor=129900,
        currency="USD",
        quota={"device_minutes": 2520, "slots": 168},
    )


def _policy(*, allow_partial: bool = False, window: int | None = 86400) -> RefundPolicy:
    return RefundPolicy(
        version="refund-v1",
        allow_partial=allow_partial,
        request_window_seconds=window,
    )


async def _create_paid_order(
    session_factory,
    *,
    runtime_campaign_id: str,
    now: datetime,
    suffix: str,
    with_reference: bool = True,
) -> str:
    with tenant_context(ORG_A):
        async with session_factory() as db:
            campaign = await db.scalar(
                select(ServiceCampaign).where(
                    ServiceCampaign.org_id == ORG_A,
                    ServiceCampaign.runtime_campaign_id == runtime_campaign_id,
                )
            )
            if campaign is None:
                campaign = await create_service_campaign(
                    db,
                    CreateServiceCampaign(
                        org_id=ORG_A,
                        owner_id=USER_A,
                        runtime_campaign_id=runtime_campaign_id,
                        package_name=f"com.example.refund.{suffix}",
                        timezone="UTC",
                        plan_version="adl-14d-v1",
                    ),
                )
            order = await create_order(
                db,
                CreateOrder(
                    org_id=ORG_A,
                    service_campaign_id=campaign.id,
                    idempotency_key=f"order-refund-{suffix}",
                    created_by=USER_A,
                    price=_price(),
                ),
            )
            db.add(
                PaymentIntent(
                    id=f"refund-intent-{suffix}",
                    org_id=ORG_A,
                    order_id=order.id,
                    provider="sandbox",
                    provider_reference=(
                        f"payment-reference-{suffix}" if with_reference else None
                    ),
                    idempotency_key=f"refund-intent-key-{suffix}",
                    amount_minor=order.amount_minor,
                    currency=order.currency,
                    status="paid",
                    created_at=now,
                )
            )
            await accept_payment_event(
                db,
                AcceptPaymentEvent(
                    org_id=ORG_A,
                    order_id=order.id,
                    provider="sandbox",
                    provider_event_id=f"refund-settled-{suffix}",
                    event_type="payment.settled",
                    source_occurred_at=now,
                    signature_verified=True,
                    amount_minor=order.amount_minor,
                    currency=order.currency,
                ),
            )
            await db.commit()
            return order.id


def _command(order_id: str, *, now: datetime, suffix: str) -> RequestRefund:
    return RequestRefund(
        org_id=ORG_A,
        order_id=order_id,
        provider="sandbox",
        idempotency_key=f"refund-request-{suffix}",
        amount_minor=129900,
        reason_code="CUSTOMER_REQUESTED",
        actor_id=USER_A,
        requested_at=now,
        policy=_policy(),
    )


@pytest.mark.asyncio
async def test_refund_request_is_idempotent_and_enforces_snapshot_policy(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    paid_at = datetime(2026, 10, 4, tzinfo=UTC)
    order_id = await _create_paid_order(
        tenancy_session_factory,
        runtime_campaign_id=seeded["campaign_a"],
        now=paid_at,
        suffix="idempotency",
    )
    command = _command(
        order_id,
        now=paid_at + timedelta(minutes=5),
        suffix="idempotency",
    )
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            refund, job = await request_refund(db, command)
            replay_refund, replay_job = await request_refund(db, command)
            with pytest.raises(RefundInvariantError, match="idempotency key"):
                await request_refund(
                    db,
                    replace(command, amount_minor=129899),
                )
            await db.commit()
            refund_count = await db.scalar(
                select(func.count()).select_from(ServiceRefund)
            )
            dispatch_count = await db.scalar(
                select(func.count()).select_from(RefundDispatchJob)
            )

    assert replay_refund.id == refund.id
    assert replay_job.id == job.id
    assert refund_count == 1
    assert dispatch_count == 1

    invalid_commands = (
        replace(
            command,
            idempotency_key="refund-wrong-policy",
            policy=RefundPolicy("refund-v2", False, 86400),
        ),
        replace(
            command,
            idempotency_key="refund-partial-denied",
            amount_minor=100,
        ),
        replace(
            command,
            idempotency_key="refund-expired",
            requested_at=paid_at + timedelta(days=2),
        ),
    )
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            for invalid in invalid_commands:
                with pytest.raises(RefundInvariantError):
                    await request_refund(db, invalid)


@pytest.mark.asyncio
async def test_dispatch_then_authoritative_reconciliation_revokes_entitlement(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    paid_at = datetime(2026, 10, 4, tzinfo=UTC)
    requested_at = paid_at + timedelta(minutes=5)
    order_id = await _create_paid_order(
        tenancy_session_factory,
        runtime_campaign_id=seeded["campaign_a"],
        now=paid_at,
        suffix="success",
    )
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            refund, dispatch = await request_refund(
                db,
                _command(order_id, now=requested_at, suffix="success"),
            )
            await db.commit()

    adapter = RefundAdapter(
        [RefundProviderReceipt(state="accepted", provider_reference="refund-safe-1")]
    )
    result = await run_refund_dispatch_batch(
        tenancy_session_factory,
        adapters={"sandbox": adapter},
        now=requested_at,
    )
    assert result.delivered == 1
    assert adapter.calls == [
        (
            "payment-reference-success",
            129900,
            "USD",
            "refund-request-success",
            "CUSTOMER_REQUESTED",
        )
    ]

    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            order_before = await db.get(ServiceOrder, order_id)
            entitlement_before = await db.scalar(
                select(ServiceEntitlement).where(
                    ServiceEntitlement.order_id == order_id
                )
            )
            stored_refund = await db.get(ServiceRefund, refund.id)
            stored_dispatch = await db.get(RefundDispatchJob, dispatch.id)
            reconciliation = await db.scalar(
                select(PaymentReconciliationJob).where(
                    PaymentReconciliationJob.order_id == order_id,
                    PaymentReconciliationJob.idempotency_key
                    == f"refund:{refund.id}",
                )
            )
    assert order_before is not None and order_before.status == "paid"
    assert entitlement_before is not None and entitlement_before.state == "active"
    assert stored_refund is not None
    assert stored_refund.status == "pending_reconciliation"
    assert stored_refund.provider_reference == "refund-safe-1"
    assert stored_dispatch is not None and stored_dispatch.status == "delivered"
    assert reconciliation is not None

    reconciled = await run_payment_reconciliation_batch(
        tenancy_session_factory,
        adapters={
            "sandbox": ReconciliationAdapter(
                PaymentProviderSnapshot(
                    state="refunded",
                    version="refund-provider-version-1",
                    observed_at=requested_at + timedelta(seconds=3),
                    amount_minor=129900,
                    currency="USD",
                )
            )
        },
        now=requested_at + timedelta(seconds=3),
    )
    assert reconciled.resolved == 1
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            order_after = await db.get(ServiceOrder, order_id)
            entitlement_after = await db.scalar(
                select(ServiceEntitlement).where(
                    ServiceEntitlement.order_id == order_id
                )
            )
    assert order_after is not None and order_after.status == "refunded"
    assert entitlement_after is not None and entitlement_after.state == "revoked"


@pytest.mark.asyncio
async def test_refund_dispatch_retries_with_symbolic_error_then_dead_letters(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    paid_at = datetime(2026, 10, 4, tzinfo=UTC)
    requested_at = paid_at + timedelta(minutes=5)
    order_id = await _create_paid_order(
        tenancy_session_factory,
        runtime_campaign_id=seeded["campaign_a"],
        now=paid_at,
        suffix="retry",
    )
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            refund, dispatch = await request_refund(
                db,
                _command(order_id, now=requested_at, suffix="retry"),
            )
            await db.commit()

    adapter = RefundAdapter([], failures=2)
    first = await run_refund_dispatch_batch(
        tenancy_session_factory,
        adapters={"sandbox": adapter},
        now=requested_at,
        max_attempts=2,
    )
    second = await run_refund_dispatch_batch(
        tenancy_session_factory,
        adapters={"sandbox": adapter},
        now=requested_at + timedelta(seconds=1),
        max_attempts=2,
    )
    assert first.retry_scheduled == 1
    assert second.dead_lettered == 1
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            stored_job = await db.get(RefundDispatchJob, dispatch.id)
            stored_refund = await db.get(ServiceRefund, refund.id)
    assert stored_job is not None and stored_job.status == "dead_lettered"
    assert stored_job.last_error_code == "PROVIDER_UNAVAILABLE"
    assert "secret" not in stored_job.last_error_code.lower()
    assert stored_refund is not None and stored_refund.status == "dispatch_failed"


@pytest.mark.asyncio
async def test_expired_refund_worker_cannot_acknowledge_a_newer_lease(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    paid_at = datetime(2026, 10, 4, tzinfo=UTC)
    requested_at = paid_at + timedelta(minutes=5)
    order_id = await _create_paid_order(
        tenancy_session_factory,
        runtime_campaign_id=seeded["campaign_a"],
        now=paid_at,
        suffix="fenced",
    )
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            refund, dispatch = await request_refund(
                db,
                _command(order_id, now=requested_at, suffix="fenced"),
            )
            await db.commit()
        async with tenancy_session_factory() as db:
            claims = await claim_refund_dispatch_batch(db, now=requested_at)
            await db.commit()
        async with tenancy_session_factory() as db:
            stored_job = await db.get(RefundDispatchJob, dispatch.id)
            assert stored_job is not None
            stored_job.lease_token = "newer-worker-token"
            await db.commit()

    result = await _acknowledge_dispatch(
        tenancy_session_factory,
        claim=claims[0],
        outcome="delivered",
        detail=RefundProviderReceipt(
            state="accepted",
            provider_reference="must-not-be-recorded",
        ),
        now=requested_at + timedelta(seconds=1),
        max_attempts=8,
    )
    assert result == "stale"
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            stored_job = await db.get(RefundDispatchJob, dispatch.id)
            stored_refund = await db.get(ServiceRefund, refund.id)
            reconciliation_count = await db.scalar(
                select(func.count()).select_from(PaymentReconciliationJob)
            )
    assert stored_job is not None and stored_job.status == "processing"
    assert stored_job.lease_token == "newer-worker-token"
    assert stored_refund is not None and stored_refund.status == "pending_dispatch"
    assert stored_refund.provider_reference is None
    assert reconciliation_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("with_reference", [False, True])
async def test_missing_reference_or_adapter_blocks_without_revoking_entitlement(
    tenancy_session_factory,
    with_reference: bool,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    paid_at = datetime(2026, 10, 4, tzinfo=UTC)
    requested_at = paid_at + timedelta(minutes=5)
    suffix = "missing-adapter" if with_reference else "missing-reference"
    order_id = await _create_paid_order(
        tenancy_session_factory,
        runtime_campaign_id=seeded["campaign_a"],
        now=paid_at,
        suffix=suffix,
        with_reference=with_reference,
    )
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            refund, dispatch = await request_refund(
                db,
                _command(order_id, now=requested_at, suffix=suffix),
            )
            await db.commit()

    adapters = {} if with_reference else {"sandbox": RefundAdapter([])}
    result = await run_refund_dispatch_batch(
        tenancy_session_factory,
        adapters=adapters,
        now=requested_at,
    )
    assert result.blocked == 1
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            order = await db.get(ServiceOrder, order_id)
            entitlement = await db.scalar(
                select(ServiceEntitlement).where(
                    ServiceEntitlement.order_id == order_id
                )
            )
            stored_job = await db.get(RefundDispatchJob, dispatch.id)
            stored_refund = await db.get(ServiceRefund, refund.id)
    assert order is not None and order.status == "paid"
    assert entitlement is not None and entitlement.state == "active"
    assert stored_job is not None and stored_job.status == "blocked"
    expected = (
        "PROVIDER_ADAPTER_UNAVAILABLE"
        if with_reference
        else "PAYMENT_REFERENCE_MISSING"
    )
    assert stored_job.last_error_code == expected
    assert stored_refund is not None and stored_refund.status == "dispatch_blocked"


@pytest.mark.asyncio
async def test_refund_dispatch_bounds_batch_and_provider_concurrency(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    paid_at = datetime(2026, 10, 4, tzinfo=UTC)
    requested_at = paid_at + timedelta(minutes=5)
    order_ids = [
        await _create_paid_order(
            tenancy_session_factory,
            runtime_campaign_id=seeded["campaign_a"],
            now=paid_at,
            suffix=f"bounded-{index}",
        )
        for index in range(5)
    ]
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            for index, order_id in enumerate(order_ids):
                await request_refund(
                    db,
                    _command(
                        order_id,
                        now=requested_at,
                        suffix=f"bounded-{index}",
                    ),
                )
            await db.commit()

    adapter = RefundAdapter(
        [RefundProviderReceipt(state="accepted") for _ in range(5)],
        delay=0.01,
    )
    result = await run_refund_dispatch_batch(
        tenancy_session_factory,
        adapters={"sandbox": adapter},
        now=requested_at,
        batch_size=4,
        concurrency=2,
    )
    assert result.claimed == 4
    assert result.delivered == 4
    assert len(adapter.calls) == 4
    assert adapter.peak == 2
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            pending = await db.scalar(
                select(func.count())
                .select_from(RefundDispatchJob)
                .where(RefundDispatchJob.status == "pending")
            )
    assert pending == 1
