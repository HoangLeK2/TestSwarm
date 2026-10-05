"""Idempotent refund request and fenced provider dispatch."""

from __future__ import annotations

import asyncio
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
    PaymentIntent,
    RefundDispatchJob,
    ServiceOrder,
    ServiceRefund,
)
from services.ai_device_lab.billing_reconciliation import (
    enqueue_payment_reconciliation,
)
from tenancy.context import tenant_context

log = logging.getLogger(__name__)

_PROVIDER_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}")
_SYMBOLIC_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,127}")
_RECEIPT_STATES = frozenset({"accepted", "succeeded", "rejected"})


class RefundInvariantError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RefundPolicy:
    version: str
    allow_partial: bool
    request_window_seconds: int | None


@dataclass(frozen=True, slots=True)
class RequestRefund:
    org_id: str
    order_id: str
    provider: str
    idempotency_key: str
    amount_minor: int
    reason_code: str
    actor_id: str
    requested_at: datetime
    policy: RefundPolicy


@dataclass(frozen=True, slots=True)
class RefundProviderReceipt:
    state: str
    provider_reference: str | None = None


class RefundProviderAdapter(Protocol):
    async def request_refund(
        self,
        *,
        payment_reference: str,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
        reason_code: str,
    ) -> RefundProviderReceipt: ...


@dataclass(frozen=True, slots=True)
class ClaimedRefundDispatch:
    id: str
    org_id: str
    refund_id: str
    order_id: str
    provider: str
    payment_reference: str | None
    idempotency_key: str
    amount_minor: int
    currency: str
    reason_code: str
    lease_token: str
    attempt: int


@dataclass(frozen=True, slots=True)
class RefundDispatchBatchResult:
    claimed: int
    delivered: int
    retry_scheduled: int
    blocked: int
    dead_lettered: int
    stale_acknowledgements: int


_configured_adapters: dict[str, RefundProviderAdapter] = {}


def configure_refund_provider_adapter(
    provider: str,
    adapter: RefundProviderAdapter | None,
) -> None:
    normalized = _provider(provider)
    if adapter is None:
        _configured_adapters.pop(normalized, None)
    else:
        _configured_adapters[normalized] = adapter


def _provider(value: str) -> str:
    normalized = value.strip().lower()
    if _PROVIDER_NAME.fullmatch(normalized) is None:
        raise RefundInvariantError("invalid refund provider name")
    return normalized


def _reason_code(value: str) -> str:
    normalized = value.strip().upper()
    if _SYMBOLIC_CODE.fullmatch(normalized) is None:
        raise RefundInvariantError("reason_code must be a symbolic code")
    return normalized


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def request_refund(
    db: AsyncSession,
    command: RequestRefund,
) -> tuple[ServiceRefund, RefundDispatchJob]:
    provider = _provider(command.provider)
    reason_code = _reason_code(command.reason_code)
    requested_at = _utc(command.requested_at)
    if not 1 <= len(command.idempotency_key) <= 128:
        raise RefundInvariantError("idempotency_key must contain 1..128 characters")
    if command.amount_minor <= 0:
        raise RefundInvariantError("refund amount must use positive integer minor units")
    if not 1 <= len(command.policy.version) <= 64:
        raise RefundInvariantError("refund policy version must contain 1..64 characters")
    if (
        command.policy.request_window_seconds is not None
        and command.policy.request_window_seconds <= 0
    ):
        raise RefundInvariantError("refund request window must be positive")

    existing = (
        await db.execute(
            select(ServiceRefund, RefundDispatchJob)
            .join(
                RefundDispatchJob,
                (RefundDispatchJob.org_id == ServiceRefund.org_id)
                & (RefundDispatchJob.refund_id == ServiceRefund.id),
            )
            .where(
                ServiceRefund.org_id == command.org_id,
                ServiceRefund.idempotency_key == command.idempotency_key,
            )
        )
    ).one_or_none()
    if existing is not None:
        refund, job = existing
        if (
            refund.order_id != command.order_id
            or refund.amount_minor != command.amount_minor
            or refund.reason != reason_code
            or refund.actor_id != command.actor_id
            or job.provider != provider
        ):
            raise RefundInvariantError(
                "refund idempotency key was reused with different input"
            )
        order_policy = await db.scalar(
            select(ServiceOrder.policy_version).where(
                ServiceOrder.org_id == command.org_id,
                ServiceOrder.id == command.order_id,
            )
        )
        if order_policy != command.policy.version:
            raise RefundInvariantError("refund policy does not match the order snapshot")
        return refund, job

    order = (
        await db.execute(
            select(ServiceOrder)
            .where(
                ServiceOrder.org_id == command.org_id,
                ServiceOrder.id == command.order_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if order is None:
        raise RefundInvariantError("order not found")
    if order.policy_version != command.policy.version:
        raise RefundInvariantError("refund policy does not match the order snapshot")
    if order.status != "paid" or order.paid_at is None:
        raise RefundInvariantError("only a paid order can be refunded")
    if (
        command.policy.request_window_seconds is not None
        and requested_at - _utc(order.paid_at)
        > timedelta(seconds=command.policy.request_window_seconds)
    ):
        raise RefundInvariantError("refund request is outside the policy window")
    if not command.policy.allow_partial and command.amount_minor != order.amount_minor:
        raise RefundInvariantError("the refund policy requires the full order amount")

    allocated = int(
        await db.scalar(
            select(func.coalesce(func.sum(ServiceRefund.amount_minor), 0)).where(
                ServiceRefund.org_id == command.org_id,
                ServiceRefund.order_id == command.order_id,
                ServiceRefund.status.notin_(("failed", "cancelled")),
            )
        )
        or 0
    )
    if allocated + command.amount_minor > order.amount_minor:
        raise RefundInvariantError("refund total exceeds the order amount")

    intent = (
        await db.execute(
            select(PaymentIntent)
            .where(
                PaymentIntent.org_id == command.org_id,
                PaymentIntent.order_id == command.order_id,
                PaymentIntent.provider == provider,
            )
            .order_by(PaymentIntent.created_at.desc(), PaymentIntent.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    refund = ServiceRefund(
        org_id=command.org_id,
        order_id=order.id,
        idempotency_key=command.idempotency_key,
        amount_minor=command.amount_minor,
        reason=reason_code,
        actor_id=command.actor_id,
        status="pending_dispatch",
        created_at=requested_at,
    )
    db.add(refund)
    await db.flush()
    job = RefundDispatchJob(
        org_id=command.org_id,
        refund_id=refund.id,
        order_id=order.id,
        provider=provider,
        payment_reference=intent.provider_reference if intent else None,
        status="pending",
        available_at=requested_at,
        created_at=requested_at,
    )
    db.add(job)
    await db.flush()
    return refund, job


async def claim_refund_dispatch_batch(
    db: AsyncSession,
    *,
    now: datetime,
    limit: int = 100,
    lease_seconds: float = 30,
) -> list[ClaimedRefundDispatch]:
    if not 1 <= limit <= 1_000:
        raise RefundInvariantError("limit must be within 1..1000")
    if not 5 <= lease_seconds <= 300:
        raise RefundInvariantError("lease_seconds must be within 5..300")
    rows = list(
        (
            await db.execute(
                select(RefundDispatchJob, ServiceRefund, ServiceOrder)
                .join(
                    ServiceRefund,
                    (ServiceRefund.org_id == RefundDispatchJob.org_id)
                    & (ServiceRefund.id == RefundDispatchJob.refund_id),
                )
                .join(
                    ServiceOrder,
                    (ServiceOrder.org_id == RefundDispatchJob.org_id)
                    & (ServiceOrder.id == RefundDispatchJob.order_id),
                )
                .where(
                    or_(
                        (
                            (RefundDispatchJob.status == "pending")
                            & (RefundDispatchJob.available_at <= now)
                        ),
                        (
                            (RefundDispatchJob.status == "processing")
                            & (RefundDispatchJob.lease_until <= now)
                        ),
                    )
                )
                .order_by(RefundDispatchJob.available_at, RefundDispatchJob.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    claims: list[ClaimedRefundDispatch] = []
    for job, refund, order in rows:
        token = uuid.uuid4().hex
        job.status = "processing"
        job.lease_token = token
        job.lease_until = now + timedelta(seconds=lease_seconds)
        job.attempts += 1
        claims.append(
            ClaimedRefundDispatch(
                id=job.id,
                org_id=job.org_id,
                refund_id=refund.id,
                order_id=order.id,
                provider=job.provider,
                payment_reference=job.payment_reference,
                idempotency_key=refund.idempotency_key,
                amount_minor=refund.amount_minor,
                currency=order.currency,
                reason_code=refund.reason,
                lease_token=token,
                attempt=job.attempts,
            )
        )
    await db.flush()
    return claims


def _retry_delay_seconds(attempt: int) -> int:
    return min(900, 2 ** max(0, attempt - 1))


async def _dispatch_refund(
    claim: ClaimedRefundDispatch,
    *,
    adapters: Mapping[str, RefundProviderAdapter],
    semaphore: asyncio.Semaphore,
) -> tuple[str, str | RefundProviderReceipt]:
    if not claim.payment_reference:
        return "blocked", "PAYMENT_REFERENCE_MISSING"
    adapter = adapters.get(claim.provider)
    if adapter is None:
        return "blocked", "PROVIDER_ADAPTER_UNAVAILABLE"
    try:
        async with semaphore:
            receipt = await adapter.request_refund(
                payment_reference=claim.payment_reference,
                amount_minor=claim.amount_minor,
                currency=claim.currency,
                idempotency_key=claim.idempotency_key,
                reason_code=claim.reason_code,
            )
    except Exception:  # noqa: BLE001 - provider details must never reach persistence
        return "retry", "PROVIDER_UNAVAILABLE"
    state = receipt.state.strip().lower()
    reference = receipt.provider_reference.strip() if receipt.provider_reference else None
    if state not in _RECEIPT_STATES or (
        reference is not None
        and (not reference or len(reference) > 255 or any(ord(c) < 32 for c in reference))
    ):
        return "blocked", "INVALID_PROVIDER_RECEIPT"
    return "delivered", RefundProviderReceipt(
        state=state,
        provider_reference=reference,
    )


async def _acknowledge_dispatch(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    claim: ClaimedRefundDispatch,
    outcome: str,
    detail: str | RefundProviderReceipt,
    now: datetime,
    max_attempts: int,
) -> str:
    with tenant_context(claim.org_id):
        async with session_factory() as db:
            job = (
                await db.execute(
                    select(RefundDispatchJob)
                    .where(
                        RefundDispatchJob.id == claim.id,
                        RefundDispatchJob.status == "processing",
                        RefundDispatchJob.lease_token == claim.lease_token,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if job is None:
                await db.rollback()
                return "stale"
            refund = (
                await db.execute(
                    select(ServiceRefund)
                    .where(ServiceRefund.id == claim.refund_id)
                    .with_for_update()
                )
            ).scalar_one()

            if outcome == "retry":
                if claim.attempt < max_attempts:
                    job.status = "pending"
                    job.available_at = now + timedelta(
                        seconds=_retry_delay_seconds(claim.attempt)
                    )
                    final = "retry"
                else:
                    job.status = "dead_lettered"
                    refund.status = "dispatch_failed"
                    final = "dead_lettered"
                job.last_error_code = str(detail)
            elif outcome == "blocked":
                job.status = "blocked"
                job.last_error_code = str(detail)
                refund.status = "dispatch_blocked"
                final = "blocked"
            else:
                if not isinstance(detail, RefundProviderReceipt):
                    raise RefundInvariantError(
                        "delivered refund requires a provider receipt"
                    )
                if detail.state == "rejected":
                    job.status = "blocked"
                    job.last_error_code = "PROVIDER_REFUND_REJECTED"
                    refund.status = "failed"
                    final = "blocked"
                else:
                    job.status = "delivered"
                    job.delivered_at = now
                    job.last_error_code = None
                    refund.status = "pending_reconciliation"
                    refund.provider_reference = detail.provider_reference
                    await enqueue_payment_reconciliation(
                        db,
                        org_id=claim.org_id,
                        order_id=claim.order_id,
                        provider=claim.provider,
                        reason_code="REFUND_DISPATCHED",
                        idempotency_key=f"refund:{claim.refund_id}",
                        now=now,
                    )
                    final = "delivered"

            job.lease_token = None
            job.lease_until = None
            await db.commit()
            return final


async def run_refund_dispatch_batch(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    adapters: Mapping[str, RefundProviderAdapter] | None = None,
    now: datetime | None = None,
    batch_size: int = 100,
    concurrency: int = 8,
    lease_seconds: float = 30,
    max_attempts: int = 8,
) -> RefundDispatchBatchResult:
    if not 1 <= batch_size <= 1_000:
        raise RefundInvariantError("batch_size must be within 1..1000")
    if not 1 <= concurrency <= 32:
        raise RefundInvariantError("concurrency must be within 1..32")
    if not 1 <= max_attempts <= 100:
        raise RefundInvariantError("max_attempts must be within 1..100")
    observed_at = now or datetime.now(UTC)
    table = RefundDispatchJob.__table__
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

    claims: list[ClaimedRefundDispatch] = []
    for org_id in org_ids:
        remaining = batch_size - len(claims)
        if remaining <= 0:
            break
        with tenant_context(org_id):
            async with session_factory() as db:
                claims.extend(
                    await claim_refund_dispatch_batch(
                        db,
                        now=observed_at,
                        limit=remaining,
                        lease_seconds=lease_seconds,
                    )
                )
                await db.commit()

    active_adapters = adapters if adapters is not None else _configured_adapters
    provider_slots = asyncio.Semaphore(concurrency)
    dispatched = await asyncio.gather(
        *(
            _dispatch_refund(
                claim,
                adapters=active_adapters,
                semaphore=provider_slots,
            )
            for claim in claims
        )
    )
    ack_slots = asyncio.Semaphore(concurrency)

    async def acknowledge(
        claim: ClaimedRefundDispatch,
        outcome: str,
        detail: str | RefundProviderReceipt,
    ) -> str:
        async with ack_slots:
            return await _acknowledge_dispatch(
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
            for claim, (outcome, detail) in zip(claims, dispatched, strict=True)
        )
    )
    return RefundDispatchBatchResult(
        claimed=len(claims),
        delivered=acknowledged.count("delivered"),
        retry_scheduled=acknowledged.count("retry"),
        blocked=acknowledged.count("blocked"),
        dead_lettered=acknowledged.count("dead_lettered"),
        stale_acknowledgements=acknowledged.count("stale"),
    )


def refund_dispatch_interval_seconds() -> float:
    raw = os.getenv("AI_DEVICE_LAB_REFUND_DISPATCH_INTERVAL_SECONDS", "5")
    try:
        return max(1.0, min(300.0, float(raw)))
    except ValueError:
        return 5.0


async def refund_dispatch_loop() -> None:
    """Run only after a provider-specific refund adapter is registered."""
    from db import database
    from web.metrics import (
        ai_device_lab_refund_dispatch_duration_seconds,
        ai_device_lab_refund_dispatch_jobs_total,
        ai_device_lab_refund_dispatch_runs_total,
    )

    interval = refund_dispatch_interval_seconds()
    while True:
        started = time.perf_counter()
        status = "success"
        try:
            if database.schema_init_ok is False:
                status = "schema_unavailable"
            elif not _configured_adapters:
                status = "adapter_unconfigured"
            else:
                result = await run_refund_dispatch_batch(database.AsyncSessionLocal)
                for outcome, count in (
                    ("delivered", result.delivered),
                    ("retry", result.retry_scheduled),
                    ("blocked", result.blocked),
                    ("dead_lettered", result.dead_lettered),
                    ("stale", result.stale_acknowledgements),
                ):
                    if count:
                        ai_device_lab_refund_dispatch_jobs_total.labels(
                            outcome=outcome
                        ).inc(count)
        except asyncio.CancelledError:
            raise
        except Exception:
            status = "error"
            log.exception("AI Device Lab refund dispatch pass failed")
        finally:
            ai_device_lab_refund_dispatch_runs_total.labels(status=status).inc()
            ai_device_lab_refund_dispatch_duration_seconds.observe(
                time.perf_counter() - started
            )
        await asyncio.sleep(interval)
