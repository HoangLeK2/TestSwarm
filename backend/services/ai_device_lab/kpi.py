"""Reproducible KPI cohort freezing and source-row measurement."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.ai_device_lab import RunAttempt, ServiceCampaign
from db.models.ai_device_lab_billing import ServiceOrder
from db.models.ai_device_lab_kpi import (
    KpiAssistanceEvent,
    KpiCohort,
    KpiCohortMember,
    KpiMeasurementDefinition,
    KpiSnapshot,
)
from db.models.ai_device_lab_runtime import ReadinessSnapshot
from db.models.execution import Execution
from db.models.execution_step import ExecutionStep


class KpiInvariantError(ValueError):
    pass


TERMINAL_EXECUTION_STATES = ("completed", "failed", "cancelled", "dlq_closed")


@dataclass(frozen=True, slots=True)
class SignKpiDefinition:
    org_id: str
    version: str
    definitions: dict
    signed_by: str
    signed_at: datetime


@dataclass(frozen=True, slots=True)
class FreezeKpiCohort:
    org_id: str
    cohort_key: str
    definition_id: str
    source_kind: str
    window_start: datetime
    window_end: datetime
    timezone: str
    service_campaign_ids: tuple[str, ...]
    created_by: str
    frozen_at: datetime


@dataclass(frozen=True, slots=True)
class RecordAssistance:
    org_id: str
    event_id: str
    service_campaign_id: str
    actor_id: str
    assistance_type: str
    classification: str
    reason: str
    occurred_at: datetime


async def sign_kpi_definition(
    db: AsyncSession,
    command: SignKpiDefinition,
) -> KpiMeasurementDefinition:
    existing = (
        await db.execute(
            select(KpiMeasurementDefinition).where(
                KpiMeasurementDefinition.org_id == command.org_id,
                KpiMeasurementDefinition.version == command.version,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.definitions != command.definitions:
            raise KpiInvariantError("signed KPI definition version is immutable")
        return existing
    required = {"self_serve_onboarding", "run_with_trace", "window_timezone"}
    if not required.issubset(command.definitions):
        raise KpiInvariantError("KPI definition is missing required measurement terms")
    definition = KpiMeasurementDefinition(
        org_id=command.org_id,
        version=command.version,
        definitions=dict(command.definitions),
        status="signed",
        signed_by=command.signed_by,
        signed_at=command.signed_at,
    )
    db.add(definition)
    await db.flush()
    return definition


async def freeze_kpi_cohort(db: AsyncSession, command: FreezeKpiCohort) -> KpiCohort:
    existing = (
        await db.execute(
            select(KpiCohort).where(
                KpiCohort.org_id == command.org_id,
                KpiCohort.cohort_key == command.cohort_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing_members = set(
            (
                await db.execute(
                    select(KpiCohortMember.service_campaign_id).where(
                        KpiCohortMember.org_id == command.org_id,
                        KpiCohortMember.cohort_id == existing.id,
                    )
                )
            ).scalars()
        )
        if (
            existing.definition_id != command.definition_id
            or existing.source_kind != command.source_kind
            or existing.window_start != command.window_start
            or existing.window_end != command.window_end
            or existing.timezone != command.timezone
            or existing_members != set(command.service_campaign_ids)
        ):
            raise KpiInvariantError("cohort key was reused with different input")
        return existing
    if command.source_kind not in {"fixture", "real"}:
        raise KpiInvariantError("cohort source must be fixture or real")
    if command.window_start >= command.window_end:
        raise KpiInvariantError("measurement window must be non-empty")
    campaign_ids = tuple(sorted(set(command.service_campaign_ids)))
    if not campaign_ids:
        raise KpiInvariantError("cohort must contain at least one campaign")
    definition = (
        await db.execute(
            select(KpiMeasurementDefinition).where(
                KpiMeasurementDefinition.id == command.definition_id,
                KpiMeasurementDefinition.org_id == command.org_id,
                KpiMeasurementDefinition.status == "signed",
            )
        )
    ).scalar_one_or_none()
    if definition is None:
        raise KpiInvariantError("signed KPI definition is required")
    campaigns = list(
        (
            await db.execute(
                select(ServiceCampaign.id).where(
                    ServiceCampaign.org_id == command.org_id,
                    ServiceCampaign.id.in_(campaign_ids),
                )
            )
        ).scalars()
    )
    if len(campaigns) != len(campaign_ids):
        raise KpiInvariantError("cohort contains an out-of-scope campaign")
    cohort = KpiCohort(
        org_id=command.org_id,
        cohort_key=command.cohort_key,
        definition_id=definition.id,
        source_kind=command.source_kind,
        window_start=command.window_start,
        window_end=command.window_end,
        timezone=command.timezone,
        status="frozen",
        frozen_at=command.frozen_at,
        created_by=command.created_by,
    )
    db.add(cohort)
    await db.flush()
    db.add_all(
        [
            KpiCohortMember(
                org_id=command.org_id,
                cohort_id=cohort.id,
                service_campaign_id=campaign_id,
                eligible=True,
            )
            for campaign_id in campaign_ids
        ]
    )
    await db.flush()
    return cohort


async def record_kpi_assistance(
    db: AsyncSession,
    command: RecordAssistance,
) -> KpiAssistanceEvent:
    if command.classification not in {"completion", "review_only"}:
        raise KpiInvariantError("assistance classification must be completion or review_only")
    existing = (
        await db.execute(
            select(KpiAssistanceEvent).where(
                KpiAssistanceEvent.org_id == command.org_id,
                KpiAssistanceEvent.event_id == command.event_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.service_campaign_id != command.service_campaign_id
            or existing.actor_id != command.actor_id
            or existing.assistance_type != command.assistance_type
            or existing.classification != command.classification
            or existing.reason != command.reason
            or existing.occurred_at != command.occurred_at
        ):
            raise KpiInvariantError("assistance event id was reused with different input")
        return existing
    campaign_exists = await db.scalar(
        select(ServiceCampaign.id).where(
            ServiceCampaign.id == command.service_campaign_id,
            ServiceCampaign.org_id == command.org_id,
        )
    )
    if campaign_exists is None:
        raise KpiInvariantError("assistance campaign is outside tenant scope")
    event = KpiAssistanceEvent(
        org_id=command.org_id,
        event_id=command.event_id,
        service_campaign_id=command.service_campaign_id,
        actor_id=command.actor_id,
        assistance_type=command.assistance_type,
        classification=command.classification,
        reason=command.reason,
        occurred_at=command.occurred_at,
    )
    db.add(event)
    await db.flush()
    return event


async def compute_kpi_snapshot(
    db: AsyncSession,
    *,
    org_id: str,
    cohort_id: str,
    query_version: str,
    data_freshness_at: datetime,
) -> KpiSnapshot:
    existing = (
        await db.execute(
            select(KpiSnapshot).where(
                KpiSnapshot.org_id == org_id,
                KpiSnapshot.cohort_id == cohort_id,
                KpiSnapshot.query_version == query_version,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    cohort = (
        await db.execute(
            select(KpiCohort).where(
                KpiCohort.id == cohort_id,
                KpiCohort.org_id == org_id,
                KpiCohort.status == "frozen",
            )
        )
    ).scalar_one_or_none()
    if cohort is None:
        raise KpiInvariantError("frozen KPI cohort is required")
    members = list(
        (
            await db.execute(
                select(KpiCohortMember).where(
                    KpiCohortMember.org_id == org_id,
                    KpiCohortMember.cohort_id == cohort.id,
                    KpiCohortMember.eligible.is_(True),
                )
            )
        ).scalars()
    )
    campaign_ids = {member.service_campaign_id for member in members}
    paid_campaign_ids = set(
        (
            await db.execute(
                select(ServiceOrder.service_campaign_id).where(
                    ServiceOrder.org_id == org_id,
                    ServiceOrder.service_campaign_id.in_(campaign_ids),
                    ServiceOrder.status == "paid",
                    ServiceOrder.paid_at >= cohort.window_start,
                    ServiceOrder.paid_at < cohort.window_end,
                )
            )
        ).scalars()
    )
    ready_campaign_ids = set(
        (
            await db.execute(
                select(ReadinessSnapshot.service_campaign_id).where(
                    ReadinessSnapshot.org_id == org_id,
                    ReadinessSnapshot.service_campaign_id.in_(paid_campaign_ids),
                    ReadinessSnapshot.status == "ready",
                    ReadinessSnapshot.observed_at >= cohort.window_start,
                    ReadinessSnapshot.observed_at < cohort.window_end,
                )
            )
        ).scalars()
    )
    assisted_completion_ids = set(
        (
            await db.execute(
                select(KpiAssistanceEvent.service_campaign_id).where(
                    KpiAssistanceEvent.org_id == org_id,
                    KpiAssistanceEvent.service_campaign_id.in_(paid_campaign_ids),
                    KpiAssistanceEvent.classification == "completion",
                    KpiAssistanceEvent.occurred_at >= cohort.window_start,
                    KpiAssistanceEvent.occurred_at < cohort.window_end,
                )
            )
        ).scalars()
    )
    self_serve_ids = ready_campaign_ids - assisted_completion_ids

    execution_rows = list(
        (
            await db.execute(
                select(Execution.id, RunAttempt.service_campaign_id)
                .join(RunAttempt, RunAttempt.execution_id == Execution.id)
                .where(
                    Execution.org_id == org_id,
                    RunAttempt.org_id == org_id,
                    RunAttempt.service_campaign_id.in_(campaign_ids),
                    Execution.status.in_(TERMINAL_EXECUTION_STATES),
                    Execution.finished_at >= cohort.window_start,
                    Execution.finished_at < cohort.window_end,
                )
                .distinct()
            )
        ).all()
    )
    terminal_execution_ids = {row.id for row in execution_rows}
    traced_execution_ids = set(
        (
            await db.execute(
                select(ExecutionStep.execution_id)
                .where(
                    ExecutionStep.org_id == org_id,
                    ExecutionStep.execution_id.in_(terminal_execution_ids),
                )
                .distinct()
            )
        ).scalars()
    )
    self_denominator = len(paid_campaign_ids)
    trace_denominator = len(terminal_execution_ids)
    result_status = (
        "fixture_only"
        if cohort.source_kind == "fixture"
        else "not_applicable"
        if self_denominator == 0 and trace_denominator == 0
        else "measured"
    )
    details = {
        "window": {
            "start": cohort.window_start.isoformat(),
            "end": cohort.window_end.isoformat(),
            "timezone": cohort.timezone,
        },
        "self_serve_onboarding": {
            "status": "not_applicable" if self_denominator == 0 else "measured",
            "assisted_completion_count": len(assisted_completion_ids),
        },
        "run_with_trace": {
            "status": "not_applicable" if trace_denominator == 0 else "measured",
            "missing_trace_count": trace_denominator - len(traced_execution_ids),
        },
        "threshold_evaluation": "not_evaluated",
    }
    snapshot = KpiSnapshot(
        org_id=org_id,
        cohort_id=cohort.id,
        query_version=query_version,
        source_kind=cohort.source_kind,
        result_status=result_status,
        self_serve_numerator=len(self_serve_ids),
        self_serve_denominator=self_denominator,
        trace_numerator=len(traced_execution_ids),
        trace_denominator=trace_denominator,
        details=details,
        data_freshness_at=data_freshness_at,
    )
    db.add(snapshot)
    await db.flush()
    return snapshot
