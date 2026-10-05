"""Idempotent provider-neutral billing state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.ai_device_lab import ServiceCampaign
from db.models.ai_device_lab_billing import (
    PaymentEvent,
    PaymentIntent,
    ServiceEntitlement,
    ServiceOrder,
)
from services.ai_device_lab.funnel import record_server_funnel_event


class BillingInvariantError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PriceSnapshot:
    plan_version: str
    pricing_version: str
    policy_version: str
    amount_minor: int
    currency: str
    quota: dict


@dataclass(frozen=True, slots=True)
class CreateOrder:
    org_id: str
    service_campaign_id: str
    idempotency_key: str
    created_by: str
    price: PriceSnapshot


@dataclass(frozen=True, slots=True)
class AcceptPaymentEvent:
    org_id: str
    order_id: str
    provider: str
    provider_event_id: str
    event_type: str
    source_occurred_at: datetime
    signature_verified: bool
    amount_minor: int | None = None
    currency: str | None = None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def create_order(db: AsyncSession, command: CreateOrder) -> ServiceOrder:
    if command.price.amount_minor <= 0:
        raise BillingInvariantError("amount must use positive integer minor units")
    currency = command.price.currency.strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise BillingInvariantError("currency must be a three-letter ISO code")
    existing = (
        await db.execute(
            select(ServiceOrder).where(
                ServiceOrder.org_id == command.org_id,
                ServiceOrder.idempotency_key == command.idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.service_campaign_id != command.service_campaign_id
            or existing.plan_version != command.price.plan_version
            or existing.pricing_version != command.price.pricing_version
            or existing.policy_version != command.price.policy_version
            or existing.quota_snapshot != command.price.quota
            or existing.amount_minor != command.price.amount_minor
            or existing.currency != currency
            or existing.created_by != command.created_by
        ):
            raise BillingInvariantError("order idempotency key was reused with different input")
        return existing
    campaign = (
        await db.execute(
            select(ServiceCampaign).where(
                ServiceCampaign.id == command.service_campaign_id,
                ServiceCampaign.org_id == command.org_id,
            )
        )
    ).scalar_one_or_none()
    if campaign is None or campaign.plan_version != command.price.plan_version:
        raise BillingInvariantError("campaign does not match the priced plan")
    order = ServiceOrder(
        org_id=command.org_id,
        service_campaign_id=command.service_campaign_id,
        idempotency_key=command.idempotency_key,
        plan_version=command.price.plan_version,
        pricing_version=command.price.pricing_version,
        policy_version=command.price.policy_version,
        quota_snapshot=command.price.quota,
        amount_minor=command.price.amount_minor,
        currency=currency,
        status="pending",
        created_by=command.created_by,
    )
    db.add(order)
    await db.flush()
    return order


async def accept_payment_event(
    db: AsyncSession,
    command: AcceptPaymentEvent,
) -> tuple[PaymentEvent, ServiceEntitlement | None]:
    if not command.signature_verified:
        raise BillingInvariantError("payment event signature is not verified")
    duplicate_row = (
        await db.execute(
            select(PaymentEvent.__table__).where(
                PaymentEvent.__table__.c.provider == command.provider,
                PaymentEvent.__table__.c.provider_event_id == command.provider_event_id,
            )
        )
    ).mappings().one_or_none()
    if duplicate_row is not None:
        normalized_currency = command.currency.upper() if command.currency else None
        if (
            duplicate_row["org_id"] != command.org_id
            or duplicate_row["order_id"] != command.order_id
            or duplicate_row["event_type"] != command.event_type
            or duplicate_row["amount_minor"] != command.amount_minor
            or duplicate_row["currency"] != normalized_currency
            or _utc(duplicate_row["source_occurred_at"]) != _utc(command.source_occurred_at)
        ):
            raise BillingInvariantError("provider event id was reused with different input")
        duplicate = await db.get(PaymentEvent, duplicate_row["id"])
        if duplicate is None:
            raise BillingInvariantError("provider event is outside tenant scope")
        entitlement = (
            await db.execute(
                select(ServiceEntitlement).where(
                    ServiceEntitlement.org_id == command.org_id,
                    ServiceEntitlement.order_id == command.order_id,
                )
            )
        ).scalar_one_or_none()
        return duplicate, entitlement

    order = (
        await db.execute(
            select(ServiceOrder)
            .where(
                ServiceOrder.id == command.order_id,
                ServiceOrder.org_id == command.org_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if order is None:
        raise BillingInvariantError("order not found")
    event = PaymentEvent(
        org_id=command.org_id,
        order_id=order.id,
        provider=command.provider,
        provider_event_id=command.provider_event_id,
        event_type=command.event_type,
        amount_minor=command.amount_minor,
        currency=command.currency.upper() if command.currency else None,
        signature_verified=True,
        source_occurred_at=command.source_occurred_at,
        processing_state="accepted",
    )
    db.add(event)
    entitlement = (
        await db.execute(
            select(ServiceEntitlement).where(
                ServiceEntitlement.org_id == command.org_id,
                ServiceEntitlement.order_id == order.id,
            )
        )
    ).scalar_one_or_none()
    intent = (
        await db.execute(
            select(PaymentIntent).where(
                PaymentIntent.org_id == command.org_id,
                PaymentIntent.order_id == order.id,
            )
        )
    ).scalar_one_or_none()

    reconciliation_reason: str | None = None
    if command.event_type == "payment.settled":
        if command.amount_minor != order.amount_minor or (command.currency or "").upper() != order.currency:
            event.processing_state = "pending_reconciliation"
            event.reason_code = "AMOUNT_OR_CURRENCY_MISMATCH"
            reconciliation_reason = event.reason_code
            if intent is not None:
                intent.status = "uncertain"
                intent.last_error_code = event.reason_code
        elif order.status == "refunded":
            event.processing_state = "ignored"
            event.reason_code = "ORDER_ALREADY_REFUNDED"
            if intent is not None:
                intent.status = "refunded"
                intent.last_error_code = None
        else:
            order.status = "paid"
            order.paid_at = command.source_occurred_at
            if intent is not None:
                intent.status = "paid"
                intent.last_error_code = None
            if entitlement is None:
                entitlement = ServiceEntitlement(
                    org_id=command.org_id,
                    order_id=order.id,
                    service_campaign_id=order.service_campaign_id,
                    state="active",
                )
                db.add(entitlement)
    elif command.event_type in {"payment.refunded", "payment.chargeback"}:
        order.status = "refunded"
        order.refunded_at = command.source_occurred_at
        if intent is not None:
            intent.status = "refunded"
            intent.last_error_code = None
        if entitlement is not None:
            entitlement.state = "revoked"
            entitlement.revoked_at = datetime.now(UTC)
            entitlement.revoke_reason = command.event_type
    else:
        event.processing_state = "pending_reconciliation"
        event.reason_code = "UNSUPPORTED_PROVIDER_EVENT"
        reconciliation_reason = event.reason_code
        if intent is not None:
            intent.status = "uncertain"
            intent.last_error_code = event.reason_code
    await db.flush()
    if event.processing_state == "accepted" and order.status == "paid":
        await record_server_funnel_event(
            db,
            org_id=command.org_id,
            service_campaign_id=order.service_campaign_id,
            event_name="payment_completed",
            source_ref=event.id,
            occurred_at=command.source_occurred_at,
        )
    if reconciliation_reason is not None:
        from services.ai_device_lab.billing_reconciliation import (
            enqueue_payment_event_reconciliation,
        )

        await enqueue_payment_event_reconciliation(
            db,
            event=event,
            reason_code=reconciliation_reason,
        )
    return event, entitlement
