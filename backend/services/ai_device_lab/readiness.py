"""Server-derived readiness, atomic start, and 14-day slot materialization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.ai_device_lab import (
    AiLabIntake,
    RunSlot,
    ScenarioApproval,
    ScenarioGenerationOperation,
    ServiceCampaign,
    ServiceLane,
)
from db.models.ai_device_lab_billing import ServiceEntitlement
from db.models.ai_device_lab_fleet import DeviceHygieneState, DeviceReservation
from db.models.ai_device_lab_participation import TrackParticipation
from db.models.ai_device_lab_runtime import ReadinessCheck, ReadinessSnapshot, SchedulingIntent
from db.models.ai_device_lab_operations import OperationalReadinessAssessment
from db.models.device import Device
from services.ai_device_lab.funnel import record_server_funnel_event


@dataclass(frozen=True, slots=True)
class ReadinessPolicy:
    version: str
    snapshot_ttl_seconds: int = 60
    device_health_freshness_seconds: int = 120
    require_participation: bool = True
    require_secret: bool = False


@dataclass(frozen=True, slots=True)
class DependencyReadiness:
    secret_ready: bool = False
    secret_source_ref: str | None = None


@dataclass(frozen=True, slots=True)
class StartCampaign:
    org_id: str
    service_campaign_id: str
    idempotency_key: str
    now: datetime
    policy: ReadinessPolicy
    dependencies: DependencyReadiness = DependencyReadiness()


@dataclass(frozen=True, slots=True)
class StartResult:
    started: bool
    campaign: ServiceCampaign
    snapshot: ReadinessSnapshot
    checks: tuple[ReadinessCheck, ...]
    intent: SchedulingIntent | None


def _check(
    *,
    org_id: str,
    snapshot_id: str,
    key: str,
    passed: bool,
    required: bool,
    observed_at: datetime,
    source_type: str,
    source_ref: str | None,
    source_version: str | None,
    owner: str,
    blocked_reason: str,
    next_action: str | None,
) -> ReadinessCheck:
    if not required:
        status, reason = "not_applicable", "NOT_APPLICABLE"
    elif passed:
        status, reason = "required_pass", "PASS"
    else:
        status, reason = "blocked", blocked_reason
    return ReadinessCheck(
        org_id=org_id,
        snapshot_id=snapshot_id,
        check_key=key,
        status=status,
        required=required,
        reason_code=reason,
        observed_at=observed_at,
        source_type=source_type,
        source_ref=source_ref,
        source_version=source_version,
        owner=owner,
        next_action=next_action if status == "blocked" else None,
    )


async def start_campaign(db: AsyncSession, command: StartCampaign) -> StartResult:
    campaign = (
        await db.execute(
            select(ServiceCampaign)
            .where(
                ServiceCampaign.id == command.service_campaign_id,
                ServiceCampaign.org_id == command.org_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if campaign is None:
        raise ValueError("service campaign not found")
    existing_intent = (
        await db.execute(
            select(SchedulingIntent).where(
                SchedulingIntent.org_id == command.org_id,
                SchedulingIntent.service_campaign_id == campaign.id,
                SchedulingIntent.intent_kind == "start",
            )
        )
    ).scalar_one_or_none()

    revision = int(
        await db.scalar(
            select(func.max(ReadinessSnapshot.revision)).where(
                ReadinessSnapshot.org_id == command.org_id,
                ReadinessSnapshot.service_campaign_id == campaign.id,
            )
        )
        or 0
    ) + 1
    snapshot = ReadinessSnapshot(
        org_id=command.org_id,
        service_campaign_id=campaign.id,
        revision=revision,
        policy_version=command.policy.version,
        status="checking",
        observed_at=command.now,
        expires_at=command.now + timedelta(seconds=command.policy.snapshot_ttl_seconds),
    )
    db.add(snapshot)
    await db.flush()

    entitlement = (
        await db.execute(
            select(ServiceEntitlement).where(
                ServiceEntitlement.org_id == command.org_id,
                ServiceEntitlement.service_campaign_id == campaign.id,
                ServiceEntitlement.state == "active",
            )
        )
    ).scalar_one_or_none()
    approval = (
        await db.execute(
            select(ScenarioApproval)
            .join(
                ScenarioGenerationOperation,
                ScenarioGenerationOperation.id == ScenarioApproval.generation_operation_id,
            )
            .join(AiLabIntake, AiLabIntake.id == ScenarioGenerationOperation.intake_id)
            .where(
                ScenarioApproval.org_id == command.org_id,
                AiLabIntake.runtime_campaign_id == campaign.runtime_campaign_id,
                ScenarioGenerationOperation.input_version == AiLabIntake.input_version,
                ScenarioGenerationOperation.input_hash == AiLabIntake.input_hash,
                ScenarioApproval.package_name == campaign.package_name,
            )
            .order_by(ScenarioApproval.approved_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    reservations = list(
        (
            await db.execute(
                select(DeviceReservation).where(
                    DeviceReservation.org_id == command.org_id,
                    DeviceReservation.service_campaign_id == campaign.id,
                    DeviceReservation.state == "active",
                    DeviceReservation.starts_at <= command.now,
                    DeviceReservation.ends_at > command.now,
                )
            )
        )
        .scalars()
        .all()
    )
    reserved_ids = [row.device_id for row in reservations]
    clean_count = 0
    healthy_count = 0
    if reserved_ids:
        clean_count = int(
            await db.scalar(
                select(func.count()).select_from(DeviceHygieneState).where(
                    DeviceHygieneState.device_id.in_(reserved_ids),
                    DeviceHygieneState.state == "verified_clean",
                )
            )
            or 0
        )
        health_cutoff = command.now - timedelta(
            seconds=command.policy.device_health_freshness_seconds
        )
        healthy_count = int(
            await db.scalar(
                select(func.count()).select_from(Device).where(
                    Device.id.in_(reserved_ids),
                    Device.last_seen.is_not(None),
                    Device.last_seen >= health_cutoff,
                )
            )
            or 0
        )
    participant_count = int(
        await db.scalar(
            select(func.count()).select_from(TrackParticipation).where(
                TrackParticipation.org_id == command.org_id,
                TrackParticipation.service_campaign_id == campaign.id,
                TrackParticipation.package_name == campaign.package_name,
                TrackParticipation.current_status == "opted_in",
            )
        )
        or 0
    )
    operational = (
        await db.execute(
            select(OperationalReadinessAssessment)
            .where(
                OperationalReadinessAssessment.org_id == command.org_id,
                OperationalReadinessAssessment.status == "ready",
                OperationalReadinessAssessment.valid_until > command.now,
            )
            .order_by(OperationalReadinessAssessment.observed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    checks = (
        _check(
            org_id=command.org_id,
            snapshot_id=snapshot.id,
            key="operational_dependencies",
            passed=operational is not None,
            required=True,
            observed_at=command.now,
            source_type="operational_readiness_assessment",
            source_ref=operational.id if operational else None,
            source_version=operational.schema_version if operational else None,
            owner="operations",
            blocked_reason="FRESH_OPERATIONAL_READINESS_REQUIRED",
            next_action="Recover dependencies and publish a fresh readiness assessment",
        ),
        _check(
            org_id=command.org_id,
            snapshot_id=snapshot.id,
            key="entitlement",
            passed=entitlement is not None,
            required=True,
            observed_at=command.now,
            source_type="service_entitlement",
            source_ref=entitlement.id if entitlement else None,
            source_version=None,
            owner="billing",
            blocked_reason="ACTIVE_ENTITLEMENT_REQUIRED",
            next_action="Verify or reconcile payment",
        ),
        _check(
            org_id=command.org_id,
            snapshot_id=snapshot.id,
            key="scenario_approval",
            passed=approval is not None,
            required=True,
            observed_at=command.now,
            source_type="scenario_approval",
            source_ref=approval.id if approval else None,
            source_version=approval.policy_version if approval else None,
            owner="customer",
            blocked_reason="APPROVED_SCENARIO_REQUIRED",
            next_action="Review and approve the generated scenario",
        ),
        _check(
            org_id=command.org_id,
            snapshot_id=snapshot.id,
            key="reservations",
            passed=len(reservations) == 12,
            required=True,
            observed_at=command.now,
            source_type="device_reservation",
            source_ref=campaign.id,
            source_version=None,
            owner="fleet",
            blocked_reason="TWELVE_ACTIVE_RESERVATIONS_REQUIRED",
            next_action="Reserve exactly 12 eligible devices",
        ),
        _check(
            org_id=command.org_id,
            snapshot_id=snapshot.id,
            key="hygiene",
            passed=clean_count == 12,
            required=True,
            observed_at=command.now,
            source_type="device_hygiene",
            source_ref=campaign.id,
            source_version=None,
            owner="fleet",
            blocked_reason="VERIFIED_CLEAN_COHORT_REQUIRED",
            next_action="Complete device cleanup readback",
        ),
        _check(
            org_id=command.org_id,
            snapshot_id=snapshot.id,
            key="device_health",
            passed=healthy_count == 12,
            required=True,
            observed_at=command.now,
            source_type="device_last_seen",
            source_ref=campaign.id,
            source_version=str(command.policy.device_health_freshness_seconds),
            owner="fleet",
            blocked_reason="TWELVE_HEALTHY_DEVICES_REQUIRED",
            next_action="Recover or replace stale devices",
        ),
        _check(
            org_id=command.org_id,
            snapshot_id=snapshot.id,
            key="participation",
            passed=participant_count == 12,
            required=command.policy.require_participation,
            observed_at=command.now,
            source_type="track_participation",
            source_ref=campaign.id,
            source_version=None,
            owner="operator",
            blocked_reason="TWELVE_OPTED_IN_IDENTITIES_REQUIRED",
            next_action="Review Play participation evidence",
        ),
        _check(
            org_id=command.org_id,
            snapshot_id=snapshot.id,
            key="secret",
            passed=command.dependencies.secret_ready,
            required=command.policy.require_secret,
            observed_at=command.now,
            source_type="secret_capability",
            source_ref=command.dependencies.secret_source_ref,
            source_version=None,
            owner="security",
            blocked_reason="JOB_SECRET_CAPABILITY_REQUIRED",
            next_action="Create a valid job-scoped secret reference",
        ),
    )
    db.add_all(checks)
    blocked = any(check.required and check.status != "required_pass" for check in checks)
    snapshot.status = "blocked" if blocked else "ready"
    intent = existing_intent
    if not blocked and existing_intent is None:
        campaign.status = "active"
        campaign.started_at = campaign.started_at or command.now
        campaign.end_at = campaign.end_at or campaign.started_at + timedelta(days=14)
        intent = SchedulingIntent(
            org_id=command.org_id,
            service_campaign_id=campaign.id,
            intent_kind="start",
            idempotency_key=command.idempotency_key,
            readiness_snapshot_id=snapshot.id,
            status="pending",
        )
        db.add(intent)
    await db.flush()
    if not blocked and intent is not None:
        await record_server_funnel_event(
            db,
            org_id=command.org_id,
            service_campaign_id=campaign.id,
            event_name="readiness_started",
            source_ref=intent.id,
            occurred_at=campaign.started_at or command.now,
        )
    return StartResult(not blocked, campaign, snapshot, checks, intent)


async def materialize_service_slots(
    db: AsyncSession,
    *,
    org_id: str,
    service_campaign_id: str,
) -> tuple[RunSlot, ...]:
    campaign = (
        await db.execute(
            select(ServiceCampaign)
            .where(
                ServiceCampaign.id == service_campaign_id,
                ServiceCampaign.org_id == org_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if campaign is None or campaign.started_at is None:
        raise ValueError("started service campaign is required")
    lanes = list(
        (
            await db.execute(
                select(ServiceLane)
                .where(
                    ServiceLane.org_id == org_id,
                    ServiceLane.service_campaign_id == service_campaign_id,
                )
                .order_by(ServiceLane.ordinal)
            )
        )
        .scalars()
        .all()
    )
    if len(lanes) != 12:
        raise ValueError("exactly 12 lanes are required")
    existing = {
        (slot.lane_id, slot.service_day): slot
        for slot in (
            await db.execute(
                select(RunSlot).where(
                    RunSlot.org_id == org_id,
                    RunSlot.service_campaign_id == service_campaign_id,
                )
            )
        )
        .scalars()
        .all()
    }
    for service_day in range(1, 15):
        for lane in lanes:
            key = (lane.id, service_day)
            if key not in existing:
                slot = RunSlot(
                    org_id=org_id,
                    service_campaign_id=service_campaign_id,
                    lane_id=lane.id,
                    service_day=service_day,
                    planned_at=campaign.started_at
                    + timedelta(days=service_day - 1, seconds=lane.ordinal - 1),
                    execution_status="scheduled",
                    play_participation_state="unknown",
                )
                db.add(slot)
                existing[key] = slot
    await db.flush()
    return tuple(existing[key] for key in sorted(existing, key=lambda item: (item[1], item[0])))
