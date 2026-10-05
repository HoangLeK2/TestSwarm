"""Tenant-scoped production API for AI Device Lab service state."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Integer, func, select

from api.deps import CurrentUser, DB, require_permission
from api.schemas.ai_device_lab import (
    AcceptanceCandidateOut,
    AcceptanceDecisionOut,
    ApproveWizardScenarioIn,
    BuildAcceptanceCandidateIn,
    CancelServiceCampaignIn,
    CampaignFunnelOut,
    ComputeKpiSnapshotIn,
    CreateFarmRunIn,
    CreateIssueIn,
    DeviceHygieneResultIn,
    DeviceHygieneResultOut,
    EvidenceDownloadOut,
    EvidenceSummaryOut,
    ExtendServiceCampaignIn,
    FunnelEventOut,
    FarmEventIn,
    FarmEventOut,
    FarmRunOut,
    EvaluateAcceptanceCandidateIn,
    FleetLifecycleOperationOut,
    FreezeKpiCohortIn,
    KpiAssistanceOut,
    KpiCohortOut,
    KpiDefinitionOut,
    KpiSnapshotOut,
    IssueListOut,
    IssueSummaryOut,
    MaterializeSlotsOut,
    ReadinessCheckOut,
    ReportDownloadOut,
    ReportListOut,
    ReportSummaryOut,
    ReservationSummaryOut,
    ReplaceLaneDeviceIn,
    RecordKpiAssistanceIn,
    ServiceCampaignCreateIn,
    ServiceCampaignOut,
    ServiceLaneDetailOut,
    ServiceLaneListOut,
    ServiceLaneSummaryOut,
    ServiceExtensionOut,
    ServiceProgressOut,
    ParticipationListOut,
    ParticipationRecordOut,
    ParticipationSummaryOut,
    PaymentReconciliationListOut,
    PaymentReconciliationOut,
    RecordParticipationIn,
    RequestRetestIn,
    RetestRequestOut,
    RunAttemptSummaryOut,
    RunSlotDetailOut,
    SignKpiDefinitionIn,
    StartCampaignIn,
    StartCampaignOut,
    StartWizardCheckoutIn,
    StartWizardGenerationIn,
    SaveWizardDraftIn,
    WizardApprovalOut,
    WizardCheckoutOut,
    WizardGenerationOut,
    WizardIntakeOut,
    WizardPaymentOut,
    WizardStateOut,
)
from db.models.ai_device_lab import RunAttempt, RunSlot, ServiceCampaign, ServiceLane
from db.models.ai_device_lab_delivery import EvidenceItem, FarmJob
from db.models.ai_device_lab_billing import (
    PaymentReconciliationJob,
    ServiceOrder,
)
from db.models.ai_device_lab_fleet import DeviceReservation
from db.models.device import Device
from db.models.ai_device_lab_participation import TrackParticipation
from db.models.ai_device_lab_quality import AppIssue, RetestRequest
from db.models.ai_device_lab_report import ReportSnapshot
from db.models.ai_device_lab_kpi import KpiCohort
from db.models.ai_device_lab_acceptance import AcceptanceCandidate
from services.ai_device_lab.readiness import (
    ReadinessPolicy,
    StartCampaign,
    materialize_service_slots,
    start_campaign,
)
from services.ai_device_lab.fleet import record_hygiene_result
from services.ai_device_lab.delivery import (
    AcceptFarmEvent,
    CreateFarmRun,
    DeliveryInvariantError,
    accept_farm_event,
    create_farm_run,
)
from services.ai_device_lab.funnel import (
    FUNNEL_STEPS,
    ClientFunnelEvent,
    FunnelInvariantError,
    list_campaign_funnel,
    record_client_acquisition,
)
from services.ai_device_lab.billing_checkout import (
    CheckoutInvariantError,
    StartWizardCheckout,
    start_wizard_checkout,
)
from services.ai_device_lab.lifecycle import (
    ExtendServiceCampaign,
    LifecycleInvariantError,
    ReplaceLaneDevice,
    cancel_service_campaign,
    complete_campaign_cancellation,
    complete_device_replacement,
    expire_service_campaign,
    extend_service_campaign,
    replace_lane_device,
)
from services.ai_device_lab.participation import (
    ParticipationInvariantError,
    RecordParticipation,
    record_participation,
)
from services.ai_device_lab.report_pdf import (
    ReportPdfInvariantError,
    publish_report_pdf,
)
from services.ai_device_lab.quality import (
    CreateIssue,
    QualityInvariantError,
    RequestRetest,
    create_issue,
    request_retest,
)
from services.ai_device_lab.kpi import (
    FreezeKpiCohort,
    KpiInvariantError,
    RecordAssistance,
    SignKpiDefinition,
    compute_kpi_snapshot,
    freeze_kpi_cohort,
    record_kpi_assistance,
    sign_kpi_definition,
)
from services.ai_device_lab.acceptance import (
    AcceptanceInvariantError,
    BuildAcceptanceCandidate,
    RequirementEvidence,
    build_acceptance_candidate,
    evaluate_acceptance_candidate,
)
from services.ai_device_lab.service_campaigns import (
    CreateServiceCampaign,
    ServiceCampaignInvariantError,
    create_service_campaign,
)
from services.ai_device_lab.intake import (
    ApproveScenario,
    ScenarioGenerationRejected,
    approve_scenario,
    scenario_version_content_hash,
)
from services.ai_device_lab.wizard import (
    SaveWizardDraft,
    WizardDraftInput,
    WizardInvariantError,
    WizardNotFound,
    WizardRevisionConflict,
    WizardState,
    load_wizard_state,
    run_wizard_generation,
    save_wizard_draft,
    wizard_operation_policy,
)


router = APIRouter(prefix="/ai-device-lab", tags=["ai-device-lab"])


def _org_id(user: CurrentUser) -> str:
    org_id = str(getattr(user, "org_id", "") or "")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Organization required"
        )
    return org_id


def _operation_out(operation) -> FleetLifecycleOperationOut:
    return FleetLifecycleOperationOut.model_validate(operation, from_attributes=True)


def _farm_run_out(job: FarmJob) -> FarmRunOut:
    payload = job.payload
    deadline_at = job.deadline_at
    if deadline_at.tzinfo is None:
        deadline_at = deadline_at.replace(tzinfo=timezone.utc)
    return FarmRunOut(
        job_id=job.id,
        run_attempt_id=job.run_attempt_id,
        execution_id=payload["execution_id"],
        slot_id=payload["slot_id"],
        lane_id=payload["lane_id"],
        device_id=job.device_id,
        reservation_id=job.reservation_id,
        scenario_version_id=payload["scenario_version_id"],
        scenario_hash=payload["scenario_hash"],
        policy_version=payload["policy_version"],
        schema_version=job.schema_version,
        status=job.status,
        verdict=job.verdict,
        terminal_reason=job.terminal_reason,
        deadline_at=deadline_at,
    )


async def _campaign_out(db: DB, campaign: ServiceCampaign) -> ServiceCampaignOut:
    lane_count = int(
        await db.scalar(
            select(func.count())
            .select_from(ServiceLane)
            .where(
                ServiceLane.org_id == campaign.org_id,
                ServiceLane.service_campaign_id == campaign.id,
            )
        )
        or 0
    )
    return ServiceCampaignOut(
        id=campaign.id,
        runtime_campaign_id=campaign.runtime_campaign_id,
        package_name=campaign.package_name,
        timezone=campaign.timezone,
        plan_version=campaign.plan_version,
        status=campaign.status,
        lane_count=lane_count,
        started_at=campaign.started_at,
        end_at=campaign.end_at,
    )


async def _wizard_state_out(db: DB, state: WizardState) -> WizardStateOut:
    intake = None
    if state.intake is not None and state.build is not None:
        intake = WizardIntakeOut(
            id=state.intake.id,
            revision=state.intake.lock_version,
            input_version=state.intake.input_version,
            package_name=state.intake.package_name,
            closed_track_link=state.intake.closed_track_link,
            test_goal=state.intake.test_goal,
            test_environment=state.intake.test_environment,
            status=state.intake.status,
            build={
                "id": state.build.id,
                "version_name": state.build.version_name,
                "version_code": state.build.version_code,
                "source_kind": state.build.source_kind,
                "source_ref": state.build.source_ref,
                "checksum_sha256": state.build.checksum_sha256,
            },
        )
    generation = None
    if state.generation is not None:
        version = state.scenario_version
        generation = WizardGenerationOut(
            operation_id=state.generation.operation_id,
            status=state.generation.status,
            error_code=state.generation.error_code,
            scenario_version_id=state.generation.scenario_version_id,
            content_hash=scenario_version_content_hash(version) if version else None,
            scenario=(
                {
                    "instructions": version.instructions,
                    "steps": version.steps or [],
                    "nodes": version.nodes or [],
                    "edges": version.edges or [],
                    "variables": version.variables or {},
                    "requirements": version.requirements or {},
                }
                if version
                else None
            ),
        )
    approval = None
    if state.approval is not None:
        approval = WizardApprovalOut.model_validate(
            state.approval, from_attributes=True
        )
    payment = state.payment
    return WizardStateOut(
        campaign=await _campaign_out(db, state.campaign),
        current_step=state.current_step,
        intake=intake,
        generation=generation,
        approval=approval,
        payment=WizardPaymentOut(
            provider_configured=payment.provider_configured,
            provider=payment.provider,
            amount_minor=payment.amount_minor,
            currency=payment.currency,
            pricing_version=payment.pricing_version,
            policy_version=payment.policy_version,
            quota=payment.quota,
            blocker_code=payment.blocker_code,
            order=(
                {
                    "id": payment.order.id,
                    "status": payment.order.status,
                    "amount_minor": payment.order.amount_minor,
                    "currency": payment.order.currency,
                    "pricing_version": payment.order.pricing_version,
                    "policy_version": payment.order.policy_version,
                }
                if payment.order
                else None
            ),
            checkout_status=payment.intent.status if payment.intent else None,
            checkout_expires_at=(
                payment.intent.checkout_expires_at if payment.intent else None
            ),
            checkout_error_code=(
                payment.intent.last_error_code if payment.intent else None
            ),
            entitlement=(
                {"id": payment.entitlement.id, "state": payment.entitlement.state}
                if payment.entitlement
                else None
            ),
        ),
    )


@router.post(
    "/service-campaigns/{campaign_id}/wizard/payment/checkout",
    response_model=WizardCheckoutOut,
    dependencies=[Depends(require_permission("campaigns", "update"))],
)
async def start_wizard_checkout_route(
    campaign_id: str,
    body: StartWizardCheckoutIn,
    db: DB,
    user: CurrentUser,
) -> WizardCheckoutOut:
    await _require_service_campaign(
        db,
        org_id=_org_id(user),
        campaign_id=campaign_id,
    )
    try:
        result = await start_wizard_checkout(
            db,
            StartWizardCheckout(
                org_id=_org_id(user),
                service_campaign_id=campaign_id,
                approval_id=body.approval_id,
                idempotency_key=body.idempotency_key,
                actor_id=str(user.id),
                now=datetime.now(timezone.utc),
            ),
        )
    except CheckoutInvariantError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code},
        ) from exc
    return WizardCheckoutOut(
        order_id=result.order_id,
        intent_id=result.intent_id,
        status=result.status,
        checkout_url=result.checkout_url,
        expires_at=result.expires_at,
        blocker_code=result.blocker_code,
    )


async def _require_service_campaign(db: DB, *, org_id: str, campaign_id: str) -> None:
    exists = await db.scalar(
        select(ServiceCampaign.id).where(
            ServiceCampaign.id == campaign_id,
            ServiceCampaign.org_id == org_id,
        )
    )
    if exists is None:
        raise HTTPException(status_code=404, detail="Service campaign not found")


@router.post(
    "/devices/{device_id}/hygiene-results",
    response_model=DeviceHygieneResultOut,
    dependencies=[Depends(require_permission("devices", "update"))],
)
async def record_device_hygiene_result_route(
    device_id: str,
    body: DeviceHygieneResultIn,
    db: DB,
    user: CurrentUser,
) -> DeviceHygieneResultOut:
    org_id = _org_id(user)
    device_exists = await db.scalar(
        select(Device.id).where(Device.id == device_id, Device.org_id == org_id)
    )
    if device_exists is None:
        raise HTTPException(status_code=404, detail="Device not found")
    if body.service_campaign_id is not None:
        await _require_service_campaign(
            db,
            org_id=org_id,
            campaign_id=body.service_campaign_id,
        )
    state = await record_hygiene_result(
        db,
        device_id=device_id,
        actor_id=str(user.id),
        protocol_version=body.protocol_version,
        reset_succeeded=body.reset_succeeded,
        readback_clean=body.readback_clean,
        evidence_ref=body.evidence_ref,
        active_run=body.active_run,
        service_campaign_id=body.service_campaign_id,
        target_type=body.target_type,
    )
    return DeviceHygieneResultOut(
        device_id=state.device_id,
        target_type=body.target_type,
        state=state.state,
        protocol_version=state.protocol_version,
        reason_code=str(state.reason_code or ""),
        verification_evidence_ref=state.verification_evidence_ref,
    )


@router.post(
    "/service-campaigns/{campaign_id}/farm-runs",
    response_model=FarmRunOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("campaigns", "execute"))],
)
async def create_farm_run_route(
    campaign_id: str,
    body: CreateFarmRunIn,
    db: DB,
    user: CurrentUser,
) -> FarmRunOut:
    try:
        _, job = await create_farm_run(
            db,
            CreateFarmRun(
                org_id=_org_id(user),
                service_campaign_id=campaign_id,
                lane_id=body.lane_id,
                slot_id=body.slot_id,
                execution_id=body.execution_id,
                scenario_version_id=body.scenario_version_id,
                app_build_id=body.app_build_id,
                reservation_id=body.reservation_id,
                approval_id=body.approval_id,
                idempotency_key=body.idempotency_key,
                deadline_at=body.deadline_at,
                reason=body.reason,
            ),
        )
    except (DeliveryInvariantError, ServiceCampaignInvariantError) as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc
    return _farm_run_out(job)


@router.get(
    "/farm-jobs/{job_id}",
    response_model=FarmRunOut,
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def get_farm_job_route(
    job_id: str,
    db: DB,
    user: CurrentUser,
) -> FarmRunOut:
    job = await db.scalar(
        select(FarmJob).where(
            FarmJob.id == job_id,
            FarmJob.org_id == _org_id(user),
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Farm job not found")
    return _farm_run_out(job)


@router.post(
    "/farm-jobs/{job_id}/events",
    response_model=FarmEventOut,
    dependencies=[Depends(require_permission("campaigns", "execute"))],
)
async def record_farm_event_route(
    job_id: str,
    body: FarmEventIn,
    db: DB,
    user: CurrentUser,
) -> FarmEventOut:
    if body.event_type != "step" or body.assertion_passed is not None:
        raise HTTPException(
            status_code=403,
            detail={"code": "FARM_TERMINAL_EVENTS_ARE_RUNTIME_INTERNAL"},
        )
    try:
        event, job = await accept_farm_event(
            db,
            AcceptFarmEvent(
                org_id=_org_id(user),
                job_id=job_id,
                schema_version=body.schema_version,
                execution_id=body.execution_id,
                source=body.source,
                event_id=body.event_id,
                event_type=body.event_type,
                occurred_at=body.occurred_at,
                sequence=body.sequence,
                reason_code=body.reason_code,
                assertion_passed=body.assertion_passed,
                step_path=body.step_path,
                step_attempt_index=body.step_attempt_index,
                artifact_refs=tuple(body.artifact_refs),
            ),
        )
    except DeliveryInvariantError as exc:
        if str(exc) == "job not found":
            raise HTTPException(status_code=404, detail="Farm job not found") from exc
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc
    return FarmEventOut(
        event_id=event.event_id,
        job_id=job.id,
        job_status=job.status,
        verdict=job.verdict,
        terminal_reason=job.terminal_reason,
    )


@router.post(
    "/service-campaigns",
    response_model=ServiceCampaignOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("campaigns", "create"))],
)
async def create_service_campaign_route(
    body: ServiceCampaignCreateIn,
    db: DB,
    user: CurrentUser,
) -> ServiceCampaignOut:
    try:
        campaign = await create_service_campaign(
            db,
            CreateServiceCampaign(
                org_id=_org_id(user),
                owner_id=str(user.id),
                runtime_campaign_id=body.runtime_campaign_id,
                package_name=body.package_name,
                timezone=body.timezone,
                plan_version=body.plan_version,
                creation_intent_key=body.creation_intent_key,
            ),
        )
        await record_client_acquisition(
            db,
            org_id=_org_id(user),
            service_campaign_id=campaign.id,
            events=tuple(
                ClientFunnelEvent(
                    event_id=event.event_id,
                    event_name=event.event_name,
                    occurred_at=event.occurred_at,
                    attribution=event.attribution,
                )
                for event in body.acquisition_events
            ),
            now=datetime.now(timezone.utc),
        )
    except (ServiceCampaignInvariantError, FunnelInvariantError) as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": (
                    exc.code
                    if isinstance(exc, FunnelInvariantError)
                    else "INVALID_SERVICE_CAMPAIGN"
                )
            },
        ) from exc
    return await _campaign_out(db, campaign)


@router.get(
    "/service-campaigns/{campaign_id}",
    response_model=ServiceCampaignOut,
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def get_service_campaign_route(
    campaign_id: str,
    db: DB,
    user: CurrentUser,
) -> ServiceCampaignOut:
    campaign = (
        await db.execute(
            select(ServiceCampaign).where(
                ServiceCampaign.id == campaign_id,
                ServiceCampaign.org_id == _org_id(user),
            )
        )
    ).scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Service campaign not found")
    return await _campaign_out(db, campaign)


@router.get(
    "/service-campaigns/{campaign_id}/funnel",
    response_model=CampaignFunnelOut,
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def get_campaign_funnel_route(
    campaign_id: str,
    db: DB,
    user: CurrentUser,
) -> CampaignFunnelOut:
    org_id = _org_id(user)
    await _require_service_campaign(db, org_id=org_id, campaign_id=campaign_id)
    rows = await list_campaign_funnel(
        db,
        org_id=org_id,
        service_campaign_id=campaign_id,
    )
    names = {row.event_name for row in rows}
    next_step = next((step for step in FUNNEL_STEPS if step not in names), None)
    return CampaignFunnelOut(
        service_campaign_id=campaign_id,
        acquisition_id=(rows[0].acquisition_id if rows else campaign_id),
        completed_steps=len(names),
        next_step=next_step,
        events=[
            FunnelEventOut(
                event_id=row.event_id,
                event_name=row.event_name,
                source_type=row.source_type,
                source_ref=row.source_ref,
                attribution=row.attribution,
                source_occurred_at=row.source_occurred_at,
            )
            for row in rows
        ],
    )


@router.get(
    "/service-campaigns/{campaign_id}/wizard",
    response_model=WizardStateOut,
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def get_wizard_state_route(
    campaign_id: str,
    db: DB,
    user: CurrentUser,
) -> WizardStateOut:
    try:
        state = await load_wizard_state(
            db,
            org_id=_org_id(user),
            service_campaign_id=campaign_id,
        )
    except WizardNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": exc.code}) from exc
    return await _wizard_state_out(db, state)


@router.get(
    "/service-campaigns/{campaign_id}/payment-reconciliations",
    response_model=PaymentReconciliationListOut,
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def list_payment_reconciliations_route(
    campaign_id: str,
    db: DB,
    user: CurrentUser,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> PaymentReconciliationListOut:
    org_id = _org_id(user)
    await _require_service_campaign(db, org_id=org_id, campaign_id=campaign_id)
    filters = (
        PaymentReconciliationJob.org_id == org_id,
        ServiceOrder.org_id == org_id,
        ServiceOrder.service_campaign_id == campaign_id,
        PaymentReconciliationJob.order_id == ServiceOrder.id,
    )
    total = int(
        await db.scalar(
            select(func.count())
            .select_from(PaymentReconciliationJob)
            .join(ServiceOrder, PaymentReconciliationJob.order_id == ServiceOrder.id)
            .where(*filters)
        )
        or 0
    )
    rows = list(
        (
            await db.execute(
                select(PaymentReconciliationJob)
                .join(ServiceOrder, PaymentReconciliationJob.order_id == ServiceOrder.id)
                .where(*filters)
                .order_by(
                    PaymentReconciliationJob.created_at.desc(),
                    PaymentReconciliationJob.id.desc(),
                )
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
    )
    return PaymentReconciliationListOut(
        items=[
            PaymentReconciliationOut.model_validate(row, from_attributes=True)
            for row in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.put(
    "/service-campaigns/{campaign_id}/wizard/app",
    response_model=WizardStateOut,
    dependencies=[Depends(require_permission("campaigns", "manage"))],
)
async def save_wizard_draft_route(
    campaign_id: str,
    body: SaveWizardDraftIn,
    db: DB,
    user: CurrentUser,
) -> WizardStateOut:
    org_id = _org_id(user)
    try:
        await save_wizard_draft(
            db,
            SaveWizardDraft(
                org_id=org_id,
                owner_id=str(user.id),
                service_campaign_id=campaign_id,
                expected_revision=body.expected_revision,
                draft=WizardDraftInput(
                    package_name=body.package_name,
                    closed_track_link=body.closed_track_link,
                    test_goal=body.test_goal,
                    test_environment=body.test_environment,
                    version_name=body.build.version_name,
                    version_code=body.build.version_code,
                    source_kind=body.build.source_kind,
                    source_ref=body.build.source_ref,
                    checksum_sha256=body.build.checksum_sha256,
                ),
            ),
        )
        state = await load_wizard_state(
            db,
            org_id=org_id,
            service_campaign_id=campaign_id,
        )
    except WizardNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": exc.code}) from exc
    except WizardRevisionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "current_revision": exc.current_revision},
        ) from exc
    except WizardInvariantError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code}) from exc
    return await _wizard_state_out(db, state)


@router.post(
    "/service-campaigns/{campaign_id}/wizard/scenario/generate",
    response_model=WizardStateOut,
    dependencies=[Depends(require_permission("campaigns", "manage"))],
)
async def generate_wizard_scenario_route(
    campaign_id: str,
    body: StartWizardGenerationIn,
    db: DB,
    user: CurrentUser,
) -> WizardStateOut:
    org_id = _org_id(user)
    try:
        await run_wizard_generation(
            db,
            org_id=org_id,
            service_campaign_id=campaign_id,
            operation_id=body.operation_id,
        )
        state = await load_wizard_state(
            db,
            org_id=org_id,
            service_campaign_id=campaign_id,
        )
    except WizardNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": exc.code}) from exc
    except WizardInvariantError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code}) from exc
    return await _wizard_state_out(db, state)


@router.post(
    "/service-campaigns/{campaign_id}/wizard/scenario/approve",
    response_model=WizardStateOut,
    dependencies=[Depends(require_permission("campaigns", "manage"))],
)
async def approve_wizard_scenario_route(
    campaign_id: str,
    body: ApproveWizardScenarioIn,
    db: DB,
    user: CurrentUser,
) -> WizardStateOut:
    org_id = _org_id(user)
    try:
        state = await load_wizard_state(
            db,
            org_id=org_id,
            service_campaign_id=campaign_id,
        )
        if (
            state.intake is None
            or state.generation is None
            or state.generation.operation_id != body.operation_id
            or state.generation.scenario_version_id != body.scenario_version_id
        ):
            raise WizardInvariantError("CURRENT_GENERATION_REQUIRED")
        await approve_scenario(
            db,
            ApproveScenario(
                org_id=org_id,
                operation_id=body.operation_id,
                scenario_version_id=body.scenario_version_id,
                expected_content_hash=body.expected_content_hash,
                approved_by=str(user.id),
                policy=wizard_operation_policy(state.intake.package_name),
            ),
        )
        state = await load_wizard_state(
            db,
            org_id=org_id,
            service_campaign_id=campaign_id,
        )
    except WizardNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": exc.code}) from exc
    except WizardInvariantError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code}) from exc
    except ScenarioGenerationRejected as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.reason_code, "path": exc.path},
        ) from exc
    return await _wizard_state_out(db, state)


@router.post(
    "/service-campaigns/{campaign_id}/start",
    response_model=StartCampaignOut,
    dependencies=[Depends(require_permission("campaigns", "execute"))],
)
async def start_service_campaign_route(
    campaign_id: str,
    body: StartCampaignIn,
    db: DB,
    user: CurrentUser,
) -> StartCampaignOut:
    result = await start_campaign(
        db,
        StartCampaign(
            org_id=_org_id(user),
            service_campaign_id=campaign_id,
            idempotency_key=body.idempotency_key,
            now=datetime.now(timezone.utc),
            policy=ReadinessPolicy(version="adl-readiness-v1"),
        ),
    )
    return StartCampaignOut(
        started=result.started,
        campaign_status=result.campaign.status,
        started_at=result.campaign.started_at,
        readiness_revision=result.snapshot.revision,
        readiness_status=result.snapshot.status,
        intent_id=result.intent.id if result.intent else None,
        checks=[
            ReadinessCheckOut(
                key=check.check_key,
                status=check.status,
                required=check.required,
                reason_code=check.reason_code,
                observed_at=check.observed_at,
                source_type=check.source_type,
                source_ref=check.source_ref,
                source_version=check.source_version,
                owner=check.owner,
                next_action=check.next_action,
            )
            for check in result.checks
        ],
    )


@router.post(
    "/service-campaigns/{campaign_id}/slots/materialize",
    response_model=MaterializeSlotsOut,
    dependencies=[Depends(require_permission("campaigns", "execute"))],
)
async def materialize_slots_route(
    campaign_id: str,
    db: DB,
    user: CurrentUser,
) -> MaterializeSlotsOut:
    try:
        slots = await materialize_service_slots(
            db,
            org_id=_org_id(user),
            service_campaign_id=campaign_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "CAMPAIGN_NOT_STARTED"}
        ) from exc
    return MaterializeSlotsOut(service_campaign_id=campaign_id, slot_count=len(slots))


@router.get(
    "/service-campaigns/{campaign_id}/progress",
    response_model=ServiceProgressOut,
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def service_progress_route(
    campaign_id: str,
    db: DB,
    user: CurrentUser,
) -> ServiceProgressOut:
    org_id = _org_id(user)
    exists = await db.scalar(
        select(ServiceCampaign.id).where(
            ServiceCampaign.id == campaign_id,
            ServiceCampaign.org_id == org_id,
        )
    )
    if exists is None:
        raise HTTPException(status_code=404, detail="Service campaign not found")
    rows = list(
        (
            await db.execute(
                select(RunSlot).where(
                    RunSlot.org_id == org_id,
                    RunSlot.service_campaign_id == campaign_id,
                )
            )
        ).scalars()
    )
    participants = list(
        (
            await db.execute(
                select(TrackParticipation).where(
                    TrackParticipation.org_id == org_id,
                    TrackParticipation.service_campaign_id == campaign_id,
                )
            )
        ).scalars()
    )
    terminal_states = {
        "succeeded",
        "failed",
        "blocked",
        "timeout",
        "missed",
        "cancelled",
    }
    return ServiceProgressOut(
        service={
            "planned": len(rows),
            "attempted": sum(row.execution_status != "scheduled" for row in rows),
            "terminal": sum(row.execution_status in terminal_states for row in rows),
            "missed": sum(row.execution_status == "missed" for row in rows),
        },
        app_quality={
            "evaluated": sum(
                row.app_verdict in {"pass", "fail", "inconclusive"} for row in rows
            ),
            "pass": sum(row.app_verdict == "pass" for row in rows),
            "fail": sum(row.app_verdict == "fail" for row in rows),
            "inconclusive": sum(row.app_verdict == "inconclusive" for row in rows),
        },
        play_participation={
            "identities": len(participants),
            "opted_in": sum(row.current_status == "opted_in" for row in participants),
            "lost": sum(row.current_status == "lost" for row in participants),
            "unknown": sum(row.current_status == "unknown" for row in participants),
        },
    )


@router.get(
    "/service-campaigns/{campaign_id}/lanes",
    response_model=ServiceLaneListOut,
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def list_service_lanes_route(
    campaign_id: str,
    db: DB,
    user: CurrentUser,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=12, ge=1, le=50),
) -> ServiceLaneListOut:
    org_id = _org_id(user)
    await _require_service_campaign(db, org_id=org_id, campaign_id=campaign_id)
    total = int(
        await db.scalar(
            select(func.count())
            .select_from(ServiceLane)
            .where(
                ServiceLane.org_id == org_id,
                ServiceLane.service_campaign_id == campaign_id,
            )
        )
        or 0
    )
    lane_rows = list(
        (
            await db.execute(
                select(ServiceLane)
                .where(
                    ServiceLane.org_id == org_id,
                    ServiceLane.service_campaign_id == campaign_id,
                )
                .order_by(ServiceLane.ordinal.asc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
    )
    lane_ids = [lane.id for lane in lane_rows]
    planned_by_lane: dict[str, int] = {}
    terminal_by_lane: dict[str, int] = {}
    reservation_by_lane: dict[str, int] = {}
    if lane_ids:
        terminal_states = {
            "succeeded",
            "failed",
            "blocked",
            "timeout",
            "missed",
            "cancelled",
        }
        slot_counts = await db.execute(
            select(
                RunSlot.lane_id,
                func.count(RunSlot.id),
                func.sum(RunSlot.execution_status.in_(terminal_states).cast(Integer)),
            )
            .where(
                RunSlot.org_id == org_id,
                RunSlot.service_campaign_id == campaign_id,
                RunSlot.lane_id.in_(lane_ids),
            )
            .group_by(RunSlot.lane_id)
        )
        for lane_id, planned, terminal in slot_counts:
            planned_by_lane[lane_id] = int(planned or 0)
            terminal_by_lane[lane_id] = int(terminal or 0)
        reservation_counts = await db.execute(
            select(DeviceReservation.lane_id, func.count(DeviceReservation.id))
            .where(
                DeviceReservation.org_id == org_id,
                DeviceReservation.service_campaign_id == campaign_id,
                DeviceReservation.lane_id.in_(lane_ids),
                DeviceReservation.state.in_(("active", "draining")),
            )
            .group_by(DeviceReservation.lane_id)
        )
        reservation_by_lane = {
            lane_id: int(count or 0) for lane_id, count in reservation_counts
        }
    return ServiceLaneListOut(
        items=[
            ServiceLaneSummaryOut(
                id=lane.id,
                ordinal=lane.ordinal,
                tester_label=lane.tester_label,
                planned_slots=planned_by_lane.get(lane.id, 0),
                terminal_slots=terminal_by_lane.get(lane.id, 0),
                active_reservation_count=reservation_by_lane.get(lane.id, 0),
            )
            for lane in lane_rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/service-campaigns/{campaign_id}/lanes/{lane_id}",
    response_model=ServiceLaneDetailOut,
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def get_service_lane_detail_route(
    campaign_id: str,
    lane_id: str,
    db: DB,
    user: CurrentUser,
    slot_offset: int = Query(default=0, ge=0),
    slot_limit: int = Query(default=14, ge=1, le=50),
) -> ServiceLaneDetailOut:
    org_id = _org_id(user)
    lane = (
        await db.execute(
            select(ServiceLane).where(
                ServiceLane.id == lane_id,
                ServiceLane.org_id == org_id,
                ServiceLane.service_campaign_id == campaign_id,
            )
        )
    ).scalar_one_or_none()
    if lane is None:
        raise HTTPException(status_code=404, detail="Service lane not found")
    slot_total = int(
        await db.scalar(
            select(func.count())
            .select_from(RunSlot)
            .where(
                RunSlot.org_id == org_id,
                RunSlot.service_campaign_id == campaign_id,
                RunSlot.lane_id == lane_id,
            )
        )
        or 0
    )
    slots = list(
        (
            await db.execute(
                select(RunSlot)
                .where(
                    RunSlot.org_id == org_id,
                    RunSlot.service_campaign_id == campaign_id,
                    RunSlot.lane_id == lane_id,
                )
                .order_by(RunSlot.service_day.asc(), RunSlot.id.asc())
                .offset(slot_offset)
                .limit(slot_limit)
            )
        ).scalars()
    )
    slot_ids = [slot.id for slot in slots]
    attempts = (
        list(
            (
                await db.execute(
                    select(RunAttempt)
                    .where(
                        RunAttempt.org_id == org_id,
                        RunAttempt.service_campaign_id == campaign_id,
                        RunAttempt.lane_id == lane_id,
                        RunAttempt.slot_id.in_(slot_ids),
                    )
                    .order_by(RunAttempt.slot_id.asc(), RunAttempt.attempt_no.asc())
                )
            ).scalars()
        )
        if slot_ids
        else []
    )
    attempt_ids = [attempt.id for attempt in attempts]
    evidence = (
        list(
            (
                await db.execute(
                    select(EvidenceItem)
                    .where(
                        EvidenceItem.org_id == org_id,
                        EvidenceItem.service_campaign_id == campaign_id,
                        EvidenceItem.run_attempt_id.in_(attempt_ids),
                    )
                    .order_by(
                        EvidenceItem.run_attempt_id.asc(),
                        EvidenceItem.step_path.asc(),
                        EvidenceItem.step_attempt_index.asc(),
                        EvidenceItem.id.asc(),
                    )
                )
            ).scalars()
        )
        if attempt_ids
        else []
    )
    evidence_by_attempt: dict[str, list[EvidenceItem]] = {}
    for item in evidence:
        evidence_by_attempt.setdefault(item.run_attempt_id, []).append(item)
    attempts_by_slot: dict[str, list[RunAttempt]] = {}
    for attempt in attempts:
        attempts_by_slot.setdefault(attempt.slot_id, []).append(attempt)
    reservations = list(
        (
            await db.execute(
                select(DeviceReservation)
                .where(
                    DeviceReservation.org_id == org_id,
                    DeviceReservation.service_campaign_id == campaign_id,
                    DeviceReservation.lane_id == lane_id,
                )
                .order_by(
                    DeviceReservation.created_at.asc(), DeviceReservation.id.asc()
                )
            )
        ).scalars()
    )
    return ServiceLaneDetailOut(
        id=lane.id,
        ordinal=lane.ordinal,
        tester_label=lane.tester_label,
        reservations=[
            ReservationSummaryOut(
                id=item.id,
                state=item.state,
                starts_at=item.starts_at,
                ends_at=item.ends_at,
                released_at=item.released_at,
            )
            for item in reservations
        ],
        slots=[
            RunSlotDetailOut(
                id=slot.id,
                service_day=slot.service_day,
                planned_at=slot.planned_at,
                execution_status=slot.execution_status,
                app_verdict=slot.app_verdict,
                play_participation_state=slot.play_participation_state,
                attempts=[
                    RunAttemptSummaryOut(
                        id=attempt.id,
                        attempt_no=attempt.attempt_no,
                        status=attempt.status,
                        outcome=attempt.outcome,
                        observed_build=attempt.observed_build,
                        failure_reason=attempt.failure_reason,
                        started_at=attempt.started_at,
                        finished_at=attempt.finished_at,
                        evidence=[
                            EvidenceSummaryOut(
                                id=item.id,
                                step_path=item.step_path,
                                step_attempt_index=item.step_attempt_index,
                                kind=item.kind,
                                status=item.status,
                                captured_at=item.captured_at,
                                capture_error_code=item.capture_error_code,
                            )
                            for item in evidence_by_attempt.get(attempt.id, [])
                        ],
                    )
                    for attempt in attempts_by_slot.get(slot.id, [])
                ],
            )
            for slot in slots
        ],
        slot_total=slot_total,
        slot_offset=slot_offset,
        slot_limit=slot_limit,
    )


@router.post(
    "/service-campaigns/{campaign_id}/evidence/{evidence_id}/download-url",
    response_model=EvidenceDownloadOut,
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def create_evidence_download_url_route(
    campaign_id: str,
    evidence_id: str,
    db: DB,
    user: CurrentUser,
) -> EvidenceDownloadOut:
    org_id = _org_id(user)
    await _require_service_campaign(db, org_id=org_id, campaign_id=campaign_id)
    item = (
        await db.execute(
            select(EvidenceItem).where(
                EvidenceItem.id == evidence_id,
                EvidenceItem.org_id == org_id,
                EvidenceItem.service_campaign_id == campaign_id,
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    retention_until = item.retention_until
    if retention_until.tzinfo is None:
        retention_until = retention_until.replace(tzinfo=timezone.utc)
    retention_elapsed = retention_until <= datetime.now(timezone.utc) and not item.pinned_by_report
    if item.status in {"expired", "deleted"} or retention_elapsed:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"code": "EVIDENCE_GONE"},
        )
    if item.status != "available" or not item.object_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "EVIDENCE_NOT_AVAILABLE", "evidence_status": item.status},
        )
    confirmed = os.getenv(
        "AI_DEVICE_LAB_PRIVATE_EVIDENCE_STORAGE_CONFIRMED", ""
    ).strip().lower() in {"1", "true", "yes"}
    if not confirmed:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "EVIDENCE_PRIVATE_STORAGE_UNCONFIRMED"},
        )

    from services.content.artifact_service import presigned_artifact_url

    content_type = item.content_type or "application/octet-stream"
    signed = presigned_artifact_url(
        item.object_key,
        ttl_seconds=300,
        content_type=content_type,
    )
    if not signed.get("url"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "EVIDENCE_STORAGE_UNAVAILABLE"},
        )
    return EvidenceDownloadOut(
        url=str(signed["url"]),
        expires_at=str(signed["expires_at"]),
        content_type=content_type,
    )


@router.get(
    "/service-campaigns/{campaign_id}/participation",
    response_model=ParticipationListOut,
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def list_campaign_participation_route(
    campaign_id: str,
    db: DB,
    user: CurrentUser,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
) -> ParticipationListOut:
    org_id = _org_id(user)
    await _require_service_campaign(db, org_id=org_id, campaign_id=campaign_id)
    scope = (
        TrackParticipation.org_id == org_id,
        TrackParticipation.service_campaign_id == campaign_id,
    )
    total = int(
        await db.scalar(
            select(func.count()).select_from(TrackParticipation).where(*scope)
        )
        or 0
    )
    rows = list(
        (
            await db.execute(
                select(TrackParticipation)
                .where(*scope)
                .order_by(
                    TrackParticipation.masked_label.asc(), TrackParticipation.id.asc()
                )
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
    )
    return ParticipationListOut(
        items=[
            ParticipationSummaryOut(
                id=item.id,
                masked_label=item.masked_label,
                track_name=item.track_name,
                current_status=item.current_status,
                evidence_grade=item.evidence_grade,
                active_segment_no=item.active_segment_no,
                last_observed_at=item.last_observed_at,
                gap_reason=item.gap_reason,
            )
            for item in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/service-campaigns/{campaign_id}/participation",
    response_model=ParticipationRecordOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("campaigns", "manage"))],
)
async def record_campaign_participation_route(
    campaign_id: str,
    body: RecordParticipationIn,
    db: DB,
    user: CurrentUser,
) -> ParticipationRecordOut:
    org_id = _org_id(user)
    campaign = (
        await db.execute(
            select(ServiceCampaign).where(
                ServiceCampaign.id == campaign_id,
                ServiceCampaign.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Service campaign not found")
    try:
        participant, event = await record_participation(
            db,
            RecordParticipation(
                org_id=org_id,
                package_name=campaign.package_name,
                track_name=body.track_name,
                pseudonymous_account_ref=body.pseudonymous_account_ref,
                masked_label=body.masked_label,
                event_type=body.event_type,
                source_type=body.source_type,
                source_ref=body.source_ref,
                evidence_ref=body.evidence_ref,
                evidence_grade=body.evidence_grade,
                observed_at=body.observed_at,
                recorded_by=str(user.id),
                reviewed_by=str(user.id) if body.approve else None,
                service_campaign_id=campaign_id,
                correction_of_id=body.correction_of_id,
                limitations=body.limitations,
            ),
        )
    except ParticipationInvariantError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "PARTICIPATION_EVIDENCE_REJECTED"},
        ) from exc
    return ParticipationRecordOut(
        participation=ParticipationSummaryOut(
            id=participant.id,
            masked_label=participant.masked_label,
            track_name=participant.track_name,
            current_status=participant.current_status,
            evidence_grade=participant.evidence_grade,
            active_segment_no=participant.active_segment_no,
            last_observed_at=participant.last_observed_at,
            gap_reason=participant.gap_reason,
        ),
        event_id=event.id,
        event_type=event.event_type,
        review_state=event.review_state,
        observed_at=event.observed_at,
    )


@router.get(
    "/service-campaigns/{campaign_id}/issues",
    response_model=IssueListOut,
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def list_campaign_issues_route(
    campaign_id: str,
    db: DB,
    user: CurrentUser,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
) -> IssueListOut:
    org_id = _org_id(user)
    await _require_service_campaign(db, org_id=org_id, campaign_id=campaign_id)
    scope = (
        AppIssue.org_id == org_id,
        AppIssue.service_campaign_id == campaign_id,
    )
    total = int(
        await db.scalar(select(func.count()).select_from(AppIssue).where(*scope)) or 0
    )
    issues = list(
        (
            await db.execute(
                select(AppIssue)
                .where(*scope)
                .order_by(AppIssue.created_at.desc(), AppIssue.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
    )
    counts: dict[str, int] = {}
    if issues:
        counts = {
            issue_id: int(count)
            for issue_id, count in (
                await db.execute(
                    select(RetestRequest.issue_id, func.count(RetestRequest.id))
                    .where(
                        RetestRequest.org_id == org_id,
                        RetestRequest.issue_id.in_([item.id for item in issues]),
                    )
                    .group_by(RetestRequest.issue_id)
                )
            ).all()
        }
    return IssueListOut(
        items=[
            IssueSummaryOut(
                id=item.id,
                source_attempt_id=item.source_attempt_id,
                source_build_id=item.source_build_id,
                source_scenario_version_id=item.source_scenario_version_id,
                severity=item.severity,
                assertion_key=item.assertion_key,
                expected=item.expected,
                actual=item.actual,
                reproduction=item.reproduction,
                fingerprint=item.fingerprint,
                status=item.status,
                retest_count=counts.get(item.id, 0),
                created_at=item.created_at,
            )
            for item in issues
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/service-campaigns/{campaign_id}/issues",
    response_model=IssueSummaryOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("campaigns", "execute"))],
)
async def create_campaign_issue_route(
    campaign_id: str,
    body: CreateIssueIn,
    db: DB,
    user: CurrentUser,
) -> IssueSummaryOut:
    org_id = _org_id(user)
    await _require_service_campaign(db, org_id=org_id, campaign_id=campaign_id)
    in_scope = await db.scalar(
        select(RunAttempt.id).where(
            RunAttempt.id == body.source_attempt_id,
            RunAttempt.org_id == org_id,
            RunAttempt.service_campaign_id == campaign_id,
        )
    )
    if in_scope is None:
        raise HTTPException(status_code=404, detail="Run attempt not found")
    try:
        issue = await create_issue(
            db,
            CreateIssue(
                org_id=org_id,
                source_attempt_id=body.source_attempt_id,
                severity=body.severity,
                assertion_key=body.assertion_key,
                expected=body.expected,
                actual=body.actual,
                reproduction=body.reproduction,
                created_by=str(user.id),
            ),
        )
    except QualityInvariantError as exc:
        raise HTTPException(status_code=409, detail={"code": "ISSUE_REJECTED"}) from exc
    return IssueSummaryOut.model_validate(issue, from_attributes=True)


@router.post(
    "/service-campaigns/{campaign_id}/issues/{issue_id}/retests",
    response_model=RetestRequestOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("campaigns", "execute"))],
)
async def request_campaign_retest_route(
    campaign_id: str,
    issue_id: str,
    body: RequestRetestIn,
    db: DB,
    user: CurrentUser,
) -> RetestRequestOut:
    org_id = _org_id(user)
    await _require_service_campaign(db, org_id=org_id, campaign_id=campaign_id)
    issue_exists = await db.scalar(
        select(AppIssue.id).where(
            AppIssue.id == issue_id,
            AppIssue.org_id == org_id,
            AppIssue.service_campaign_id == campaign_id,
        )
    )
    if issue_exists is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    lane_ids = set(body.lane_scope)
    scoped_lane_ids = set(
        (
            await db.execute(
                select(ServiceLane.id).where(
                    ServiceLane.org_id == org_id,
                    ServiceLane.service_campaign_id == campaign_id,
                    ServiceLane.id.in_(lane_ids),
                )
            )
        ).scalars()
    )
    if scoped_lane_ids != lane_ids:
        raise HTTPException(status_code=404, detail="Lane not found")
    try:
        retest = await request_retest(
            db,
            RequestRetest(
                org_id=org_id,
                issue_id=issue_id,
                target_build_id=body.target_build_id,
                target_scenario_version_id=body.target_scenario_version_id,
                lane_scope=tuple(body.lane_scope),
                idempotency_key=body.idempotency_key,
                consent_snapshot=body.consent,
                requested_by=str(user.id),
            ),
        )
    except QualityInvariantError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "RETEST_REJECTED"}
        ) from exc
    return RetestRequestOut.model_validate(retest, from_attributes=True)


@router.get(
    "/service-campaigns/{campaign_id}/reports",
    response_model=ReportListOut,
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def list_campaign_reports_route(
    campaign_id: str,
    db: DB,
    user: CurrentUser,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> ReportListOut:
    org_id = _org_id(user)
    await _require_service_campaign(db, org_id=org_id, campaign_id=campaign_id)
    scope = (
        ReportSnapshot.org_id == org_id,
        ReportSnapshot.service_campaign_id == campaign_id,
    )
    total = int(
        await db.scalar(select(func.count()).select_from(ReportSnapshot).where(*scope))
        or 0
    )
    rows = list(
        (
            await db.execute(
                select(ReportSnapshot)
                .where(*scope)
                .order_by(ReportSnapshot.version.desc(), ReportSnapshot.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
    )
    return ReportListOut(
        items=[
            ReportSummaryOut(
                id=item.id,
                version=item.version,
                schema_version=item.schema_version,
                cutoff_at=item.cutoff_at,
                builder_version=item.builder_version,
                summary={
                    key: item.manifest.get(key, {})
                    for key in (
                        "service",
                        "app_quality",
                        "play_participation",
                        "evidence",
                        "quota",
                    )
                },
                manifest_sha256=item.manifest_sha256,
                status=item.status,
                download_available=bool(
                    item.status == "published"
                    and item.pdf_object_key
                    and item.pdf_sha256
                ),
                pdf_sha256=item.pdf_sha256,
                created_at=item.created_at,
            )
            for item in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/service-campaigns/{campaign_id}/reports/{report_id}/publish",
    response_model=ReportSummaryOut,
    dependencies=[Depends(require_permission("campaigns", "manage"))],
)
async def publish_campaign_report_route(
    campaign_id: str,
    report_id: str,
    db: DB,
    user: CurrentUser,
) -> ReportSummaryOut:
    org_id = _org_id(user)
    report_exists = await db.scalar(
        select(ReportSnapshot.id).where(
            ReportSnapshot.id == report_id,
            ReportSnapshot.org_id == org_id,
            ReportSnapshot.service_campaign_id == campaign_id,
        )
    )
    if report_exists is None:
        raise HTTPException(status_code=404, detail="Report not found")
    try:
        report = await publish_report_pdf(db, org_id=org_id, report_id=report_id)
    except ReportPdfInvariantError as exc:
        code = (
            "REPORT_PRIVATE_STORAGE_UNAVAILABLE"
            if "storage" in str(exc)
            else "REPORT_PUBLISH_REJECTED"
        )
        http_status = 503 if code == "REPORT_PRIVATE_STORAGE_UNAVAILABLE" else 409
        raise HTTPException(status_code=http_status, detail={"code": code}) from exc
    return ReportSummaryOut(
        id=report.id,
        version=report.version,
        schema_version=report.schema_version,
        cutoff_at=report.cutoff_at,
        builder_version=report.builder_version,
        summary={
            key: report.manifest.get(key, {})
            for key in (
                "service",
                "app_quality",
                "play_participation",
                "evidence",
                "quota",
            )
        },
        manifest_sha256=report.manifest_sha256,
        status=report.status,
        download_available=True,
        pdf_sha256=report.pdf_sha256,
        created_at=report.created_at,
    )


@router.post(
    "/service-campaigns/{campaign_id}/reports/{report_id}/download-url",
    response_model=ReportDownloadOut,
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def create_report_download_url_route(
    campaign_id: str,
    report_id: str,
    db: DB,
    user: CurrentUser,
) -> ReportDownloadOut:
    org_id = _org_id(user)
    await _require_service_campaign(db, org_id=org_id, campaign_id=campaign_id)
    report = (
        await db.execute(
            select(ReportSnapshot).where(
                ReportSnapshot.id == report_id,
                ReportSnapshot.org_id == org_id,
                ReportSnapshot.service_campaign_id == campaign_id,
            )
        )
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if (
        report.status != "published"
        or not report.pdf_object_key
        or not report.pdf_sha256
    ):
        raise HTTPException(
            status_code=409,
            detail={"code": "REPORT_PDF_NOT_AVAILABLE"},
        )
    from services.content.artifact_service import presigned_artifact_url

    signed = presigned_artifact_url(
        report.pdf_object_key,
        ttl_seconds=300,
        content_type="application/pdf",
    )
    if not signed.get("url"):
        raise HTTPException(
            status_code=503,
            detail={"code": "REPORT_STORAGE_UNAVAILABLE"},
        )
    return ReportDownloadOut(
        url=str(signed["url"]),
        expires_at=str(signed["expires_at"]),
        content_type="application/pdf",
    )


@router.post(
    "/service-campaigns/{campaign_id}/lanes/{lane_id}/replace",
    response_model=FleetLifecycleOperationOut,
    dependencies=[Depends(require_permission("campaigns", "execute"))],
)
async def replace_lane_device_route(
    campaign_id: str,
    lane_id: str,
    body: ReplaceLaneDeviceIn,
    db: DB,
    user: CurrentUser,
) -> FleetLifecycleOperationOut:
    org_id = _org_id(user)
    await _require_service_campaign(db, org_id=org_id, campaign_id=campaign_id)
    try:
        operation = await replace_lane_device(
            db,
            ReplaceLaneDevice(
                org_id=org_id,
                service_campaign_id=campaign_id,
                lane_id=lane_id,
                new_device_id=body.new_device_id,
                idempotency_key=body.idempotency_key,
                actor_id=str(user.id),
                reason=body.reason,
                now=datetime.now(timezone.utc),
            ),
        )
    except LifecycleInvariantError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "REPLACEMENT_REJECTED"}
        ) from exc
    return _operation_out(operation)


@router.post(
    "/service-campaigns/{campaign_id}/operations/{operation_id}/complete-replacement",
    response_model=FleetLifecycleOperationOut,
    dependencies=[Depends(require_permission("campaigns", "execute"))],
)
async def complete_replacement_route(
    campaign_id: str,
    operation_id: str,
    db: DB,
    user: CurrentUser,
) -> FleetLifecycleOperationOut:
    org_id = _org_id(user)
    await _require_service_campaign(db, org_id=org_id, campaign_id=campaign_id)
    try:
        operation = await complete_device_replacement(
            db,
            org_id=org_id,
            service_campaign_id=campaign_id,
            operation_id=operation_id,
            now=datetime.now(timezone.utc),
        )
    except LifecycleInvariantError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "REPLACEMENT_NOT_DRAINED"}
        ) from exc
    return _operation_out(operation)


@router.post(
    "/service-campaigns/{campaign_id}/extend",
    response_model=ServiceExtensionOut,
    dependencies=[Depends(require_permission("campaigns", "execute"))],
)
async def extend_service_campaign_route(
    campaign_id: str,
    body: ExtendServiceCampaignIn,
    db: DB,
    user: CurrentUser,
) -> ServiceExtensionOut:
    org_id = _org_id(user)
    await _require_service_campaign(db, org_id=org_id, campaign_id=campaign_id)
    try:
        extension = await extend_service_campaign(
            db,
            ExtendServiceCampaign(
                org_id=org_id,
                service_campaign_id=campaign_id,
                order_id=body.order_id,
                entitlement_id=body.entitlement_id,
                idempotency_key=body.idempotency_key,
                actor_id=str(user.id),
                added_service_days=body.added_service_days,
                consent_snapshot=body.consent.model_dump(mode="json"),
                now=datetime.now(timezone.utc),
            ),
        )
    except LifecycleInvariantError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "EXTENSION_REJECTED"}
        ) from exc
    return ServiceExtensionOut.model_validate(extension, from_attributes=True)


@router.post(
    "/service-campaigns/{campaign_id}/cancel",
    response_model=FleetLifecycleOperationOut,
    dependencies=[Depends(require_permission("campaigns", "execute"))],
)
async def cancel_service_campaign_route(
    campaign_id: str,
    body: CancelServiceCampaignIn,
    db: DB,
    user: CurrentUser,
) -> FleetLifecycleOperationOut:
    org_id = _org_id(user)
    await _require_service_campaign(db, org_id=org_id, campaign_id=campaign_id)
    try:
        operation = await cancel_service_campaign(
            db,
            org_id=org_id,
            service_campaign_id=campaign_id,
            idempotency_key=body.idempotency_key,
            actor_id=str(user.id),
            reason=body.reason,
            now=datetime.now(timezone.utc),
        )
    except LifecycleInvariantError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "CANCELLATION_REJECTED"}
        ) from exc
    return _operation_out(operation)


@router.post(
    "/service-campaigns/{campaign_id}/expire",
    response_model=FleetLifecycleOperationOut,
    dependencies=[Depends(require_permission("campaigns", "execute"))],
)
async def expire_service_campaign_route(
    campaign_id: str,
    body: CancelServiceCampaignIn,
    db: DB,
    user: CurrentUser,
) -> FleetLifecycleOperationOut:
    org_id = _org_id(user)
    await _require_service_campaign(db, org_id=org_id, campaign_id=campaign_id)
    try:
        operation = await expire_service_campaign(
            db,
            org_id=org_id,
            service_campaign_id=campaign_id,
            idempotency_key=body.idempotency_key,
            actor_id=str(user.id),
            reason=body.reason,
            now=datetime.now(timezone.utc),
        )
    except LifecycleInvariantError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "EXPIRY_REJECTED"}
        ) from exc
    return _operation_out(operation)


@router.post(
    "/service-campaigns/{campaign_id}/operations/{operation_id}/complete-cancellation",
    response_model=FleetLifecycleOperationOut,
    dependencies=[Depends(require_permission("campaigns", "execute"))],
)
async def complete_cancellation_route(
    campaign_id: str,
    operation_id: str,
    db: DB,
    user: CurrentUser,
) -> FleetLifecycleOperationOut:
    org_id = _org_id(user)
    await _require_service_campaign(db, org_id=org_id, campaign_id=campaign_id)
    try:
        operation = await complete_campaign_cancellation(
            db,
            org_id=org_id,
            service_campaign_id=campaign_id,
            operation_id=operation_id,
            now=datetime.now(timezone.utc),
        )
    except LifecycleInvariantError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "CANCELLATION_NOT_DRAINED"}
        ) from exc
    return _operation_out(operation)


@router.post(
    "/kpi/definitions",
    response_model=KpiDefinitionOut,
    dependencies=[Depends(require_permission("campaigns", "manage"))],
)
async def sign_kpi_definition_route(
    body: SignKpiDefinitionIn,
    db: DB,
    user: CurrentUser,
) -> KpiDefinitionOut:
    try:
        definition = await sign_kpi_definition(
            db,
            SignKpiDefinition(
                org_id=_org_id(user),
                version=body.version,
                definitions=body.definitions,
                signed_by=str(user.id),
                signed_at=datetime.now(timezone.utc),
            ),
        )
    except KpiInvariantError as exc:
        raise HTTPException(
            status_code=422, detail={"code": "INVALID_KPI_DEFINITION"}
        ) from exc
    return KpiDefinitionOut.model_validate(definition, from_attributes=True)


@router.post(
    "/kpi/cohorts",
    response_model=KpiCohortOut,
    dependencies=[Depends(require_permission("campaigns", "manage"))],
)
async def freeze_kpi_cohort_route(
    body: FreezeKpiCohortIn,
    db: DB,
    user: CurrentUser,
) -> KpiCohortOut:
    now = datetime.now(timezone.utc)
    try:
        cohort = await freeze_kpi_cohort(
            db,
            FreezeKpiCohort(
                org_id=_org_id(user),
                cohort_key=body.cohort_key,
                definition_id=body.definition_id,
                source_kind=body.source_kind,
                window_start=body.window_start,
                window_end=body.window_end,
                timezone=body.timezone,
                service_campaign_ids=tuple(body.service_campaign_ids),
                created_by=str(user.id),
                frozen_at=now,
            ),
        )
    except KpiInvariantError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "KPI_COHORT_REJECTED"}
        ) from exc
    return KpiCohortOut.model_validate(cohort, from_attributes=True)


@router.post(
    "/kpi/assistance-events",
    response_model=KpiAssistanceOut,
    dependencies=[Depends(require_permission("campaigns", "execute"))],
)
async def record_kpi_assistance_route(
    body: RecordKpiAssistanceIn,
    db: DB,
    user: CurrentUser,
) -> KpiAssistanceOut:
    try:
        event = await record_kpi_assistance(
            db,
            RecordAssistance(
                org_id=_org_id(user),
                event_id=body.event_id,
                service_campaign_id=body.service_campaign_id,
                actor_id=str(user.id),
                assistance_type=body.assistance_type,
                classification=body.classification,
                reason=body.reason,
                occurred_at=body.occurred_at,
            ),
        )
    except KpiInvariantError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "KPI_ASSISTANCE_REJECTED"}
        ) from exc
    return KpiAssistanceOut.model_validate(event, from_attributes=True)


@router.post(
    "/kpi/cohorts/{cohort_id}/snapshots",
    response_model=KpiSnapshotOut,
    dependencies=[Depends(require_permission("campaigns", "manage"))],
)
async def compute_kpi_snapshot_route(
    cohort_id: str,
    body: ComputeKpiSnapshotIn,
    db: DB,
    user: CurrentUser,
) -> KpiSnapshotOut:
    org_id = _org_id(user)
    exists = await db.scalar(
        select(KpiCohort.id).where(
            KpiCohort.id == cohort_id, KpiCohort.org_id == org_id
        )
    )
    if exists is None:
        raise HTTPException(status_code=404, detail="KPI cohort not found")
    try:
        snapshot = await compute_kpi_snapshot(
            db,
            org_id=org_id,
            cohort_id=cohort_id,
            query_version=body.query_version,
            data_freshness_at=datetime.now(timezone.utc),
        )
    except KpiInvariantError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "KPI_SNAPSHOT_REJECTED"}
        ) from exc
    return KpiSnapshotOut.model_validate(snapshot, from_attributes=True)


@router.post(
    "/acceptance/candidates",
    response_model=AcceptanceCandidateOut,
    dependencies=[Depends(require_permission("campaigns", "manage"))],
)
async def build_acceptance_candidate_route(
    body: BuildAcceptanceCandidateIn,
    db: DB,
    user: CurrentUser,
) -> AcceptanceCandidateOut:
    try:
        candidate = await build_acceptance_candidate(
            db,
            BuildAcceptanceCandidate(
                org_id=_org_id(user),
                version=body.version,
                source_kind=body.source_kind,
                environment=body.environment,
                commit_sha=body.commit_sha,
                schema_version=body.schema_version,
                rollback_owner=body.rollback_owner,
                oncall_owner=body.oncall_owner,
                created_by=str(user.id),
                frozen_at=datetime.now(timezone.utc),
                requirements=tuple(
                    RequirementEvidence(
                        requirement_key=item.requirement_key,
                        adl_id=item.adl_id,
                        acceptance_id=item.acceptance_id,
                        test_id=item.test_id,
                        expected=item.expected,
                        observed=item.observed,
                        status=item.status,
                        required_evidence_level=item.required_evidence_level,
                        observed_evidence_level=item.observed_evidence_level,
                        evidence_refs=tuple(item.evidence_refs),
                        reviewer_id=item.reviewer_id,
                        executed_at=item.executed_at,
                        blocker=item.blocker,
                    )
                    for item in body.requirements
                ),
            ),
        )
    except AcceptanceInvariantError as exc:
        raise HTTPException(
            status_code=422, detail={"code": "INVALID_ACCEPTANCE_PACK"}
        ) from exc
    return AcceptanceCandidateOut.model_validate(candidate, from_attributes=True)


@router.post(
    "/acceptance/candidates/{candidate_id}/evaluate",
    response_model=AcceptanceDecisionOut,
    dependencies=[Depends(require_permission("campaigns", "manage"))],
)
async def evaluate_acceptance_candidate_route(
    candidate_id: str,
    body: EvaluateAcceptanceCandidateIn,
    db: DB,
    user: CurrentUser,
) -> AcceptanceDecisionOut:
    org_id = _org_id(user)
    exists = await db.scalar(
        select(AcceptanceCandidate.id).where(
            AcceptanceCandidate.id == candidate_id,
            AcceptanceCandidate.org_id == org_id,
        )
    )
    if exists is None:
        raise HTTPException(status_code=404, detail="Acceptance candidate not found")
    try:
        decision = await evaluate_acceptance_candidate(
            db,
            org_id=org_id,
            candidate_id=candidate_id,
            evaluation_key=body.evaluation_key,
            evaluated_at=datetime.now(timezone.utc),
        )
    except AcceptanceInvariantError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "ACCEPTANCE_EVALUATION_REJECTED"}
        ) from exc
    return AcceptanceDecisionOut.model_validate(decision, from_attributes=True)
