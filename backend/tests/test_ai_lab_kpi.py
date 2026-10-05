from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from db.models.ai_device_lab import RunAttempt
from db.models.ai_device_lab_billing import ServiceOrder
from db.models.ai_device_lab_kpi import KpiAssistanceEvent, KpiSnapshot
from db.models.ai_device_lab_runtime import ReadinessSnapshot
from db.models.campaign import Campaign
from db.models.execution import Execution
from db.models.execution_step import ExecutionStep
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
from services.ai_device_lab.service_campaigns import CreateServiceCampaign, create_service_campaign
from tenancy.context import tenant_context
from tests.tenancy_test_support import ORG_A, ORG_B, USER_A, seed_two_org_fixture


async def _seed_campaign(db, *, runtime_campaign_id: str, suffix: str):
    return await create_service_campaign(
        db,
        CreateServiceCampaign(
            org_id=ORG_A,
            owner_id=USER_A,
            runtime_campaign_id=runtime_campaign_id,
            package_name=f"com.example.{suffix}",
            timezone="UTC",
            plan_version="adl-14d-v1",
        ),
    )


@pytest.mark.asyncio
async def test_kpi_snapshot_reconciles_paid_readiness_assistance_and_missing_trace(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    window_start = datetime(2026, 10, 4, tzinfo=timezone.utc)
    window_end = window_start + timedelta(days=1)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            db.add(
                Campaign(
                    id="camp-a-kpi-2",
                    name="KPI campaign 2",
                    name_lower="kpi campaign 2",
                    user_id=USER_A,
                    org_id=ORG_A,
                    created_at=window_start,
                    updated_at=window_start,
                )
            )
            await db.flush()
            campaign_1 = await _seed_campaign(
                db, runtime_campaign_id=seeded["campaign_a"], suffix="kpi.one"
            )
            campaign_2 = await _seed_campaign(
                db, runtime_campaign_id="camp-a-kpi-2", suffix="kpi.two"
            )
            definition = await sign_kpi_definition(
                db,
                SignKpiDefinition(
                    org_id=ORG_A,
                    version="kpi-v1",
                    definitions={
                        "self_serve_onboarding": "paid+ready without completion assistance",
                        "run_with_trace": "terminal execution with persisted step",
                        "window_timezone": "UTC",
                    },
                    signed_by=USER_A,
                    signed_at=window_start,
                ),
            )
            cohort = await freeze_kpi_cohort(
                db,
                FreezeKpiCohort(
                    org_id=ORG_A,
                    cohort_key="fixture-cohort-oct-04",
                    definition_id=definition.id,
                    source_kind="fixture",
                    window_start=window_start,
                    window_end=window_end,
                    timezone="UTC",
                    service_campaign_ids=(campaign_1.id, campaign_2.id),
                    created_by=USER_A,
                    frozen_at=window_start,
                ),
            )
            repeated_cohort = await freeze_kpi_cohort(
                db,
                FreezeKpiCohort(
                    org_id=ORG_A,
                    cohort_key="fixture-cohort-oct-04",
                    definition_id=definition.id,
                    source_kind="fixture",
                    window_start=window_start,
                    window_end=window_end,
                    timezone="UTC",
                    service_campaign_ids=(campaign_2.id, campaign_1.id),
                    created_by=USER_A,
                    frozen_at=window_start,
                ),
            )
            assert repeated_cohort.id == cohort.id
            with pytest.raises(KpiInvariantError, match="cohort key"):
                await freeze_kpi_cohort(
                    db,
                    FreezeKpiCohort(
                        org_id=ORG_A,
                        cohort_key="fixture-cohort-oct-04",
                        definition_id=definition.id,
                        source_kind="fixture",
                        window_start=window_start,
                        window_end=window_end,
                        timezone="UTC",
                        service_campaign_ids=(campaign_1.id,),
                        created_by=USER_A,
                        frozen_at=window_start,
                    ),
                )
            for index, campaign in enumerate((campaign_1, campaign_2), start=1):
                db.add(
                    ServiceOrder(
                        org_id=ORG_A,
                        service_campaign_id=campaign.id,
                        idempotency_key=f"kpi-order-{index}",
                        plan_version=campaign.plan_version,
                        pricing_version="pricing-v1",
                        policy_version="policy-v1",
                        quota_snapshot={"slots": 168},
                        amount_minor=10000,
                        currency="USD",
                        status="paid",
                        created_by=USER_A,
                        paid_at=window_start + timedelta(hours=index),
                    )
                )
                db.add(
                    ReadinessSnapshot(
                        org_id=ORG_A,
                        service_campaign_id=campaign.id,
                        revision=1,
                        policy_version="readiness-v1",
                        status="ready",
                        observed_at=window_start + timedelta(hours=index + 2),
                        expires_at=window_end,
                    )
                )
            review_event = await record_kpi_assistance(
                db,
                RecordAssistance(
                    org_id=ORG_A,
                    event_id="assist-review-only",
                    service_campaign_id=campaign_1.id,
                    actor_id=USER_A,
                    assistance_type="evidence_review",
                    classification="review_only",
                    reason="required service evidence review",
                    occurred_at=window_start + timedelta(hours=3),
                ),
            )
            repeated_review = await record_kpi_assistance(
                db,
                RecordAssistance(
                    org_id=ORG_A,
                    event_id="assist-review-only",
                    service_campaign_id=campaign_1.id,
                    actor_id=USER_A,
                    assistance_type="evidence_review",
                    classification="review_only",
                    reason="required service evidence review",
                    occurred_at=window_start + timedelta(hours=3),
                ),
            )
            with pytest.raises(KpiInvariantError, match="assistance event id"):
                await record_kpi_assistance(
                    db,
                    RecordAssistance(
                        org_id=ORG_A,
                        event_id="assist-review-only",
                        service_campaign_id=campaign_1.id,
                        actor_id=USER_A,
                        assistance_type="required_input_completion",
                        classification="completion",
                        reason="same event id with different meaning",
                        occurred_at=window_start + timedelta(hours=3),
                    ),
                )
            await record_kpi_assistance(
                db,
                RecordAssistance(
                    org_id=ORG_A,
                    event_id="assist-completion",
                    service_campaign_id=campaign_2.id,
                    actor_id=USER_A,
                    assistance_type="required_input_completion",
                    classification="completion",
                    reason="operator completed a required customer input",
                    occurred_at=window_start + timedelta(hours=4),
                ),
            )

            executions = []
            for index, campaign in enumerate((campaign_1, campaign_2), start=1):
                execution = Execution(
                    id=f"kpi-execution-{index}",
                    org_id=ORG_A,
                    run_type="campaign_run",
                    status="completed" if index == 1 else "failed",
                    user_id=USER_A,
                    finished_at=window_start + timedelta(hours=6 + index),
                )
                db.add(execution)
                executions.append(execution)
                db.add(
                    RunAttempt(
                        org_id=ORG_A,
                        service_campaign_id=campaign.id,
                        lane_id=f"kpi-lane-{index}",
                        slot_id=f"kpi-slot-{index}",
                        attempt_no=1,
                        execution_id=execution.id,
                        scenario_version_id=f"kpi-scenario-{index}",
                        app_build_id=f"kpi-build-{index}",
                        idempotency_key=f"kpi-attempt-{index}",
                        reason="scheduled",
                        status=execution.status,
                    )
                )
            db.add(
                ExecutionStep(
                    org_id=ORG_A,
                    execution_id=executions[0].id,
                    step_index=0,
                    step_id="open-app",
                    step_type="open_app",
                    status="passed",
                    started_at=window_start + timedelta(hours=7),
                    ended_at=window_start + timedelta(hours=7, minutes=1),
                )
            )
            await db.flush()

            snapshot_v1 = await compute_kpi_snapshot(
                db,
                org_id=ORG_A,
                cohort_id=cohort.id,
                query_version="query-v1",
                data_freshness_at=window_end,
            )
            await record_kpi_assistance(
                db,
                RecordAssistance(
                    org_id=ORG_A,
                    event_id="assist-late-completion",
                    service_campaign_id=campaign_1.id,
                    actor_id=USER_A,
                    assistance_type="scenario_approval_completion",
                    classification="completion",
                    reason="late imported assistance event",
                    occurred_at=window_start + timedelta(hours=5),
                ),
            )
            repeated_v1 = await compute_kpi_snapshot(
                db,
                org_id=ORG_A,
                cohort_id=cohort.id,
                query_version="query-v1",
                data_freshness_at=window_end + timedelta(hours=1),
            )
            snapshot_v2 = await compute_kpi_snapshot(
                db,
                org_id=ORG_A,
                cohort_id=cohort.id,
                query_version="query-v2",
                data_freshness_at=window_end + timedelta(hours=1),
            )
            event_count = await db.scalar(select(func.count()).select_from(KpiAssistanceEvent))
            snapshot_count = await db.scalar(select(func.count()).select_from(KpiSnapshot))

    assert repeated_review.id == review_event.id
    assert event_count == 3
    assert snapshot_v1.result_status == "fixture_only"
    assert (snapshot_v1.self_serve_numerator, snapshot_v1.self_serve_denominator) == (1, 2)
    assert (snapshot_v1.trace_numerator, snapshot_v1.trace_denominator) == (1, 2)
    assert snapshot_v1.details["run_with_trace"]["missing_trace_count"] == 1
    assert snapshot_v1.details["threshold_evaluation"] == "not_evaluated"
    assert repeated_v1.id == snapshot_v1.id
    assert snapshot_v2.self_serve_numerator == 0
    assert snapshot_count == 2


@pytest.mark.asyncio
async def test_kpi_cohort_rejects_cross_tenant_campaign(tenancy_session_factory) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign = await _seed_campaign(
                db, runtime_campaign_id=seeded["campaign_a"], suffix="kpi.scope"
            )
            definition = await sign_kpi_definition(
                db,
                SignKpiDefinition(
                    org_id=ORG_A,
                    version="kpi-scope-v1",
                    definitions={
                        "self_serve_onboarding": "definition",
                        "run_with_trace": "definition",
                        "window_timezone": "UTC",
                    },
                    signed_by=USER_A,
                    signed_at=now,
                ),
            )
            with pytest.raises(KpiInvariantError, match="out-of-scope"):
                await freeze_kpi_cohort(
                    db,
                    FreezeKpiCohort(
                        org_id=ORG_A,
                        cohort_key="cross-tenant-cohort",
                        definition_id=definition.id,
                        source_kind="real",
                        window_start=now,
                        window_end=now + timedelta(days=1),
                        timezone="UTC",
                        service_campaign_ids=(campaign.id, "service-campaign-org-b"),
                        created_by=USER_A,
                        frozen_at=now,
                    ),
                )

    assert ORG_B != ORG_A
