from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from db.models.ai_device_lab_billing import PaymentEvent, ServiceEntitlement
from services.ai_device_lab.billing import (
    AcceptPaymentEvent,
    BillingInvariantError,
    CreateOrder,
    PriceSnapshot,
    accept_payment_event,
    create_order,
)
from services.ai_device_lab.service_campaigns import CreateServiceCampaign, create_service_campaign
from tenancy.context import tenant_context
from tests.tenancy_test_support import ORG_A, ORG_B, USER_A, USER_B, seed_two_org_fixture


def _price() -> PriceSnapshot:
    return PriceSnapshot(
        plan_version="adl-14d-v1",
        pricing_version="pricing-v1",
        policy_version="refund-v1",
        amount_minor=129900,
        currency="USD",
        quota={"device_minutes": 2520, "slots": 168},
    )


@pytest.mark.asyncio
async def test_verified_duplicate_settlement_grants_one_entitlement(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign = await create_service_campaign(
                db,
                CreateServiceCampaign(
                    org_id=ORG_A,
                    owner_id=USER_A,
                    runtime_campaign_id=seeded["campaign_a"],
                    package_name="com.example.app",
                    timezone="UTC",
                    plan_version="adl-14d-v1",
                ),
            )
            order = await create_order(
                db,
                CreateOrder(
                    org_id=ORG_A,
                    service_campaign_id=campaign.id,
                    idempotency_key="order-1",
                    created_by=USER_A,
                    price=_price(),
                ),
            )
            repeated_order = await create_order(
                db,
                CreateOrder(
                    org_id=ORG_A,
                    service_campaign_id=campaign.id,
                    idempotency_key="order-1",
                    created_by=USER_A,
                    price=_price(),
                ),
            )
            with pytest.raises(BillingInvariantError, match="order idempotency key"):
                await create_order(
                    db,
                    CreateOrder(
                        org_id=ORG_A,
                        service_campaign_id=campaign.id,
                        idempotency_key="order-1",
                        created_by=USER_A,
                        price=PriceSnapshot(
                            plan_version="adl-14d-v1",
                            pricing_version="pricing-v2",
                            policy_version="refund-v1",
                            amount_minor=139900,
                            currency="USD",
                            quota={"device_minutes": 2520, "slots": 168},
                        ),
                    ),
                )
            event_command = AcceptPaymentEvent(
                org_id=ORG_A,
                order_id=order.id,
                provider="sandbox",
                provider_event_id="evt-settled-1",
                event_type="payment.settled",
                source_occurred_at=now,
                signature_verified=True,
                amount_minor=129900,
                currency="USD",
            )
            first_event, first_grant = await accept_payment_event(db, event_command)
            second_event, second_grant = await accept_payment_event(db, event_command)
            with pytest.raises(BillingInvariantError, match="provider event id"):
                await accept_payment_event(
                    db,
                    AcceptPaymentEvent(
                        org_id=ORG_A,
                        order_id=order.id,
                        provider="sandbox",
                        provider_event_id="evt-settled-1",
                        event_type="payment.settled",
                        source_occurred_at=now,
                        signature_verified=True,
                        amount_minor=1,
                        currency="USD",
                    ),
                )
            await db.commit()
            event_count = await db.scalar(select(func.count()).select_from(PaymentEvent))
            grant_count = await db.scalar(select(func.count()).select_from(ServiceEntitlement))

    assert repeated_order.id == order.id
    assert first_event.id == second_event.id
    assert first_grant is not None and second_grant is not None
    assert first_grant.id == second_grant.id
    assert event_count == 1
    assert grant_count == 1
    assert order.status == "paid"


@pytest.mark.asyncio
async def test_refund_is_not_resurrected_by_delayed_paid_event_and_forgery_is_rejected(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign = await create_service_campaign(
                db,
                CreateServiceCampaign(
                    org_id=ORG_A,
                    owner_id=USER_A,
                    runtime_campaign_id=seeded["campaign_a"],
                    package_name="com.example.app",
                    timezone="UTC",
                    plan_version="adl-14d-v1",
                ),
            )
            order = await create_order(
                db,
                CreateOrder(
                    org_id=ORG_A,
                    service_campaign_id=campaign.id,
                    idempotency_key="order-2",
                    created_by=USER_A,
                    price=_price(),
                ),
            )
            with pytest.raises(BillingInvariantError):
                await accept_payment_event(
                    db,
                    AcceptPaymentEvent(
                        org_id=ORG_A,
                        order_id=order.id,
                        provider="sandbox",
                        provider_event_id="evt-forged",
                        event_type="payment.settled",
                        source_occurred_at=now,
                        signature_verified=False,
                        amount_minor=129900,
                        currency="USD",
                    ),
                )
            await accept_payment_event(
                db,
                AcceptPaymentEvent(
                    org_id=ORG_A,
                    order_id=order.id,
                    provider="sandbox",
                    provider_event_id="evt-refund",
                    event_type="payment.refunded",
                    source_occurred_at=now + timedelta(minutes=2),
                    signature_verified=True,
                ),
            )
            delayed, grant = await accept_payment_event(
                db,
                AcceptPaymentEvent(
                    org_id=ORG_A,
                    order_id=order.id,
                    provider="sandbox",
                    provider_event_id="evt-delayed-paid",
                    event_type="payment.settled",
                    source_occurred_at=now,
                    signature_verified=True,
                    amount_minor=129900,
                    currency="USD",
                ),
            )

    assert order.status == "refunded"
    assert grant is None
    assert delayed.processing_state == "ignored"
    assert delayed.reason_code == "ORDER_ALREADY_REFUNDED"


@pytest.mark.asyncio
async def test_provider_event_id_cannot_be_rebound_to_another_tenant_order(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign_a = await create_service_campaign(
                db,
                CreateServiceCampaign(
                    org_id=ORG_A,
                    owner_id=USER_A,
                    runtime_campaign_id=seeded["campaign_a"],
                    package_name="com.example.billing.a",
                    timezone="UTC",
                    plan_version="adl-14d-v1",
                ),
            )
            order_a = await create_order(
                db,
                CreateOrder(
                    org_id=ORG_A,
                    service_campaign_id=campaign_a.id,
                    idempotency_key="order-provider-global-a",
                    created_by=USER_A,
                    price=_price(),
                ),
            )
            await accept_payment_event(
                db,
                AcceptPaymentEvent(
                    org_id=ORG_A,
                    order_id=order_a.id,
                    provider="sandbox",
                    provider_event_id="evt-provider-global",
                    event_type="payment.settled",
                    source_occurred_at=now,
                    signature_verified=True,
                    amount_minor=129900,
                    currency="USD",
                ),
            )
            await db.commit()

    with tenant_context(ORG_B):
        async with tenancy_session_factory() as db:
            campaign_b = await create_service_campaign(
                db,
                CreateServiceCampaign(
                    org_id=ORG_B,
                    owner_id=USER_B,
                    runtime_campaign_id=seeded["campaign_b"],
                    package_name="com.example.billing.b",
                    timezone="UTC",
                    plan_version="adl-14d-v1",
                ),
            )
            order_b = await create_order(
                db,
                CreateOrder(
                    org_id=ORG_B,
                    service_campaign_id=campaign_b.id,
                    idempotency_key="order-provider-global-b",
                    created_by=USER_B,
                    price=_price(),
                ),
            )
            with pytest.raises(BillingInvariantError, match="provider event id"):
                await accept_payment_event(
                    db,
                    AcceptPaymentEvent(
                        org_id=ORG_B,
                        order_id=order_b.id,
                        provider="sandbox",
                        provider_event_id="evt-provider-global",
                        event_type="payment.settled",
                        source_occurred_at=now,
                        signature_verified=True,
                        amount_minor=129900,
                        currency="USD",
                    ),
                )
            entitlement_count = await db.scalar(
                select(func.count()).select_from(ServiceEntitlement)
            )

    assert entitlement_count == 0
