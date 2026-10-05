"""Provider-neutral, idempotent checkout creation and uncertain-state recovery."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.ai_device_lab import ServiceCampaign
from db.models.ai_device_lab_billing import PaymentIntent
from services.ai_device_lab.billing import CreateOrder, PriceSnapshot, create_order
from services.ai_device_lab.billing_reconciliation import (
    enqueue_payment_reconciliation,
)

_PROVIDER_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}")


class CheckoutInvariantError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CheckoutProviderSession:
    provider_reference: str
    checkout_url: str
    expires_at: datetime


class CheckoutProviderAdapter(Protocol):
    async def create_or_lookup_checkout(
        self,
        *,
        order_id: str,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
        return_url: str,
        cancel_url: str,
    ) -> CheckoutProviderSession: ...


@dataclass(frozen=True, slots=True)
class StartWizardCheckout:
    org_id: str
    service_campaign_id: str
    approval_id: str
    idempotency_key: str
    actor_id: str
    now: datetime


@dataclass(frozen=True, slots=True)
class CheckoutResult:
    order_id: str
    intent_id: str
    status: str
    checkout_url: str | None
    expires_at: datetime | None
    blocker_code: str | None


_configured_adapters: dict[str, CheckoutProviderAdapter] = {}
_provider_slots: dict[str, asyncio.Semaphore] = {}


def _provider(value: str) -> str:
    normalized = value.strip().lower()
    if _PROVIDER_NAME.fullmatch(normalized) is None:
        raise CheckoutInvariantError("INVALID_PAYMENT_PROVIDER")
    return normalized


def _checkout_concurrency() -> int:
    try:
        configured = int(os.getenv("AI_DEVICE_LAB_CHECKOUT_CONCURRENCY", "8"))
    except ValueError:
        configured = 8
    return max(1, min(32, configured))


def _checkout_timeout_seconds() -> float:
    try:
        configured = float(
            os.getenv("AI_DEVICE_LAB_CHECKOUT_TIMEOUT_SECONDS", "10")
        )
    except ValueError:
        configured = 10
    return max(1.0, min(30.0, configured))


def configure_checkout_provider_adapter(
    provider: str,
    adapter: CheckoutProviderAdapter | None,
) -> None:
    normalized = _provider(provider)
    if adapter is None:
        _configured_adapters.pop(normalized, None)
        _provider_slots.pop(normalized, None)
    else:
        _configured_adapters[normalized] = adapter
        _provider_slots[normalized] = asyncio.Semaphore(_checkout_concurrency())


def _allowed_checkout_hosts() -> frozenset[str]:
    return frozenset(
        item.strip().lower()
        for item in os.getenv("AI_DEVICE_LAB_CHECKOUT_ALLOWED_HOSTS", "").split(",")
        if item.strip()
    )


def _configured_url(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return None
    return value


def checkout_provider_available(provider: str | None) -> bool:
    if provider is None:
        return False
    try:
        normalized = _provider(provider)
    except CheckoutInvariantError:
        return False
    return bool(
        normalized in _configured_adapters
        and _allowed_checkout_hosts()
        and _configured_url("AI_DEVICE_LAB_CHECKOUT_RETURN_URL")
        and _configured_url("AI_DEVICE_LAB_CHECKOUT_CANCEL_URL")
    )


def _callback_url(base: str, *, campaign_id: str) -> str:
    parsed = urlsplit(base)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["campaign_id"] = campaign_id
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def _valid_checkout_session(
    session: CheckoutProviderSession,
    *,
    now: datetime,
) -> bool:
    reference = session.provider_reference.strip()
    parsed = urlsplit(session.checkout_url)
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    else:
        expires_at = expires_at.astimezone(UTC)
    observed_at = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
    return bool(
        1 <= len(reference) <= 255
        and not any(ord(char) < 32 for char in reference)
        and parsed.scheme == "https"
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and parsed.hostname.lower() in _allowed_checkout_hosts()
        and observed_at < expires_at <= observed_at + timedelta(days=7)
    )


def _order_idempotency_key(campaign_id: str) -> str:
    digest = hashlib.sha256(campaign_id.encode()).hexdigest()
    return f"wizard-order:{digest}"


async def _mark_uncertain(
    db: AsyncSession,
    *,
    org_id: str,
    intent_id: str,
    order_id: str,
    provider: str,
    error_code: str,
    now: datetime,
) -> PaymentIntent:
    intent = (
        await db.execute(
            select(PaymentIntent)
            .where(
                PaymentIntent.org_id == org_id,
                PaymentIntent.id == intent_id,
            )
            .with_for_update()
        )
    ).scalar_one()
    intent.status = "uncertain"
    intent.last_error_code = error_code
    await enqueue_payment_reconciliation(
        db,
        org_id=org_id,
        order_id=order_id,
        provider=provider,
        reason_code=error_code,
        idempotency_key=f"checkout:{intent.id}",
        provider_lookup_key=intent.idempotency_key,
        now=now,
    )
    await db.commit()
    return intent


async def start_wizard_checkout(
    db: AsyncSession,
    command: StartWizardCheckout,
) -> CheckoutResult:
    if not 8 <= len(command.idempotency_key) <= 128:
        raise CheckoutInvariantError("INVALID_CHECKOUT_IDEMPOTENCY_KEY")
    from services.ai_device_lab.wizard import load_wizard_state

    state = await load_wizard_state(
        db,
        org_id=command.org_id,
        service_campaign_id=command.service_campaign_id,
    )
    if state.approval is None or state.approval.id != command.approval_id:
        raise CheckoutInvariantError("CURRENT_APPROVAL_REQUIRED")
    payment = state.payment
    if (
        not payment.provider_configured
        or payment.provider is None
        or payment.amount_minor is None
        or payment.currency is None
        or payment.pricing_version is None
    ):
        raise CheckoutInvariantError("PAYMENT_PROVIDER_UNAVAILABLE")
    provider = _provider(payment.provider)
    adapter = _configured_adapters.get(provider)
    return_base = _configured_url("AI_DEVICE_LAB_CHECKOUT_RETURN_URL")
    cancel_base = _configured_url("AI_DEVICE_LAB_CHECKOUT_CANCEL_URL")
    if adapter is None or return_base is None or cancel_base is None:
        raise CheckoutInvariantError("PAYMENT_PROVIDER_UNAVAILABLE")

    campaign = (
        await db.execute(
            select(ServiceCampaign)
            .where(
                ServiceCampaign.org_id == command.org_id,
                ServiceCampaign.id == command.service_campaign_id,
            )
            .with_for_update()
        )
    ).scalar_one()
    order = await create_order(
        db,
        CreateOrder(
            org_id=command.org_id,
            service_campaign_id=campaign.id,
            idempotency_key=_order_idempotency_key(campaign.id),
            created_by=command.actor_id,
            price=PriceSnapshot(
                plan_version=campaign.plan_version,
                pricing_version=payment.pricing_version,
                policy_version=payment.policy_version,
                amount_minor=payment.amount_minor,
                currency=payment.currency,
                quota=payment.quota,
            ),
        ),
    )
    if order.status == "paid":
        intent = await db.scalar(
            select(PaymentIntent).where(
                PaymentIntent.org_id == command.org_id,
                PaymentIntent.order_id == order.id,
            )
        )
        if intent is None:
            raise CheckoutInvariantError("PAID_ORDER_INTENT_MISSING")
        return CheckoutResult(order.id, intent.id, "paid", None, None, None)

    intent = (
        await db.execute(
            select(PaymentIntent)
            .where(
                PaymentIntent.org_id == command.org_id,
                PaymentIntent.order_id == order.id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if intent is None:
        intent = PaymentIntent(
            org_id=command.org_id,
            order_id=order.id,
            provider=provider,
            idempotency_key=command.idempotency_key,
            amount_minor=order.amount_minor,
            currency=order.currency,
            status="dispatching",
            created_at=command.now,
            updated_at=command.now,
        )
        db.add(intent)
        await db.flush()
    elif (
        intent.provider != provider
        or intent.amount_minor != order.amount_minor
        or intent.currency != order.currency
    ):
        raise CheckoutInvariantError("CHECKOUT_INTENT_MISMATCH")
    else:
        intent.status = "dispatching"
        intent.last_error_code = None
        intent.updated_at = command.now
    await db.commit()

    return_url = _callback_url(return_base, campaign_id=campaign.id)
    cancel_url = _callback_url(cancel_base, campaign_id=campaign.id)
    try:
        async with _provider_slots[provider]:
            provider_session = await asyncio.wait_for(
                adapter.create_or_lookup_checkout(
                    order_id=order.id,
                    amount_minor=order.amount_minor,
                    currency=order.currency,
                    idempotency_key=intent.idempotency_key,
                    return_url=return_url,
                    cancel_url=cancel_url,
                ),
                timeout=_checkout_timeout_seconds(),
            )
    except TimeoutError:
        await _mark_uncertain(
            db,
            org_id=command.org_id,
            intent_id=intent.id,
            order_id=order.id,
            provider=provider,
            error_code="CHECKOUT_PROVIDER_TIMEOUT",
            now=command.now,
        )
        return CheckoutResult(
            order.id,
            intent.id,
            "uncertain",
            None,
            None,
            "PAYMENT_RECONCILIATION_PENDING",
        )
    except Exception:  # noqa: BLE001 - provider details must never reach persistence
        await _mark_uncertain(
            db,
            org_id=command.org_id,
            intent_id=intent.id,
            order_id=order.id,
            provider=provider,
            error_code="CHECKOUT_PROVIDER_UNAVAILABLE",
            now=command.now,
        )
        return CheckoutResult(
            order.id,
            intent.id,
            "uncertain",
            None,
            None,
            "PAYMENT_RECONCILIATION_PENDING",
        )

    if not _valid_checkout_session(provider_session, now=command.now):
        await _mark_uncertain(
            db,
            org_id=command.org_id,
            intent_id=intent.id,
            order_id=order.id,
            provider=provider,
            error_code="INVALID_CHECKOUT_PROVIDER_SESSION",
            now=command.now,
        )
        return CheckoutResult(
            order.id,
            intent.id,
            "uncertain",
            None,
            None,
            "PAYMENT_RECONCILIATION_PENDING",
        )

    stored = (
        await db.execute(
            select(PaymentIntent)
            .where(
                PaymentIntent.org_id == command.org_id,
                PaymentIntent.id == intent.id,
            )
            .with_for_update()
        )
    ).scalar_one()
    reference = provider_session.provider_reference.strip()
    if stored.provider_reference is not None and stored.provider_reference != reference:
        stored = await _mark_uncertain(
            db,
            org_id=command.org_id,
            intent_id=stored.id,
            order_id=order.id,
            provider=provider,
            error_code="CHECKOUT_PROVIDER_REFERENCE_CONFLICT",
            now=command.now,
        )
        return CheckoutResult(
            order.id,
            stored.id,
            "uncertain",
            None,
            None,
            "PAYMENT_RECONCILIATION_PENDING",
        )
    stored.provider_reference = reference
    stored.status = "awaiting_payment"
    stored.last_error_code = None
    stored.checkout_expires_at = provider_session.expires_at
    stored.updated_at = command.now
    await db.commit()
    return CheckoutResult(
        order.id,
        stored.id,
        stored.status,
        provider_session.checkout_url,
        provider_session.expires_at,
        None,
    )
