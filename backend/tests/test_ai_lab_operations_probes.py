from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from services.ai_device_lab.operations import (
    DependencyObservation,
    SignOperationalTarget,
    sign_operational_target,
)
from services.ai_device_lab.operations_probes import (
    HttpStatusProbe,
    RunOperationalProbes,
    collect_dependency_observations,
    run_operational_probe_batch,
    run_operational_readiness_probes,
)
from services.ai_device_lab.readiness import (
    ReadinessPolicy,
    StartCampaign,
    start_campaign,
)
from services.ai_device_lab.service_campaigns import (
    CreateServiceCampaign,
    create_service_campaign,
)
from tenancy.context import tenant_context
from tests.tenancy_test_support import ORG_A, USER_A, seed_two_org_fixture


@dataclass
class ProbeTracker:
    active: int = 0
    peak: int = 0


class Probe:
    def __init__(
        self,
        dependency: str,
        *,
        ready: bool = True,
        delay: float = 0,
        fail: bool = False,
        observed_at_offset: timedelta = timedelta(),
        tracker: ProbeTracker | None = None,
    ) -> None:
        self.dependency = dependency
        self.ready = ready
        self.delay = delay
        self.fail = fail
        self.observed_at_offset = observed_at_offset
        self.tracker = tracker or ProbeTracker()

    async def probe(self, *, observed_at: datetime) -> DependencyObservation:
        self.tracker.active += 1
        self.tracker.peak = max(self.tracker.peak, self.tracker.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.fail:
                raise RuntimeError("private endpoint and credential must not persist")
            return DependencyObservation(
                ready=self.ready,
                reason_code="PASS" if self.ready else "DEPENDENCY_UNREADY",
                observed_at=observed_at + self.observed_at_offset,
                source_type="test_probe",
                source_ref=self.dependency,
                source_version="fixture-v1",
                latency_ms=self.delay * 1000,
            )
        finally:
            self.tracker.active -= 1


def _target(now: datetime) -> SignOperationalTarget:
    return SignOperationalTarget(
        org_id=ORG_A,
        version="ops-probes-v1",
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


def _all_probes() -> dict[str, Probe]:
    return {
        dependency: Probe(dependency)
        for dependency in (
            "encryption",
            "payment_provider",
            "object_storage",
            "worker",
            "relay",
        )
    }


@pytest.mark.asyncio
async def test_probes_persist_provenance_and_feed_the_atomic_start_gate(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 4, tzinfo=UTC)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign = await create_service_campaign(
                db,
                CreateServiceCampaign(
                    org_id=ORG_A,
                    owner_id=USER_A,
                    runtime_campaign_id=seeded["campaign_a"],
                    package_name="com.example.operations.probes",
                    timezone="UTC",
                    plan_version="adl-14d-v1",
                ),
            )
            target = await sign_operational_target(db, _target(now))
            assessment = await run_operational_readiness_probes(
                db,
                RunOperationalProbes(
                    org_id=ORG_A,
                    target_id=target.id,
                    build_ref="build-probe-fixture",
                    schema_version="160",
                    observed_at=now,
                ),
                probes=_all_probes(),
            )
            result = await start_campaign(
                db,
                StartCampaign(
                    org_id=ORG_A,
                    service_campaign_id=campaign.id,
                    idempotency_key="start-after-probes",
                    now=now + timedelta(seconds=1),
                    policy=ReadinessPolicy(
                        version="readiness-v1",
                        require_participation=False,
                    ),
                ),
            )

    assert assessment.status == "ready"
    assert assessment.checks["relay"] == {
        "ready": True,
        "reason_code": "PASS",
        "observed_at": now.isoformat(),
        "source_type": "test_probe",
        "source_ref": "relay",
        "source_version": "fixture-v1",
        "latency_ms": 0,
    }
    operational = {check.check_key: check for check in result.checks}[
        "operational_dependencies"
    ]
    assert operational.status == "required_pass"
    assert operational.source_ref == assessment.id
    assert result.started is False  # other mandatory campaign evidence is still absent


@pytest.mark.asyncio
async def test_probe_timeout_failure_staleness_and_missing_config_fail_closed(
    tenancy_session_factory,
) -> None:
    await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 4, tzinfo=UTC)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            target = await sign_operational_target(db, _target(now))
            assessment = await run_operational_readiness_probes(
                db,
                RunOperationalProbes(
                    org_id=ORG_A,
                    target_id=target.id,
                    build_ref="build-probe-fixture",
                    schema_version="160",
                    observed_at=now,
                    timeout_seconds=0.05,
                    max_observation_age_seconds=5,
                ),
                probes={
                    "payment_provider": Probe("payment_provider", fail=True),
                    "object_storage": Probe("object_storage", delay=0.1),
                    "relay": Probe(
                        "relay",
                        observed_at_offset=-timedelta(seconds=6),
                    ),
                },
            )

    assert assessment.status == "blocked"
    assert assessment.checks["encryption"]["reason_code"] == "PROBE_UNCONFIGURED"
    assert assessment.checks["payment_provider"]["reason_code"] == "PROBE_FAILED"
    assert assessment.checks["object_storage"]["reason_code"] == "PROBE_TIMEOUT"
    assert assessment.checks["relay"]["reason_code"] == "PROBE_OBSERVATION_STALE"
    serialized = str(assessment.checks).lower()
    assert "private endpoint" not in serialized
    assert "credential" not in serialized


@pytest.mark.asyncio
async def test_probe_collection_bounds_dependency_concurrency() -> None:
    now = datetime(2026, 10, 4, tzinfo=UTC)
    tracker = ProbeTracker()
    probes = {
        dependency: Probe(dependency, delay=0.01, tracker=tracker)
        for dependency in (
            "encryption",
            "payment_provider",
            "object_storage",
            "worker",
            "relay",
        )
    }
    observations = await collect_dependency_observations(
        probes,
        observed_at=now,
        concurrency=2,
    )
    assert all(observation.ready for observation in observations.values())
    assert tracker.peak == 2


@pytest.mark.asyncio
async def test_probe_batch_discovers_latest_target_and_skips_fresh_assessment(
    tenancy_session_factory,
) -> None:
    await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 4, tzinfo=UTC)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            await sign_operational_target(db, _target(now))
            await db.commit()

    first = await run_operational_probe_batch(
        tenancy_session_factory,
        build_ref="build-probe-fixture",
        schema_version="160",
        probes=_all_probes(),
        now=now,
    )
    second = await run_operational_probe_batch(
        tenancy_session_factory,
        build_ref="build-probe-fixture",
        schema_version="160",
        probes=_all_probes(),
        now=now + timedelta(seconds=1),
    )
    assert first.discovered == 1
    assert first.assessed == 1
    assert first.ready == 1
    assert second.discovered == 1
    assert second.assessed == 0
    assert second.skipped_fresh == 1


@pytest.mark.asyncio
async def test_http_probe_keeps_endpoint_and_response_body_ephemeral() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["token"] == "ephemeral-secret"
        return httpx.Response(
            200,
            headers={"x-service-version": "relay-v3"},
            text="private provider response body",
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        observation = await HttpStatusProbe(
            endpoint="https://relay.internal/ready?token=ephemeral-secret",
            source_ref="relay-primary",
            client=client,
        ).probe(observed_at=datetime(2026, 10, 4, tzinfo=UTC))
    finally:
        await client.aclose()

    assert observation.ready is True
    assert observation.source_ref == "relay-primary"
    assert observation.source_version == "relay-v3"
    serialized = str(observation)
    assert "relay.internal" not in serialized
    assert "ephemeral-secret" not in serialized
    assert "private provider response body" not in serialized
