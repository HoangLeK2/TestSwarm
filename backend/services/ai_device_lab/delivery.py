"""Transactional farm job outbox and order-independent terminal reducer."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models.ai_device_lab import (
    AppBuild,
    RunAttempt,
    RunSlot,
    ScenarioApproval,
    ServiceCampaign,
)
from db.models.ai_device_lab_delivery import FarmEventInbox, FarmJob, FarmJobOutbox
from db.models.ai_device_lab_fleet import DeviceReservation
from db.models.execution import Execution
from services.ai_device_lab.service_campaigns import AllocateRunAttempt, allocate_run_attempt
from services.operation_policy import OperationPolicy
from tenancy.context import tenant_context

log = logging.getLogger(__name__)

SUPPORTED_FARM_JOB_SCHEMA_VERSIONS = frozenset({"adl-farm-job-v1"})
SUPPORTED_FARM_EVENT_SCHEMA_VERSIONS = frozenset({"adl-farm-event-v1"})
NON_RETRYABLE_DELIVERY_CODES = frozenset({"FALLBACK_DISPATCH_UNCERTAIN"})
TERMINAL_RUN_ATTEMPT_STATES = frozenset({"passed", "failed", "blocked", "cancelled"})
MAX_FARM_EVENTS_PER_JOB = 2_000
MAX_FARM_EVENT_BYTES = 65_536
MAX_FARM_ARTIFACT_REF_BYTES = 1_024


class DeliveryInvariantError(ValueError):
    pass


class FarmDeliveryError(RuntimeError):
    def __init__(self, code: str) -> None:
        normalized = code.strip().upper()
        if re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", normalized) is None:
            raise ValueError("farm delivery error code must be a safe symbolic code")
        self.code = normalized
        super().__init__(normalized)


class FarmJobSink(Protocol):
    async def deliver(self, payload: dict) -> None: ...


@dataclass(frozen=True, slots=True)
class ClaimedFarmJob:
    outbox_id: str
    org_id: str
    job_id: str
    lease_token: str
    delivery_attempt: int
    job_status: str
    schema_version: str
    deadline_at: datetime
    payload: dict


@dataclass(frozen=True, slots=True)
class FarmDeliveryBatchResult:
    claimed: int
    delivered: int
    reconciled: int
    cancelled: int
    retry_scheduled: int
    dead_lettered: int
    stale_acknowledgements: int


_configured_farm_job_sink: FarmJobSink | None = None


def configure_farm_job_sink(sink: FarmJobSink | None) -> None:
    """Attach the existing runtime/relay adapter without importing it here."""
    global _configured_farm_job_sink
    _configured_farm_job_sink = sink


@dataclass(frozen=True, slots=True)
class CreateFarmJob:
    org_id: str
    run_attempt_id: str
    reservation_id: str
    approval_id: str
    idempotency_key: str
    deadline_at: datetime
    active_policy: OperationPolicy
    secret_capability_ref: str | None = None


@dataclass(frozen=True, slots=True)
class CreateFarmRun:
    org_id: str
    service_campaign_id: str
    lane_id: str
    slot_id: str
    execution_id: str
    scenario_version_id: str
    app_build_id: str
    reservation_id: str
    approval_id: str
    idempotency_key: str
    deadline_at: datetime
    reason: str = "scheduled"


@dataclass(frozen=True, slots=True)
class AcceptFarmEvent:
    org_id: str
    job_id: str
    schema_version: str
    execution_id: str
    source: str
    event_id: str
    event_type: str
    occurred_at: datetime
    sequence: int | None = None
    reason_code: str | None = None
    assertion_passed: bool | None = None
    step_path: str | None = None
    step_attempt_index: int | None = None
    artifact_refs: tuple[str, ...] = ()


def _validate_farm_event(command: AcceptFarmEvent, job: FarmJob) -> None:
    if command.schema_version not in SUPPORTED_FARM_EVENT_SCHEMA_VERSIONS:
        raise DeliveryInvariantError("unsupported farm event schema version")
    expected_execution_id = job.payload.get("execution_id")
    if command.execution_id != expected_execution_id:
        raise DeliveryInvariantError("farm event execution does not match job")
    if len(command.source.encode("utf-8")) > 64 or len(command.event_id.encode("utf-8")) > 128:
        raise DeliveryInvariantError("farm event identity exceeds contract limit")
    if len(command.artifact_refs) > 100 or any(
        not ref or len(ref.encode("utf-8")) > MAX_FARM_ARTIFACT_REF_BYTES
        for ref in command.artifact_refs
    ):
        raise DeliveryInvariantError("farm event artifact reference exceeds contract limit")
    encoded = json.dumps(
        {
            "schema_version": command.schema_version,
            "execution_id": command.execution_id,
            "source": command.source,
            "event_id": command.event_id,
            "event_type": command.event_type,
            "occurred_at": _utc(command.occurred_at).isoformat(),
            "sequence": command.sequence,
            "reason_code": command.reason_code,
            "assertion_passed": command.assertion_passed,
            "step_path": command.step_path,
            "step_attempt_index": command.step_attempt_index,
            "artifact_refs": command.artifact_refs,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_FARM_EVENT_BYTES:
        raise DeliveryInvariantError("farm event exceeds 64 KiB")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def create_farm_run(
    db: AsyncSession,
    command: CreateFarmRun,
) -> tuple[RunAttempt, FarmJob]:
    """Atomically allocate a run attempt and its durable delivery intent."""
    campaign = await db.scalar(
        select(ServiceCampaign).where(
            ServiceCampaign.id == command.service_campaign_id,
            ServiceCampaign.org_id == command.org_id,
        )
    )
    approval = await db.scalar(
        select(ScenarioApproval).where(
            ScenarioApproval.id == command.approval_id,
            ScenarioApproval.org_id == command.org_id,
            ScenarioApproval.scenario_version_id == command.scenario_version_id,
        )
    )
    build = await db.scalar(
        select(AppBuild).where(
            AppBuild.id == command.app_build_id,
            AppBuild.org_id == command.org_id,
        )
    )
    execution = await db.scalar(
        select(Execution).where(
            Execution.id == command.execution_id,
            Execution.org_id == command.org_id,
        )
    )
    reservation = await db.scalar(
        select(DeviceReservation).where(
            DeviceReservation.id == command.reservation_id,
            DeviceReservation.org_id == command.org_id,
            DeviceReservation.state == "active",
        )
    )
    if None in (campaign, approval, build, execution, reservation):
        raise DeliveryInvariantError("farm run references are outside organization scope")
    if (
        campaign.package_name != approval.package_name
        or build.package_name != campaign.package_name
        or execution.campaign_id != campaign.runtime_campaign_id
        or execution.scenario_version_id != command.scenario_version_id
        or reservation.service_campaign_id != campaign.id
        or reservation.lane_id != command.lane_id
    ):
        raise DeliveryInvariantError("farm run references do not describe one approved run")
    if _utc(command.deadline_at) <= datetime.now(UTC):
        raise DeliveryInvariantError("farm run deadline must be in the future")

    attempt = await allocate_run_attempt(
        db,
        AllocateRunAttempt(
            org_id=command.org_id,
            service_campaign_id=command.service_campaign_id,
            lane_id=command.lane_id,
            slot_id=command.slot_id,
            execution_id=command.execution_id,
            scenario_version_id=command.scenario_version_id,
            app_build_id=command.app_build_id,
            idempotency_key=command.idempotency_key,
            reason=command.reason,
        ),
    )
    policy = OperationPolicy(
        version=approval.policy_version,
        app_package=approval.package_name,
        allowed_actions=frozenset(approval.allowed_operations),
        allowed_targets=frozenset({approval.package_name}),
    )
    job = await create_farm_job(
        db,
        CreateFarmJob(
            org_id=command.org_id,
            run_attempt_id=attempt.id,
            reservation_id=command.reservation_id,
            approval_id=command.approval_id,
            idempotency_key=command.idempotency_key,
            deadline_at=command.deadline_at,
            active_policy=policy,
        ),
    )
    return attempt, job


async def create_farm_job(db: AsyncSession, command: CreateFarmJob) -> FarmJob:
    existing = (
        await db.execute(
            select(FarmJob).where(
                FarmJob.org_id == command.org_id,
                FarmJob.idempotency_key == command.idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.run_attempt_id != command.run_attempt_id
            or existing.reservation_id != command.reservation_id
            or existing.scenario_approval_id != command.approval_id
            or _utc(existing.deadline_at) != _utc(command.deadline_at)
            or existing.payload.get("policy_version") != command.active_policy.version
            or existing.payload.get("package_name") != command.active_policy.app_package
            or existing.payload.get("secret_capability_ref") != command.secret_capability_ref
        ):
            raise DeliveryInvariantError("farm job idempotency key was reused with different input")
        return existing
    attempt = (
        await db.execute(
            select(RunAttempt).where(
                RunAttempt.id == command.run_attempt_id,
                RunAttempt.org_id == command.org_id,
            )
        )
    ).scalar_one_or_none()
    reservation = (
        await db.execute(
            select(DeviceReservation).where(
                DeviceReservation.id == command.reservation_id,
                DeviceReservation.org_id == command.org_id,
                DeviceReservation.state == "active",
            )
        )
    ).scalar_one_or_none()
    approval = (
        await db.execute(
            select(ScenarioApproval).where(
                ScenarioApproval.id == command.approval_id,
                ScenarioApproval.org_id == command.org_id,
                ScenarioApproval.policy_version == command.active_policy.version,
            )
        )
    ).scalar_one_or_none()
    if attempt is None or reservation is None or approval is None:
        raise DeliveryInvariantError("attempt, reservation, and approval must be active and scoped")
    if (
        attempt.service_campaign_id != reservation.service_campaign_id
        or attempt.lane_id != reservation.lane_id
        or attempt.scenario_version_id != approval.scenario_version_id
        or approval.package_name != command.active_policy.app_package
    ):
        raise DeliveryInvariantError("delivery references do not describe one approved lane run")
    payload = {
        "schema_version": "adl-farm-job-v1",
        "org_id": command.org_id,
        "service_campaign_id": attempt.service_campaign_id,
        "lane_id": attempt.lane_id,
        "slot_id": attempt.slot_id,
        "run_attempt_id": attempt.id,
        "execution_id": attempt.execution_id,
        "device_id": reservation.device_id,
        "reservation_id": reservation.id,
        "app_build_id": attempt.app_build_id,
        "scenario_version_id": attempt.scenario_version_id,
        "scenario_hash": approval.content_hash,
        "policy_version": approval.policy_version,
        "allowed_operations": approval.allowed_operations,
        "package_name": approval.package_name,
        "deadline_at": command.deadline_at.isoformat(),
        "idempotency_key": command.idempotency_key,
        "secret_capability_ref": command.secret_capability_ref,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 65536:
        raise DeliveryInvariantError("farm job payload exceeds 64 KiB")
    job = FarmJob(
        org_id=command.org_id,
        run_attempt_id=attempt.id,
        reservation_id=reservation.id,
        scenario_approval_id=approval.id,
        schema_version="adl-farm-job-v1",
        idempotency_key=command.idempotency_key,
        device_id=reservation.device_id,
        deadline_at=command.deadline_at,
        payload=payload,
        status="pending",
    )
    db.add(job)
    await db.flush()
    db.add(
        FarmJobOutbox(
            org_id=command.org_id,
            job_id=job.id,
            status="pending",
            available_at=datetime.now(command.deadline_at.tzinfo),
        )
    )
    await db.flush()
    return job


async def claim_farm_job_delivery_batch(
    db: AsyncSession,
    *,
    now: datetime,
    limit: int = 100,
    lease_seconds: float = 30,
) -> list[ClaimedFarmJob]:
    """Fence a tenant-scoped batch before any external delivery is attempted."""
    if not 1 <= limit <= 1_000:
        raise DeliveryInvariantError("limit must be between 1 and 1000")
    if not 5 <= lease_seconds <= 300:
        raise DeliveryInvariantError("lease_seconds must be between 5 and 300")

    rows = list(
        (
            await db.execute(
                select(FarmJobOutbox, FarmJob)
                .join(FarmJob, FarmJob.id == FarmJobOutbox.job_id)
                .where(
                    or_(
                        (
                            (FarmJobOutbox.status == "pending")
                            & (FarmJobOutbox.available_at <= now)
                        ),
                        (
                            (FarmJobOutbox.status == "delivering")
                            & (FarmJobOutbox.lease_until <= now)
                        ),
                    )
                )
                .order_by(FarmJobOutbox.available_at, FarmJobOutbox.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    claimed: list[ClaimedFarmJob] = []
    for outbox, job in rows:
        token = uuid.uuid4().hex
        outbox.status = "delivering"
        outbox.lease_token = token
        outbox.lease_until = now + timedelta(seconds=lease_seconds)
        outbox.delivery_attempts += 1
        claimed.append(
            ClaimedFarmJob(
                outbox_id=outbox.id,
                org_id=outbox.org_id,
                job_id=job.id,
                lease_token=token,
                delivery_attempt=outbox.delivery_attempts,
                job_status=job.status,
                schema_version=job.schema_version,
                deadline_at=job.deadline_at,
                payload=dict(job.payload),
            )
        )
    await db.flush()
    return claimed


def _retry_delay_seconds(delivery_attempt: int) -> int:
    return min(300, 2 ** max(0, delivery_attempt - 1))


async def _deliver_claim(
    claim: ClaimedFarmJob,
    *,
    sink: FarmJobSink,
    now: datetime,
    semaphore: asyncio.Semaphore,
) -> tuple[str, str | None]:
    if claim.job_status in {"running", "dispatched", "succeeded"}:
        return "reconciled", None
    if claim.job_status in {"cancelled", "blocked", "failed"}:
        return "cancelled", f"JOB_{claim.job_status.upper()}"
    if claim.job_status != "pending":
        return "dead_lettered", "UNSUPPORTED_JOB_STATUS"
    if claim.schema_version not in SUPPORTED_FARM_JOB_SCHEMA_VERSIONS:
        return "dead_lettered", "UNSUPPORTED_SCHEMA_VERSION"
    if _utc(claim.deadline_at) <= _utc(now):
        return "dead_lettered", "DEADLINE_EXCEEDED"
    try:
        async with semaphore:
            await sink.deliver(dict(claim.payload))
    except FarmDeliveryError as exc:
        if exc.code in NON_RETRYABLE_DELIVERY_CODES:
            return "dead_lettered", exc.code
        return "failed", exc.code
    except Exception:  # noqa: BLE001 - adapters expose a safe code, never raw details
        return "failed", "DELIVERY_ERROR"
    return "delivered", None


async def _acknowledge_farm_delivery(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    claim: ClaimedFarmJob,
    outcome: str,
    error_code: str | None,
    now: datetime,
    max_attempts: int,
) -> str:
    with tenant_context(claim.org_id):
        async with session_factory() as db:
            outbox = (
                await db.execute(
                    select(FarmJobOutbox)
                    .where(
                        FarmJobOutbox.id == claim.outbox_id,
                        FarmJobOutbox.status == "delivering",
                        FarmJobOutbox.lease_token == claim.lease_token,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if outbox is None:
                await db.rollback()
                return "stale"
            job = (
                await db.execute(
                    select(FarmJob)
                    .where(FarmJob.id == claim.job_id)
                    .with_for_update()
                )
            ).scalar_one()

            final_outcome = outcome
            if outcome == "failed" and claim.delivery_attempt < max_attempts:
                final_outcome = "retry"
                outbox.status = "pending"
                outbox.available_at = now + timedelta(
                    seconds=_retry_delay_seconds(claim.delivery_attempt)
                )
            elif outcome == "failed":
                final_outcome = "dead_lettered"
                outbox.status = "dead_lettered"
                job.status = "blocked"
                job.verdict = "inconclusive"
                job.terminal_reason = error_code or "DELIVERY_EXHAUSTED"
            elif outcome == "dead_lettered":
                outbox.status = "dead_lettered"
                job.status = "blocked"
                job.verdict = "inconclusive"
                job.terminal_reason = error_code
            elif outcome == "cancelled":
                outbox.status = "cancelled"
            elif outcome == "reconciled":
                outbox.status = "delivered"
                outbox.delivered_at = now
            else:
                outbox.status = "delivered"
                outbox.delivered_at = now
                if job.status == "pending":
                    job.status = "dispatched"

            outbox.last_error_code = error_code
            outbox.lease_token = None
            outbox.lease_until = None
            await db.commit()
            return final_outcome


async def run_farm_delivery_batch(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    sink: FarmJobSink,
    now: datetime | None = None,
    batch_size: int = 100,
    delivery_concurrency: int = 8,
    lease_seconds: float = 30,
    max_attempts: int = 8,
) -> FarmDeliveryBatchResult:
    """Claim globally, deliver without a DB connection, then fenced-ack by tenant."""
    if not 1 <= batch_size <= 1_000:
        raise DeliveryInvariantError("batch_size must be between 1 and 1000")
    if not 1 <= delivery_concurrency <= 32:
        raise DeliveryInvariantError("delivery_concurrency must be between 1 and 32")
    if not 1 <= max_attempts <= 100:
        raise DeliveryInvariantError("max_attempts must be between 1 and 100")

    observed_at = now or datetime.now(UTC)
    async with session_factory() as discovery_db:
        outbox_table = FarmJobOutbox.__table__
        oldest_available = func.min(outbox_table.c.available_at).label(
            "oldest_available"
        )
        org_result = await discovery_db.execute(
            select(outbox_table.c.org_id, oldest_available)
            .where(
                or_(
                    (
                        (outbox_table.c.status == "pending")
                        & (outbox_table.c.available_at <= observed_at)
                    ),
                    (
                        (outbox_table.c.status == "delivering")
                        & (outbox_table.c.lease_until <= observed_at)
                    ),
                )
            )
            .group_by(outbox_table.c.org_id)
            .order_by(oldest_available, outbox_table.c.org_id)
            .limit(min(batch_size, 100))
        )
        org_ids = [str(row[0]) for row in org_result]

    claims: list[ClaimedFarmJob] = []
    for org_id in org_ids:
        remaining = batch_size - len(claims)
        if remaining <= 0:
            break
        with tenant_context(org_id):
            async with session_factory() as db:
                claims.extend(
                    await claim_farm_job_delivery_batch(
                        db,
                        now=observed_at,
                        limit=remaining,
                        lease_seconds=lease_seconds,
                    )
                )
                await db.commit()

    semaphore = asyncio.Semaphore(delivery_concurrency)
    delivery_outcomes = await asyncio.gather(
        *(
            _deliver_claim(
                claim,
                sink=sink,
                now=observed_at,
                semaphore=semaphore,
            )
            for claim in claims
        )
    )
    acknowledgement_slots = asyncio.Semaphore(delivery_concurrency)

    async def acknowledge(
        claim: ClaimedFarmJob,
        outcome: str,
        error_code: str | None,
    ) -> str:
        async with acknowledgement_slots:
            return await _acknowledge_farm_delivery(
                session_factory,
                claim=claim,
                outcome=outcome,
                error_code=error_code,
                now=observed_at,
                max_attempts=max_attempts,
            )

    acknowledged = await asyncio.gather(
        *(
            acknowledge(claim, outcome, error_code)
            for claim, (outcome, error_code) in zip(
                claims, delivery_outcomes, strict=True
            )
        )
    )
    return FarmDeliveryBatchResult(
        claimed=len(claims),
        delivered=acknowledged.count("delivered"),
        reconciled=acknowledged.count("reconciled"),
        cancelled=acknowledged.count("cancelled"),
        retry_scheduled=acknowledged.count("retry"),
        dead_lettered=acknowledged.count("dead_lettered"),
        stale_acknowledgements=acknowledged.count("stale"),
    )


def farm_delivery_interval_seconds() -> float:
    raw = os.getenv("AI_DEVICE_LAB_FARM_DELIVERY_INTERVAL_SECONDS", "1")
    try:
        return max(0.25, min(60.0, float(raw)))
    except ValueError:
        return 1.0


async def farm_delivery_loop() -> None:
    """Lifecycle worker; remains fail-closed until the runtime registers a sink."""
    from db import database
    from web.metrics import (
        ai_device_lab_farm_delivery_duration_seconds,
        ai_device_lab_farm_delivery_jobs_total,
        ai_device_lab_farm_delivery_runs_total,
    )

    interval = farm_delivery_interval_seconds()
    while True:
        started = time.perf_counter()
        status = "success"
        try:
            if database.schema_init_ok is False:
                status = "schema_unavailable"
            elif _configured_farm_job_sink is None:
                status = "adapter_unconfigured"
            else:
                result = await run_farm_delivery_batch(
                    database.AsyncSessionLocal,
                    sink=_configured_farm_job_sink,
                )
                for outcome, count in (
                    ("delivered", result.delivered),
                    ("reconciled", result.reconciled),
                    ("cancelled", result.cancelled),
                    ("retry", result.retry_scheduled),
                    ("dead_lettered", result.dead_lettered),
                    ("stale_ack", result.stale_acknowledgements),
                ):
                    if count:
                        ai_device_lab_farm_delivery_jobs_total.labels(
                            outcome=outcome
                        ).inc(count)
        except Exception as exc:  # noqa: BLE001 - worker must survive transient faults
            status = "error"
            log.warning("AI Device Lab farm delivery pass failed: %s", exc)
        finally:
            ai_device_lab_farm_delivery_runs_total.labels(status=status).inc()
            ai_device_lab_farm_delivery_duration_seconds.observe(
                time.perf_counter() - started
            )
        await asyncio.sleep(interval)


def _reduce_events(events: list[FarmEventInbox]) -> tuple[str, str | None, str | None]:
    if any(event.event_type == "cancelled" for event in events):
        return "cancelled", "inconclusive", "CANCELLED"
    failed = next(
        (event for event in events if event.event_type == "assertion" and event.assertion_passed is False),
        None,
    )
    if failed is not None:
        return "failed", "fail", failed.reason_code or "ASSERTION_FAILED"
    blocked = next(
        (event for event in events if event.event_type in {"blocked", "uncertain", "deadline"}),
        None,
    )
    if blocked is not None:
        return "blocked", "inconclusive", blocked.reason_code or blocked.event_type.upper()
    if any(event.event_type == "completed" and event.assertion_passed is True for event in events):
        return "succeeded", "pass", "ASSERTIONS_PASSED"
    if any(event.event_type in {"accepted", "running", "step"} for event in events):
        return "running", None, None
    return "pending", None, None


async def accept_farm_event(
    db: AsyncSession,
    command: AcceptFarmEvent,
) -> tuple[FarmEventInbox, FarmJob]:
    duplicate_row = (
        await db.execute(
            select(FarmEventInbox.__table__).where(
                FarmEventInbox.__table__.c.source == command.source,
                FarmEventInbox.__table__.c.event_id == command.event_id,
            )
        )
    ).mappings().one_or_none()
    job = (
        await db.execute(
            select(FarmJob)
            .where(FarmJob.id == command.job_id, FarmJob.org_id == command.org_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if job is None:
        raise DeliveryInvariantError("job not found")
    _validate_farm_event(command, job)
    if duplicate_row is not None:
        if (
            duplicate_row["org_id"] != command.org_id
            or duplicate_row["job_id"] != command.job_id
            or duplicate_row["schema_version"] != command.schema_version
            or duplicate_row["execution_id"] != command.execution_id
            or duplicate_row["sequence"] != command.sequence
            or duplicate_row["event_type"] != command.event_type
            or duplicate_row["reason_code"] != command.reason_code
            or duplicate_row["assertion_passed"] != command.assertion_passed
            or duplicate_row["step_path"] != command.step_path
            or duplicate_row["step_attempt_index"] != command.step_attempt_index
            or duplicate_row["artifact_refs"] != list(command.artifact_refs)
            or _utc(duplicate_row["occurred_at"]) != _utc(command.occurred_at)
        ):
            raise DeliveryInvariantError("farm event id was reused with different input")
        duplicate = await db.get(FarmEventInbox, duplicate_row["id"])
        if duplicate is None:
            raise DeliveryInvariantError("farm event is outside tenant scope")
    else:
        event_count = await db.scalar(
            select(func.count()).select_from(FarmEventInbox).where(
                FarmEventInbox.job_id == job.id
            )
        )
        if int(event_count or 0) >= MAX_FARM_EVENTS_PER_JOB:
            raise DeliveryInvariantError("farm event limit reached")
        duplicate = FarmEventInbox(
            org_id=command.org_id,
            job_id=job.id,
            schema_version=command.schema_version,
            execution_id=command.execution_id,
            source=command.source,
            event_id=command.event_id,
            sequence=command.sequence,
            event_type=command.event_type,
            reason_code=command.reason_code,
            assertion_passed=command.assertion_passed,
            step_path=command.step_path,
            step_attempt_index=command.step_attempt_index,
            artifact_refs=list(command.artifact_refs),
            occurred_at=command.occurred_at,
        )
        db.add(duplicate)
        await db.flush()
    terminal_events = list(
        (
            await db.execute(
                select(FarmEventInbox).where(
                    FarmEventInbox.job_id == job.id,
                    FarmEventInbox.event_type.in_(
                        {"assertion", "uncertain", "blocked", "deadline", "cancelled", "completed"}
                    ),
                )
            )
        ).scalars()
    )
    job.status, job.verdict, job.terminal_reason = _reduce_events(terminal_events)
    if job.status == "pending":
        job.status = "running"
    attempt = await db.scalar(
        select(RunAttempt)
        .where(
            RunAttempt.id == job.run_attempt_id,
            RunAttempt.org_id == command.org_id,
        )
        .with_for_update()
    )
    if attempt is not None:
        slot = await db.scalar(
            select(RunSlot)
            .where(
                RunSlot.id == attempt.slot_id,
                RunSlot.org_id == command.org_id,
            )
            .with_for_update()
        )
        now = datetime.now(UTC)
        terminal = {
            "succeeded": ("passed", "pass", "completed", "pass"),
            "failed": ("failed", "fail", "failed", "fail"),
            "blocked": ("blocked", "inconclusive", "blocked", "inconclusive"),
            "cancelled": ("cancelled", "inconclusive", "cancelled", "inconclusive"),
        }.get(job.status)
        if terminal is not None:
            attempt.status, attempt.outcome, slot_status, app_verdict = terminal
            attempt.failure_reason = (
                None if job.status == "succeeded" else job.terminal_reason
            )
            attempt.finished_at = attempt.finished_at or now
            if slot is not None:
                slot.execution_status = slot_status
                slot.app_verdict = app_verdict
        elif job.status == "running":
            if attempt.status not in TERMINAL_RUN_ATTEMPT_STATES:
                attempt.status = "running"
                attempt.started_at = attempt.started_at or now
            if slot is not None and slot.execution_status not in {
                "completed",
                "failed",
                "blocked",
                "cancelled",
            }:
                slot.execution_status = "running"
    await db.flush()
    return duplicate, job
