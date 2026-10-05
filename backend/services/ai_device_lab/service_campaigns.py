"""Service-campaign creation and lifecycle invariants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.ai_device_lab import AppBuild, RunAttempt, RunSlot, ServiceCampaign, ServiceLane
from db.models.scenario_version import ScenarioVersion
from db.models.campaign import Campaign


class ServiceCampaignInvariantError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CreateServiceCampaign:
    org_id: str
    owner_id: str
    runtime_campaign_id: str
    package_name: str
    timezone: str
    plan_version: str
    lane_count: int = 12
    creation_intent_key: str | None = None


@dataclass(frozen=True, slots=True)
class CreateRunSlot:
    org_id: str
    service_campaign_id: str
    lane_id: str
    service_day: int
    planned_at: datetime


@dataclass(frozen=True, slots=True)
class AllocateRunAttempt:
    org_id: str
    service_campaign_id: str
    lane_id: str
    slot_id: str
    execution_id: str
    scenario_version_id: str
    app_build_id: str
    idempotency_key: str
    reason: str


async def create_service_campaign(
    db: AsyncSession,
    command: CreateServiceCampaign,
) -> ServiceCampaign:
    """Create a draft service contract and its stable logical lane identities."""
    if command.lane_count < 1 or command.lane_count > 12:
        raise ServiceCampaignInvariantError("lane_count must be between 1 and 12")
    if command.creation_intent_key:
        existing = (
            await db.execute(
                select(ServiceCampaign).where(
                    ServiceCampaign.org_id == command.org_id,
                    ServiceCampaign.creation_intent_key == command.creation_intent_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if (
                existing.runtime_campaign_id != command.runtime_campaign_id
                or existing.package_name != command.package_name
                or existing.plan_version != command.plan_version
            ):
                raise ServiceCampaignInvariantError("creation intent was already used for different input")
            return existing

    runtime_campaign_id = (
        await db.execute(
            select(Campaign.__table__.c.id).where(
                Campaign.__table__.c.id == command.runtime_campaign_id,
                Campaign.__table__.c.org_id == command.org_id,
            )
        )
    ).scalar_one_or_none()
    if runtime_campaign_id is None:
        raise ServiceCampaignInvariantError("runtime campaign is outside organization scope")

    campaign = ServiceCampaign(
        org_id=command.org_id,
        owner_id=command.owner_id,
        runtime_campaign_id=command.runtime_campaign_id,
        package_name=command.package_name,
        timezone=command.timezone,
        plan_version=command.plan_version,
        creation_intent_key=command.creation_intent_key,
        status="draft",
    )
    try:
        async with db.begin_nested():
            db.add(campaign)
            await db.flush()
            db.add_all(
                [
                    ServiceLane(
                        org_id=command.org_id,
                        service_campaign_id=campaign.id,
                        ordinal=ordinal,
                        tester_label=f"Tester {ordinal:02d}",
                    )
                    for ordinal in range(1, command.lane_count + 1)
                ]
            )
            await db.flush()
    except IntegrityError as exc:
        if not command.creation_intent_key:
            raise
        existing = (
            await db.execute(
                select(ServiceCampaign).where(
                    ServiceCampaign.org_id == command.org_id,
                    ServiceCampaign.creation_intent_key == command.creation_intent_key,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            raise ServiceCampaignInvariantError("service campaign creation conflicted") from exc
        if (
            existing.runtime_campaign_id != command.runtime_campaign_id
            or existing.package_name != command.package_name
            or existing.plan_version != command.plan_version
        ):
            raise ServiceCampaignInvariantError("creation intent was already used for different input") from exc
        return existing
    return campaign


async def create_run_slot(db: AsyncSession, command: CreateRunSlot) -> RunSlot:
    """Create one server-numbered service day without conflating it with a retry."""
    if command.service_day < 1 or command.service_day > 14:
        raise ServiceCampaignInvariantError("service_day must be between 1 and 14")
    lane_id = await db.scalar(
        select(ServiceLane.__table__.c.id).where(
            ServiceLane.__table__.c.id == command.lane_id,
            ServiceLane.__table__.c.org_id == command.org_id,
            ServiceLane.__table__.c.service_campaign_id == command.service_campaign_id,
        )
    )
    if lane_id is None:
        raise ServiceCampaignInvariantError("lane is outside campaign scope")
    slot = RunSlot(
        org_id=command.org_id,
        service_campaign_id=command.service_campaign_id,
        lane_id=command.lane_id,
        service_day=command.service_day,
        planned_at=command.planned_at,
        execution_status="planned",
        play_participation_state="unknown",
    )
    db.add(slot)
    await db.flush()
    return slot


async def allocate_run_attempt(
    db: AsyncSession,
    command: AllocateRunAttempt,
) -> RunAttempt:
    """Allocate one run attempt idempotently while retaining the original slot."""
    existing = (
        await db.execute(
            select(RunAttempt).where(
                RunAttempt.org_id == command.org_id,
                RunAttempt.idempotency_key == command.idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.service_campaign_id != command.service_campaign_id
            or existing.lane_id != command.lane_id
            or existing.slot_id != command.slot_id
            or existing.execution_id != command.execution_id
            or existing.scenario_version_id != command.scenario_version_id
            or existing.app_build_id != command.app_build_id
            or existing.reason != command.reason
        ):
            raise ServiceCampaignInvariantError(
                "attempt idempotency key was reused with different input"
            )
        return existing

    slot = (
        await db.execute(
            select(RunSlot).where(
                RunSlot.id == command.slot_id,
                RunSlot.org_id == command.org_id,
                RunSlot.service_campaign_id == command.service_campaign_id,
                RunSlot.lane_id == command.lane_id,
            ).with_for_update()
        )
    ).scalar_one_or_none()
    existing = (
        await db.execute(
            select(RunAttempt).where(
                RunAttempt.org_id == command.org_id,
                RunAttempt.idempotency_key == command.idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.service_campaign_id != command.service_campaign_id
            or existing.lane_id != command.lane_id
            or existing.slot_id != command.slot_id
            or existing.execution_id != command.execution_id
            or existing.scenario_version_id != command.scenario_version_id
            or existing.app_build_id != command.app_build_id
            or existing.reason != command.reason
        ):
            raise ServiceCampaignInvariantError(
                "attempt idempotency key was reused with different input"
            )
        return existing
    build_id = await db.scalar(
        select(AppBuild.__table__.c.id).where(
            AppBuild.__table__.c.id == command.app_build_id,
            AppBuild.__table__.c.org_id == command.org_id,
        )
    )
    scenario_version_id = await db.scalar(
        select(ScenarioVersion.__table__.c.id).where(
            ScenarioVersion.__table__.c.id == command.scenario_version_id
        )
    )
    if slot is None or build_id is None or scenario_version_id is None:
        raise ServiceCampaignInvariantError("attempt references are outside approved scope")

    last_attempt = await db.scalar(
        select(func.max(RunAttempt.attempt_no)).where(
            RunAttempt.org_id == command.org_id,
            RunAttempt.slot_id == command.slot_id,
        )
    )
    attempt = RunAttempt(
        org_id=command.org_id,
        service_campaign_id=command.service_campaign_id,
        lane_id=command.lane_id,
        slot_id=command.slot_id,
        attempt_no=int(last_attempt or 0) + 1,
        execution_id=command.execution_id,
        scenario_version_id=command.scenario_version_id,
        app_build_id=command.app_build_id,
        idempotency_key=command.idempotency_key,
        reason=command.reason,
        status="created",
    )
    db.add(attempt)
    await db.flush()
    return attempt
