"""Durable, provider-neutral reconciliation for uncertain payment state."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models.ai_device_lab_billing import (
    PaymentEvent,
    PaymentIntent,
    PaymentReconciliationJob,
    ServiceOrder,
)
from services.ai_device_lab.billing import AcceptPaymentEvent, accept_payment_event
from tenancy.context import tenant_context

log = logging.getLogger(__name__)

_SYMBOLIC_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,127}")
_PROVIDER_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}")
_SNAPSHOT_STATES = frozenset({"pending", "paid", "failed", "refunded"})


class PaymentReconciliationInvariantError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PaymentProviderSnapshot:
    state: str
    version: str
    observed_at: datetime
    amount_minor: int
    currency: str


class PaymentReconciliationAdapter(Protocol):
    async def fetch_payment(
        self,
        *,
        provider_reference: str | None,
        idempotency_key: str,
    ) -> PaymentProviderSnapshot: ...


@dataclass(frozen=True, slots=True)
class ClaimedPaymentReconciliation:
    id: str
    org_id: str
    order_id: str
    provider: str
    provider_reference: str | None
    provider_lookup_key: str | None
    idempotency_key: str
    lease_token: str
    attempt: int


@dataclass(frozen=True, slots=True)
class PaymentReconciliationBatchResult:
    claimed: int
    resolved: int
    retry_scheduled: int
    blocked: int
    dead_lettered: int
    stale_acknowledgements: int


_configured_adapters: dict[str, PaymentReconciliationAdapter] = {}


def configure_payment_reconciliation_adapter(
    provider: str,
    adapter: PaymentReconciliationAdapter | None,
) -> None:
    normalized = provider.strip().lower()
    if _PROVIDER_NAME.fullmatch(normalized) is None:
        raise PaymentReconciliationInvariantError("invalid payment provider name")
    if adapter is None:
        _configured_adapters.pop(normalized, None)
    else:
        _configured_adapters[normalized] = adapter


def _symbolic_code(value: str, *, field: str) -> str:
    normalized = value.strip().upper()
    if _SYMBOLIC_CODE.fullmatch(normalized) is None:
        raise PaymentReconciliationInvariantError(f"{field} must be a symbolic code")
    return normalized


async def enqueue_payment_reconciliation(
    db: AsyncSession,
    *,
    org_id: str,
    order_id: str,
    provider: str,
    reason_code: str,
    idempotency_key: str,
    provider_lookup_key: str | None = None,
    now: datetime | None = None,
) -> PaymentReconciliationJob:
    normalized_provider = provider.strip().lower()
    if _PROVIDER_NAME.fullmatch(normalized_provider) is None:
        raise PaymentReconciliationInvariantError("invalid payment provider name")
    normalized_reason = _symbolic_code(reason_code, field="reason_code")
    if not 1 <= len(idempotency_key) <= 128:
        raise PaymentReconciliationInvariantError(
            "idempotency_key must contain 1..128 characters"
        )
    existing = (
        await db.execute(
            select(PaymentReconciliationJob).where(
                PaymentReconciliationJob.org_id == org_id,
                PaymentReconciliationJob.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.order_id != order_id
            or existing.provider != normalized_provider
            or existing.reason_code != normalized_reason
            or (
                provider_lookup_key is not None
                and existing.provider_lookup_key != provider_lookup_key
            )
        ):
            raise PaymentReconciliationInvariantError(
                "reconciliation idempotency key was reused with different input"
            )
        return existing

    order = (
        await db.execute(
            select(ServiceOrder).where(
                ServiceOrder.id == order_id,
                ServiceOrder.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if order is None:
        raise PaymentReconciliationInvariantError("order not found")
    intent = (
        await db.execute(
            select(PaymentIntent)
            .where(
                PaymentIntent.org_id == org_id,
                PaymentIntent.order_id == order_id,
                PaymentIntent.provider == normalized_provider,
            )
            .order_by(PaymentIntent.created_at.desc(), PaymentIntent.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    job = PaymentReconciliationJob(
        org_id=org_id,
        order_id=order_id,
        provider=normalized_provider,
        provider_reference=intent.provider_reference if intent else None,
        provider_lookup_key=(
            provider_lookup_key
            if provider_lookup_key is not None
            else (intent.idempotency_key if intent else None)
        ),
        reason_code=normalized_reason,
        idempotency_key=idempotency_key,
        status="pending",
        available_at=now or datetime.now(UTC),
    )
    db.add(job)
    await db.flush()
    return job


async def enqueue_payment_event_reconciliation(
    db: AsyncSession,
    *,
    event: PaymentEvent,
    reason_code: str,
) -> PaymentReconciliationJob:
    digest = hashlib.sha256(
        f"{event.provider}\0{event.provider_event_id}".encode()
    ).hexdigest()
    return await enqueue_payment_reconciliation(
        db,
        org_id=event.org_id,
        order_id=event.order_id,
        provider=event.provider,
        reason_code=reason_code,
        idempotency_key=f"payment-event:{digest}",
        now=event.recorded_at,
    )


async def claim_payment_reconciliation_batch(
    db: AsyncSession,
    *,
    now: datetime,
    limit: int = 100,
    lease_seconds: float = 30,
) -> list[ClaimedPaymentReconciliation]:
    if not 1 <= limit <= 1_000:
        raise PaymentReconciliationInvariantError("limit must be within 1..1000")
    if not 5 <= lease_seconds <= 300:
        raise PaymentReconciliationInvariantError(
            "lease_seconds must be within 5..300"
        )
    rows = list(
        (
            await db.execute(
                select(PaymentReconciliationJob)
                .where(
                    or_(
                        (
                            (PaymentReconciliationJob.status == "pending")
                            & (PaymentReconciliationJob.available_at <= now)
                        ),
                        (
                            (PaymentReconciliationJob.status == "processing")
                            & (PaymentReconciliationJob.lease_until <= now)
                        ),
                    )
                )
                .order_by(
                    PaymentReconciliationJob.available_at,
                    PaymentReconciliationJob.id,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )
    claims: list[ClaimedPaymentReconciliation] = []
    for row in rows:
        token = uuid.uuid4().hex
        row.status = "processing"
        row.lease_token = token
        row.lease_until = now + timedelta(seconds=lease_seconds)
        row.attempts += 1
        claims.append(
            ClaimedPaymentReconciliation(
                id=row.id,
                org_id=row.org_id,
                order_id=row.order_id,
                provider=row.provider,
                provider_reference=row.provider_reference,
                provider_lookup_key=row.provider_lookup_key,
                idempotency_key=row.idempotency_key,
                lease_token=token,
                attempt=row.attempts,
            )
        )
    await db.flush()
    return claims


def _retry_delay_seconds(attempt: int) -> int:
    return min(900, 2 ** max(0, attempt - 1))


async def _fetch_snapshot(
    claim: ClaimedPaymentReconciliation,
    *,
    adapters: Mapping[str, PaymentReconciliationAdapter],
    semaphore: asyncio.Semaphore,
) -> tuple[str, str | PaymentProviderSnapshot]:
    adapter = adapters.get(claim.provider)
    if adapter is None:
        return (
            ("blocked", "PROVIDER_REFERENCE_MISSING")
            if not claim.provider_reference
            else ("blocked", "PROVIDER_ADAPTER_UNAVAILABLE")
        )
    try:
        async with semaphore:
            snapshot = await adapter.fetch_payment(
                provider_reference=claim.provider_reference,
                idempotency_key=(
                    claim.provider_lookup_key
                    if not claim.provider_reference and claim.provider_lookup_key
                    else claim.idempotency_key
                ),
            )
    except Exception:  # noqa: BLE001 - provider details must never reach persistence
        return "retry", "PROVIDER_UNAVAILABLE"
    state = snapshot.state.strip().lower()
    currency = snapshot.currency.strip().upper()
    if (
        state not in _SNAPSHOT_STATES
        or not snapshot.version.strip()
        or len(snapshot.version) > 128
        or snapshot.amount_minor < 0
        or len(currency) != 3
        or not currency.isalpha()
    ):
        return "blocked", "INVALID_PROVIDER_SNAPSHOT"
    normalized = PaymentProviderSnapshot(
        state=state,
        version=snapshot.version.strip(),
        observed_at=snapshot.observed_at,
        amount_minor=snapshot.amount_minor,
        currency=currency,
    )
    if state == "pending":
        return "retry", "PROVIDER_STATE_PENDING"
    return "resolved", normalized


def _reconciliation_event_id(
    claim: ClaimedPaymentReconciliation,
    snapshot: PaymentProviderSnapshot,
) -> str:
    digest = hashlib.sha256(
        f"{claim.provider_reference}\0{snapshot.version}".encode()
    ).hexdigest()
    return f"reconciliation:{digest}"


async def _acknowledge_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    claim: ClaimedPaymentReconciliation,
    outcome: str,
    detail: str | PaymentProviderSnapshot,
    now: datetime,
    max_attempts: int,
) -> str:
    with tenant_context(claim.org_id):
        async with session_factory() as db:
            job = (
                await db.execute(
                    select(PaymentReconciliationJob)
                    .where(
                        PaymentReconciliationJob.id == claim.id,
                        PaymentReconciliationJob.status == "processing",
                        PaymentReconciliationJob.lease_token == claim.lease_token,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if job is None:
                await db.rollback()
                return "stale"
            order = (
                await db.execute(
                    select(ServiceOrder)
                    .where(ServiceOrder.id == claim.order_id)
                    .with_for_update()
                )
            ).scalar_one()

            if outcome == "retry":
                error_code = str(detail)
                if claim.attempt < max_attempts:
                    job.status = "pending"
                    job.available_at = now + timedelta(
                        seconds=_retry_delay_seconds(claim.attempt)
                    )
                    final = "retry"
                else:
                    job.status = "dead_lettered"
                    final = "dead_lettered"
                job.last_error_code = error_code
            elif outcome == "blocked":
                job.status = "blocked"
                job.last_error_code = str(detail)
                final = "blocked"
            else:
                if not isinstance(detail, PaymentProviderSnapshot):
                    raise PaymentReconciliationInvariantError(
                        "resolved reconciliation requires a provider snapshot"
                    )
                snapshot = detail
                if (
                    snapshot.amount_minor != order.amount_minor
                    or snapshot.currency != order.currency
                ):
                    job.status = "blocked"
                    job.last_error_code = "AMOUNT_OR_CURRENCY_MISMATCH"
                    final = "blocked"
                elif snapshot.state in {"paid", "refunded"}:
                    await accept_payment_event(
                        db,
                        AcceptPaymentEvent(
                            org_id=claim.org_id,
                            order_id=order.id,
                            provider=claim.provider,
                            provider_event_id=_reconciliation_event_id(claim, snapshot),
                            event_type=(
                                "payment.settled"
                                if snapshot.state == "paid"
                                else "payment.refunded"
                            ),
                            source_occurred_at=snapshot.observed_at,
                            signature_verified=True,
                            amount_minor=snapshot.amount_minor,
                            currency=snapshot.currency,
                        ),
                    )
                    job.status = "resolved"
                    job.resolved_at = now
                    job.last_error_code = None
                    final = "resolved"
                else:
                    event = PaymentEvent(
                        org_id=claim.org_id,
                        order_id=order.id,
                        provider=claim.provider,
                        provider_event_id=_reconciliation_event_id(claim, snapshot),
                        event_type="payment.failed",
                        amount_minor=snapshot.amount_minor,
                        currency=snapshot.currency,
                        signature_verified=True,
                        source_occurred_at=snapshot.observed_at,
                        processing_state="accepted",
                        reason_code="AUTHORITATIVE_PROVIDER_FAILURE",
                    )
                    db.add(event)
                    if order.status != "refunded":
                        order.status = "failed"
                    job.status = "resolved"
                    job.resolved_at = now
                    job.last_error_code = None
                    final = "resolved"

            job.lease_token = None
            job.lease_until = None
            await db.commit()
            return final


async def run_payment_reconciliation_batch(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    adapters: Mapping[str, PaymentReconciliationAdapter] | None = None,
    now: datetime | None = None,
    batch_size: int = 100,
    concurrency: int = 8,
    lease_seconds: float = 30,
    max_attempts: int = 8,
) -> PaymentReconciliationBatchResult:
    if not 1 <= batch_size <= 1_000:
        raise PaymentReconciliationInvariantError("batch_size must be within 1..1000")
    if not 1 <= concurrency <= 32:
        raise PaymentReconciliationInvariantError("concurrency must be within 1..32")
    if not 1 <= max_attempts <= 100:
        raise PaymentReconciliationInvariantError("max_attempts must be within 1..100")
    observed_at = now or datetime.now(UTC)
    table = PaymentReconciliationJob.__table__
    oldest = func.min(table.c.available_at).label("oldest_available")
    async with session_factory() as discovery_db:
        rows = await discovery_db.execute(
            select(table.c.org_id, oldest)
            .where(
                or_(
                    ((table.c.status == "pending") & (table.c.available_at <= observed_at)),
                    (
                        (table.c.status == "processing")
                        & (table.c.lease_until <= observed_at)
                    ),
                )
            )
            .group_by(table.c.org_id)
            .order_by(oldest, table.c.org_id)
            .limit(min(batch_size, 100))
        )
        org_ids = [str(row[0]) for row in rows]

    claims: list[ClaimedPaymentReconciliation] = []
    for org_id in org_ids:
        remaining = batch_size - len(claims)
        if remaining <= 0:
            break
        with tenant_context(org_id):
            async with session_factory() as db:
                claims.extend(
                    await claim_payment_reconciliation_batch(
                        db,
                        now=observed_at,
                        limit=remaining,
                        lease_seconds=lease_seconds,
                    )
                )
                await db.commit()

    active_adapters = adapters if adapters is not None else _configured_adapters
    provider_slots = asyncio.Semaphore(concurrency)
    fetched = await asyncio.gather(
        *(
            _fetch_snapshot(
                claim,
                adapters=active_adapters,
                semaphore=provider_slots,
            )
            for claim in claims
        )
    )
    ack_slots = asyncio.Semaphore(concurrency)

    async def acknowledge(
        claim: ClaimedPaymentReconciliation,
        outcome: str,
        detail: str | PaymentProviderSnapshot,
    ) -> str:
        async with ack_slots:
            return await _acknowledge_snapshot(
                session_factory,
                claim=claim,
                outcome=outcome,
                detail=detail,
                now=observed_at,
                max_attempts=max_attempts,
            )

    acknowledged = await asyncio.gather(
        *(
            acknowledge(claim, outcome, detail)
            for claim, (outcome, detail) in zip(claims, fetched, strict=True)
        )
    )
    return PaymentReconciliationBatchResult(
        claimed=len(claims),
        resolved=acknowledged.count("resolved"),
        retry_scheduled=acknowledged.count("retry"),
        blocked=acknowledged.count("blocked"),
        dead_lettered=acknowledged.count("dead_lettered"),
        stale_acknowledgements=acknowledged.count("stale"),
    )


def payment_reconciliation_interval_seconds() -> float:
    raw = os.getenv("AI_DEVICE_LAB_PAYMENT_RECONCILIATION_INTERVAL_SECONDS", "5")
    try:
        return max(1.0, min(300.0, float(raw)))
    except ValueError:
        return 5.0


async def payment_reconciliation_loop() -> None:
    """Run only after a provider-specific verified adapter is registered."""
    from db import database
    from web.metrics import (
        ai_device_lab_payment_reconciliation_duration_seconds,
        ai_device_lab_payment_reconciliation_jobs_total,
        ai_device_lab_payment_reconciliation_runs_total,
    )

    interval = payment_reconciliation_interval_seconds()
    while True:
        started = time.perf_counter()
        status = "success"
        try:
            if database.schema_init_ok is False:
                status = "schema_unavailable"
            elif not _configured_adapters:
                status = "adapter_unconfigured"
            else:
                result = await run_payment_reconciliation_batch(
                    database.AsyncSessionLocal
                )
                for outcome, count in (
                    ("resolved", result.resolved),
                    ("retry", result.retry_scheduled),
                    ("blocked", result.blocked),
                    ("dead_lettered", result.dead_lettered),
                    ("stale_ack", result.stale_acknowledgements),
                ):
                    if count:
                        ai_device_lab_payment_reconciliation_jobs_total.labels(
                            outcome=outcome
                        ).inc(count)
        except Exception as exc:  # noqa: BLE001 - background worker must survive faults
            status = "error"
            log.warning("AI Device Lab payment reconciliation failed: %s", exc)
        finally:
            ai_device_lab_payment_reconciliation_runs_total.labels(status=status).inc()
            ai_device_lab_payment_reconciliation_duration_seconds.observe(
                time.perf_counter() - started
            )
        await asyncio.sleep(interval)
