from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class ClientFunnelEventIn(BaseModel):
    event_id: str = Field(min_length=8, max_length=128)
    event_name: str = Field(pattern="^(landing_view|start_click)$")
    occurred_at: datetime
    attribution: dict[str, str] = Field(default_factory=dict)


class ServiceCampaignCreateIn(BaseModel):
    creation_intent_key: str = Field(min_length=8, max_length=128)
    runtime_campaign_id: str
    package_name: str = Field(min_length=3, max_length=255)
    timezone: str = Field(min_length=1, max_length=64)
    plan_version: str = Field(min_length=1, max_length=64)
    acquisition_events: list[ClientFunnelEventIn] = Field(
        default_factory=list, max_length=2
    )


class ServiceCampaignOut(BaseModel):
    id: str
    runtime_campaign_id: str
    package_name: str
    timezone: str
    plan_version: str
    status: str
    lane_count: int
    started_at: datetime | None
    end_at: datetime | None


class FunnelEventOut(BaseModel):
    event_id: str
    event_name: str
    source_type: str
    source_ref: str | None
    attribution: dict[str, str]
    source_occurred_at: datetime


class CampaignFunnelOut(BaseModel):
    service_campaign_id: str
    acquisition_id: str
    completed_steps: int
    next_step: str | None
    events: list[FunnelEventOut]


class WizardDraftBuildIn(BaseModel):
    version_name: str = Field(min_length=1, max_length=128)
    version_code: str = Field(min_length=1, max_length=64)
    source_kind: str = Field(pattern="^(closed_track|uploaded_artifact)$")
    source_ref: str | None = Field(default=None, max_length=512)
    checksum_sha256: str | None = Field(default=None, min_length=64, max_length=64)


class SaveWizardDraftIn(BaseModel):
    expected_revision: int = Field(ge=0)
    package_name: str = Field(min_length=3, max_length=255)
    closed_track_link: str = Field(min_length=8, max_length=4000)
    test_goal: str = Field(min_length=1, max_length=8000)
    test_environment: dict = Field(default_factory=dict)
    build: WizardDraftBuildIn


class WizardIntakeOut(BaseModel):
    id: str
    revision: int
    input_version: int
    package_name: str
    closed_track_link: str
    test_goal: str
    test_environment: dict
    status: str
    build: dict


class WizardGenerationOut(BaseModel):
    operation_id: str
    status: str
    error_code: str | None
    scenario_version_id: str | None
    content_hash: str | None
    scenario: dict | None


class WizardApprovalOut(BaseModel):
    id: str
    scenario_version_id: str
    content_hash: str
    policy_version: str
    assertions: list[dict]
    allowed_operations: list[str]
    approved_at: datetime


class WizardPaymentOut(BaseModel):
    provider_configured: bool
    provider: str | None
    amount_minor: int | None
    currency: str | None
    pricing_version: str | None
    policy_version: str
    quota: dict[str, int]
    blocker_code: str | None
    order: dict | None
    checkout_status: str | None
    checkout_expires_at: datetime | None
    checkout_error_code: str | None
    entitlement: dict | None


class StartWizardCheckoutIn(BaseModel):
    approval_id: str = Field(min_length=1, max_length=36)
    idempotency_key: str = Field(min_length=8, max_length=128)


class WizardCheckoutOut(BaseModel):
    order_id: str
    intent_id: str
    status: str
    checkout_url: str | None
    expires_at: datetime | None
    blocker_code: str | None


class WizardStateOut(BaseModel):
    campaign: ServiceCampaignOut
    current_step: str
    intake: WizardIntakeOut | None
    generation: WizardGenerationOut | None
    approval: WizardApprovalOut | None
    payment: WizardPaymentOut


class PaymentReconciliationOut(BaseModel):
    id: str
    order_id: str
    provider: str
    reason_code: str
    status: str
    attempts: int
    last_error_code: str | None
    available_at: datetime
    resolved_at: datetime | None
    created_at: datetime


class PaymentReconciliationListOut(BaseModel):
    items: list[PaymentReconciliationOut]
    total: int
    offset: int
    limit: int


class StartWizardGenerationIn(BaseModel):
    operation_id: str = Field(min_length=8, max_length=128)


class ApproveWizardScenarioIn(BaseModel):
    operation_id: str = Field(min_length=8, max_length=128)
    scenario_version_id: str = Field(min_length=1, max_length=64)
    expected_content_hash: str = Field(min_length=64, max_length=64)


class StartCampaignIn(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128)


class ReadinessCheckOut(BaseModel):
    key: str
    status: str
    required: bool
    reason_code: str
    observed_at: datetime
    source_type: str
    source_ref: str | None
    source_version: str | None
    owner: str
    next_action: str | None


class StartCampaignOut(BaseModel):
    started: bool
    campaign_status: str
    started_at: datetime | None
    readiness_revision: int
    readiness_status: str
    intent_id: str | None
    checks: list[ReadinessCheckOut]


class MaterializeSlotsOut(BaseModel):
    service_campaign_id: str
    slot_count: int


class ServiceProgressOut(BaseModel):
    service: dict[str, int | str]
    app_quality: dict[str, int]
    play_participation: dict[str, int]


class ServiceLaneSummaryOut(BaseModel):
    id: str
    ordinal: int
    tester_label: str
    planned_slots: int
    terminal_slots: int
    active_reservation_count: int


class ServiceLaneListOut(BaseModel):
    items: list[ServiceLaneSummaryOut]
    total: int
    offset: int
    limit: int


class EvidenceSummaryOut(BaseModel):
    id: str
    step_path: str
    step_attempt_index: int
    kind: str
    status: str
    captured_at: datetime
    capture_error_code: str | None


class EvidenceDownloadOut(BaseModel):
    url: str
    expires_at: str
    content_type: str


class RunAttemptSummaryOut(BaseModel):
    id: str
    attempt_no: int
    status: str
    outcome: str | None
    observed_build: dict
    failure_reason: str | None
    started_at: datetime | None
    finished_at: datetime | None
    evidence: list[EvidenceSummaryOut]


class RunSlotDetailOut(BaseModel):
    id: str
    service_day: int
    planned_at: datetime
    execution_status: str
    app_verdict: str | None
    play_participation_state: str
    attempts: list[RunAttemptSummaryOut]


class ReservationSummaryOut(BaseModel):
    id: str
    state: str
    starts_at: datetime
    ends_at: datetime
    released_at: datetime | None


class DeviceHygieneResultIn(BaseModel):
    target_type: str = Field(pattern="^(physical|emulator)$")
    protocol_version: str = Field(min_length=1, max_length=64)
    reset_succeeded: bool
    readback_clean: bool
    evidence_ref: str | None = Field(default=None, max_length=255)
    active_run: bool = False
    service_campaign_id: str | None = Field(default=None, max_length=64)


class DeviceHygieneResultOut(BaseModel):
    device_id: str
    target_type: str
    state: str
    protocol_version: str
    reason_code: str
    verification_evidence_ref: str | None


class CreateFarmRunIn(BaseModel):
    lane_id: str = Field(min_length=1, max_length=64)
    slot_id: str = Field(min_length=1, max_length=64)
    execution_id: str = Field(min_length=1, max_length=64)
    scenario_version_id: str = Field(min_length=1, max_length=64)
    app_build_id: str = Field(min_length=1, max_length=64)
    reservation_id: str = Field(min_length=1, max_length=64)
    approval_id: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=128)
    deadline_at: datetime
    reason: str = Field(default="scheduled", min_length=1, max_length=64)


class FarmRunOut(BaseModel):
    job_id: str
    run_attempt_id: str
    execution_id: str
    slot_id: str
    lane_id: str
    device_id: str
    reservation_id: str
    scenario_version_id: str
    scenario_hash: str
    policy_version: str
    schema_version: str
    status: str
    verdict: str | None
    terminal_reason: str | None
    deadline_at: datetime


class FarmEventIn(BaseModel):
    schema_version: str = Field(pattern="^adl-farm-event-v1$")
    execution_id: str = Field(min_length=1, max_length=36)
    source: str = Field(min_length=1, max_length=64)
    event_id: str = Field(min_length=1, max_length=128)
    event_type: str = Field(
        pattern="^(accepted|running|step|assertion|uncertain|blocked|deadline|cancelled|completed)$"
    )
    occurred_at: datetime
    sequence: int | None = Field(default=None, ge=0)
    reason_code: str | None = Field(default=None, pattern="^[A-Z][A-Z0-9_]{0,127}$")
    assertion_passed: bool | None = None
    step_path: str | None = Field(default=None, max_length=255)
    step_attempt_index: int | None = Field(default=None, ge=0)
    artifact_refs: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("artifact_refs")
    @classmethod
    def validate_artifact_refs(cls, refs: list[str]) -> list[str]:
        if any(not ref or len(ref.encode("utf-8")) > 1024 for ref in refs):
            raise ValueError("artifact references must be 1..1024 UTF-8 bytes")
        return refs


class FarmEventOut(BaseModel):
    event_id: str
    job_id: str
    job_status: str
    verdict: str | None
    terminal_reason: str | None


class ServiceLaneDetailOut(BaseModel):
    id: str
    ordinal: int
    tester_label: str
    reservations: list[ReservationSummaryOut]
    slots: list[RunSlotDetailOut]
    slot_total: int
    slot_offset: int
    slot_limit: int


class ParticipationSummaryOut(BaseModel):
    id: str
    masked_label: str
    track_name: str
    current_status: str
    evidence_grade: str
    active_segment_no: int
    last_observed_at: datetime | None
    gap_reason: str | None


class ParticipationListOut(BaseModel):
    items: list[ParticipationSummaryOut]
    total: int
    offset: int
    limit: int


class RecordParticipationIn(BaseModel):
    pseudonymous_account_ref: str = Field(min_length=1, max_length=128)
    masked_label: str = Field(min_length=1, max_length=128)
    track_name: str = Field(min_length=1, max_length=64)
    event_type: str = Field(
        pattern="^(invited|opted_in|installed|opened|lost|rejoined|unknown|corrected)$"
    )
    source_type: str = Field(min_length=1, max_length=32)
    source_ref: str | None = Field(default=None, max_length=255)
    evidence_ref: str | None = Field(default=None, max_length=255)
    evidence_grade: str = Field(
        pattern="^(none|self_attested|operator_attested|provider_verified)$"
    )
    observed_at: datetime
    approve: bool = False
    correction_of_id: str | None = None
    limitations: str | None = Field(default=None, max_length=4000)


class ParticipationRecordOut(BaseModel):
    participation: ParticipationSummaryOut
    event_id: str
    event_type: str
    review_state: str
    observed_at: datetime


class CreateIssueIn(BaseModel):
    source_attempt_id: str = Field(min_length=1, max_length=64)
    severity: str = Field(pattern="^(minor|major|critical)$")
    assertion_key: str = Field(min_length=1, max_length=255)
    expected: str = Field(min_length=1, max_length=4000)
    actual: str = Field(min_length=1, max_length=4000)
    reproduction: dict


class IssueSummaryOut(BaseModel):
    id: str
    source_attempt_id: str
    source_build_id: str
    source_scenario_version_id: str
    severity: str
    assertion_key: str
    expected: str
    actual: str
    reproduction: dict
    fingerprint: str
    status: str
    retest_count: int = 0
    created_at: datetime


class IssueListOut(BaseModel):
    items: list[IssueSummaryOut]
    total: int
    offset: int
    limit: int


class RequestRetestIn(BaseModel):
    target_build_id: str = Field(min_length=1, max_length=64)
    target_scenario_version_id: str = Field(min_length=1, max_length=64)
    lane_scope: list[str] = Field(min_length=1, max_length=12)
    idempotency_key: str = Field(min_length=8, max_length=128)
    consent: dict


class RetestRequestOut(BaseModel):
    id: str
    issue_id: str
    source_attempt_id: str
    target_build_id: str
    target_scenario_version_id: str
    lane_scope: list[str]
    status: str
    new_attempt_id: str | None
    verdict: str | None
    verdict_reason: str | None
    created_at: datetime


class ReportSummaryOut(BaseModel):
    id: str
    version: int
    schema_version: str
    cutoff_at: datetime
    builder_version: str
    summary: dict
    manifest_sha256: str
    status: str
    download_available: bool
    pdf_sha256: str | None
    created_at: datetime


class ReportListOut(BaseModel):
    items: list[ReportSummaryOut]
    total: int
    offset: int
    limit: int


class ReportDownloadOut(BaseModel):
    url: str
    expires_at: str
    content_type: str


class ReplaceLaneDeviceIn(BaseModel):
    new_device_id: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=128)
    reason: str = Field(min_length=3, max_length=1000)


class CancelServiceCampaignIn(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    reason: str = Field(min_length=3, max_length=1000)


class ExtensionConsentIn(BaseModel):
    accepted: bool
    accepted_at: datetime
    policy_version: str = Field(min_length=1, max_length=64)
    pricing_version: str = Field(min_length=1, max_length=64)
    amount_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)


class ExtendServiceCampaignIn(BaseModel):
    order_id: str = Field(min_length=1, max_length=64)
    entitlement_id: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=128)
    added_service_days: int = Field(gt=0, le=365)
    consent: ExtensionConsentIn


class FleetLifecycleOperationOut(BaseModel):
    id: str
    service_campaign_id: str
    lane_id: str | None
    operation_type: str
    status: str
    checkpoint: str
    old_reservation_id: str | None
    new_reservation_id: str | None
    reason: str
    error_code: str | None
    created_at: datetime
    updated_at: datetime


class ServiceExtensionOut(BaseModel):
    id: str
    service_campaign_id: str
    previous_end_at: datetime
    new_end_at: datetime
    added_service_days: int
    order_id: str
    entitlement_id: str
    created_at: datetime


class SignKpiDefinitionIn(BaseModel):
    version: str = Field(min_length=1, max_length=64)
    definitions: dict[str, str]


class KpiDefinitionOut(BaseModel):
    id: str
    version: str
    definitions: dict
    status: str
    signed_by: str | None
    signed_at: datetime | None


class FreezeKpiCohortIn(BaseModel):
    cohort_key: str = Field(min_length=1, max_length=128)
    definition_id: str
    source_kind: str
    window_start: datetime
    window_end: datetime
    timezone: str = Field(min_length=1, max_length=64)
    service_campaign_ids: list[str] = Field(min_length=1)


class KpiCohortOut(BaseModel):
    id: str
    cohort_key: str
    definition_id: str
    source_kind: str
    window_start: datetime
    window_end: datetime
    timezone: str
    status: str
    frozen_at: datetime | None


class RecordKpiAssistanceIn(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    service_campaign_id: str
    assistance_type: str = Field(min_length=1, max_length=64)
    classification: str
    reason: str = Field(min_length=3, max_length=1000)
    occurred_at: datetime


class KpiAssistanceOut(BaseModel):
    id: str
    event_id: str
    service_campaign_id: str
    actor_id: str
    assistance_type: str
    classification: str
    reason: str
    occurred_at: datetime


class ComputeKpiSnapshotIn(BaseModel):
    query_version: str = Field(min_length=1, max_length=64)


class KpiSnapshotOut(BaseModel):
    id: str
    cohort_id: str
    query_version: str
    source_kind: str
    result_status: str
    self_serve_numerator: int
    self_serve_denominator: int
    trace_numerator: int
    trace_denominator: int
    details: dict
    data_freshness_at: datetime


class AcceptanceRequirementIn(BaseModel):
    requirement_key: str = Field(min_length=1, max_length=128)
    adl_id: str = Field(min_length=6, max_length=16)
    acceptance_id: str = Field(min_length=1, max_length=32)
    test_id: str = Field(min_length=1, max_length=32)
    expected: str = Field(min_length=1, max_length=4000)
    observed: str = Field(min_length=1, max_length=4000)
    status: str
    required_evidence_level: str
    observed_evidence_level: str
    evidence_refs: list[str]
    reviewer_id: str | None = None
    executed_at: datetime | None = None
    blocker: str | None = None


class BuildAcceptanceCandidateIn(BaseModel):
    version: str = Field(min_length=1, max_length=64)
    source_kind: str
    environment: str = Field(min_length=1, max_length=64)
    commit_sha: str = Field(min_length=1, max_length=64)
    schema_version: str = Field(min_length=1, max_length=64)
    rollback_owner: str | None = Field(default=None, max_length=255)
    oncall_owner: str | None = Field(default=None, max_length=255)
    requirements: list[AcceptanceRequirementIn]


class AcceptanceCandidateOut(BaseModel):
    id: str
    version: str
    source_kind: str
    environment: str
    commit_sha: str
    schema_version: str
    status: str
    rollback_owner: str | None
    oncall_owner: str | None
    frozen_at: datetime | None


class EvaluateAcceptanceCandidateIn(BaseModel):
    evaluation_key: str = Field(min_length=8, max_length=128)


class AcceptanceDecisionOut(BaseModel):
    id: str
    candidate_id: str
    evaluation_key: str
    verdict: str
    blockers: list[dict]
    requirement_summary: dict
    pack_sha256: str
    signer_snapshot: dict
    rationale: str
    evaluated_at: datetime
