from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.ai_device_lab.operations import (
    AssessOperationalReadiness,
    OperationalInvariantError,
    SignOperationalTarget,
    assess_operational_readiness,
    sign_operational_target,
)
from services.ai_device_lab.readiness import ReadinessPolicy, StartCampaign, start_campaign
from services.ai_device_lab.service_campaigns import CreateServiceCampaign, create_service_campaign
from tenancy.context import tenant_context
from tests.tenancy_test_support import ORG_A, USER_A, seed_two_org_fixture


def _target(now: datetime, **overrides) -> SignOperationalTarget:
    values = dict(
        org_id=ORG_A,
        version="ops-v1",
        capacity={
            "concurrent_campaigns": 1,
            "devices": 12,
            "jobs_per_minute": 12,
            "artifact_bytes": 1_000_000,
        },
        slo={"api_p95_ms": 500, "dispatch_lag_p95_seconds": 30},
        recovery={"rpo_seconds": 300, "rto_seconds": 1800},
        alerting={"owner": "oncall-primary", "escalation_ref": "runbook://ai-lab"},
        signed_by=USER_A,
        signed_at=now,
    )
    values.update(overrides)
    return SignOperationalTarget(**values)


@pytest.mark.asyncio
async def test_dependency_assessment_fails_closed_without_exposing_config_values(
    tenancy_session_factory,
) -> None:
    await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            target = await sign_operational_target(db, _target(now))
            blocked = await assess_operational_readiness(
                db,
                AssessOperationalReadiness(
                    org_id=ORG_A,
                    target_id=target.id,
                    dependency_states={
                        "encryption": True,
                        "payment_provider": False,
                        "object_storage": True,
                        "worker": True,
                        "relay": True,
                    },
                    build_ref="build-fixture",
                    schema_version="155",
                    observed_at=now,
                ),
            )

    assert blocked.status == "blocked"
    assert blocked.checks["payment_provider"] == {
        "ready": False,
        "reason_code": "PAYMENT_PROVIDER_UNAVAILABLE",
    }
    assert set(blocked.checks) == {
        "encryption",
        "payment_provider",
        "object_storage",
        "worker",
        "relay",
    }


@pytest.mark.asyncio
async def test_start_uses_only_fresh_ready_operational_assessment(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign = await create_service_campaign(
                db,
                CreateServiceCampaign(
                    org_id=ORG_A,
                    owner_id=USER_A,
                    runtime_campaign_id=seeded["campaign_a"],
                    package_name="com.example.operations",
                    timezone="UTC",
                    plan_version="adl-14d-v1",
                ),
            )
            target = await sign_operational_target(db, _target(now))
            assessment = await assess_operational_readiness(
                db,
                AssessOperationalReadiness(
                    org_id=ORG_A,
                    target_id=target.id,
                    dependency_states={
                        "encryption": True,
                        "payment_provider": True,
                        "object_storage": True,
                        "worker": True,
                        "relay": True,
                    },
                    build_ref="build-fixture",
                    schema_version="155",
                    observed_at=now,
                    ttl_seconds=60,
                ),
            )
            fresh = await start_campaign(
                db,
                StartCampaign(
                    org_id=ORG_A,
                    service_campaign_id=campaign.id,
                    idempotency_key="ops-start-fresh",
                    now=now + timedelta(seconds=30),
                    policy=ReadinessPolicy(version="readiness-v1", require_participation=False),
                ),
            )
            stale = await start_campaign(
                db,
                StartCampaign(
                    org_id=ORG_A,
                    service_campaign_id=campaign.id,
                    idempotency_key="ops-start-stale",
                    now=now + timedelta(seconds=61),
                    policy=ReadinessPolicy(version="readiness-v1", require_participation=False),
                ),
            )

    fresh_check = {item.check_key: item for item in fresh.checks}["operational_dependencies"]
    stale_check = {item.check_key: item for item in stale.checks}["operational_dependencies"]
    assert fresh_check.status == "required_pass"
    assert fresh_check.source_ref == assessment.id
    assert stale_check.status == "blocked"
    assert stale_check.reason_code == "FRESH_OPERATIONAL_READINESS_REQUIRED"


@pytest.mark.asyncio
async def test_operational_target_rejects_unvalidated_zero_capacity(
    tenancy_session_factory,
) -> None:
    await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            with pytest.raises(OperationalInvariantError, match="capacity"):
                await sign_operational_target(
                    db,
                    _target(
                        now,
                        capacity={
                            "concurrent_campaigns": 0,
                            "devices": 12,
                            "jobs_per_minute": 12,
                            "artifact_bytes": 1_000_000,
                        },
                    ),
                )


@pytest.mark.asyncio
async def test_operational_target_version_rejects_different_replay(
    tenancy_session_factory,
) -> None:
    await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            target = await sign_operational_target(db, _target(now))
            repeated = await sign_operational_target(db, _target(now))
            with pytest.raises(OperationalInvariantError, match="immutable"):
                await sign_operational_target(
                    db,
                    _target(
                        now,
                        capacity={
                            "concurrent_campaigns": 2,
                            "devices": 24,
                            "jobs_per_minute": 24,
                            "artifact_bytes": 2_000_000,
                        },
                    ),
                )

    assert repeated.id == target.id
