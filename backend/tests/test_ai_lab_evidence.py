from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from db.models.ai_device_lab import RunAttempt, ServiceCampaign
from db.models.ai_device_lab_delivery import EvidenceItem
from services.ai_device_lab.evidence import (
    RegisterEvidence,
    expire_evidence,
    register_evidence,
    run_evidence_retention_batch,
)
from tenancy.context import tenant_context
from tests.tenancy_test_support import (
    ORG_A,
    ORG_B,
    USER_A,
    USER_B,
    seed_two_org_fixture,
)


class _DeleteStorage:
    def __init__(self, *, succeeds: bool) -> None:
        self.succeeds = succeeds
        self.deleted: list[str] = []

    async def delete_private(self, *, object_key: str) -> bool:
        self.deleted.append(object_key)
        return self.succeeds


class _ConcurrencyTrackingStorage:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.deleted: list[str] = []

    async def delete_private(self, *, object_key: str) -> bool:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0)
        self.deleted.append(object_key)
        self.active -= 1
        return True


@pytest.mark.asyncio
async def test_evidence_is_available_only_after_verified_storage_and_pin_blocks_expiry(
    tenancy_session_factory,
) -> None:
    await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 5, tzinfo=UTC)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            attempt = RunAttempt(
                id="evidence-attempt-1",
                org_id=ORG_A,
                service_campaign_id="service-campaign-1",
                lane_id="lane-1",
                slot_id="slot-1",
                attempt_no=1,
                execution_id="execution-1",
                scenario_version_id="scenario-version-1",
                app_build_id="build-1",
                idempotency_key="attempt-evidence-1",
                reason="scheduled",
            )
            db.add(attempt)
            await db.flush()
            missing = await register_evidence(
                db,
                RegisterEvidence(
                    org_id=ORG_A,
                    run_attempt_id=attempt.id,
                    step_path="steps[0]",
                    step_attempt_index=1,
                    kind="screenshot",
                    captured_at=now,
                    retention_until=now + timedelta(days=30),
                    object_key="private/unverified.png",
                    checksum_sha256="a" * 64,
                    storage_verified=False,
                    capture_error_code="UPLOAD_TIMEOUT",
                ),
            )
            available = await register_evidence(
                db,
                RegisterEvidence(
                    org_id=ORG_A,
                    run_attempt_id=attempt.id,
                    step_path="steps[1]",
                    step_attempt_index=1,
                    kind="screenshot",
                    captured_at=now,
                    retention_until=now - timedelta(seconds=1),
                    object_key="private/verified.png",
                    content_type="image/png",
                    checksum_sha256="b" * 64,
                    storage_verified=True,
                ),
            )
            available.pinned_by_report = True
            expired = await expire_evidence(db, now=now)

    assert missing.status == "missing" and missing.object_key is None
    assert available.status == "available"
    assert expired == 0


@pytest.mark.asyncio
async def test_expiry_tombstones_only_after_private_object_delete_succeeds(
    tenancy_session_factory,
) -> None:
    await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 5, tzinfo=UTC)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            attempt = RunAttempt(
                id="evidence-attempt-cleanup",
                org_id=ORG_A,
                service_campaign_id="service-campaign-cleanup",
                lane_id="lane-cleanup",
                slot_id="slot-cleanup",
                attempt_no=1,
                execution_id="execution-cleanup",
                scenario_version_id="scenario-version-cleanup",
                app_build_id="build-cleanup",
                idempotency_key="attempt-evidence-cleanup",
                reason="scheduled",
            )
            db.add(attempt)
            await db.flush()
            failed_delete = await register_evidence(
                db,
                RegisterEvidence(
                    org_id=ORG_A,
                    run_attempt_id=attempt.id,
                    step_path="steps[0]",
                    step_attempt_index=1,
                    kind="screenshot",
                    captured_at=now,
                    retention_until=now - timedelta(seconds=1),
                    object_key="private/delete-fails.png",
                    content_type="image/png",
                    checksum_sha256="c" * 64,
                    storage_verified=True,
                ),
            )
            succeeds = _DeleteStorage(succeeds=True)
            fails = _DeleteStorage(succeeds=False)

            first = await expire_evidence(db, now=now, storage=fails, batch_size=1)
            second = await expire_evidence(db, now=now, storage=succeeds, batch_size=1)

    assert first == 0
    assert failed_delete.status == "expired"
    assert failed_delete.deleted_at == now
    assert fails.deleted == ["private/delete-fails.png"]
    assert succeeds.deleted == ["private/delete-fails.png"]
    assert second == 1


@pytest.mark.asyncio
async def test_expiry_limits_each_batch_and_private_delete_concurrency(
    tenancy_session_factory,
) -> None:
    await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 5, tzinfo=UTC)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            attempt = RunAttempt(
                id="evidence-attempt-batch",
                org_id=ORG_A,
                service_campaign_id="service-campaign-batch",
                lane_id="lane-batch",
                slot_id="slot-batch",
                attempt_no=1,
                execution_id="execution-batch",
                scenario_version_id="scenario-version-batch",
                app_build_id="build-batch",
                idempotency_key="attempt-evidence-batch",
                reason="scheduled",
            )
            db.add(attempt)
            await db.flush()
            evidence = []
            for index in range(3):
                evidence.append(
                    await register_evidence(
                        db,
                        RegisterEvidence(
                            org_id=ORG_A,
                            run_attempt_id=attempt.id,
                            step_path=f"steps[{index}]",
                            step_attempt_index=1,
                            kind="screenshot",
                            captured_at=now,
                            retention_until=now - timedelta(seconds=3 - index),
                            object_key=f"private/batch-{index}.png",
                            content_type="image/png",
                            checksum_sha256=f"{index + 1}" * 64,
                            storage_verified=True,
                        ),
                    )
                )
            storage = _ConcurrencyTrackingStorage()

            expired = await expire_evidence(
                db,
                now=now,
                storage=storage,
                batch_size=2,
                delete_concurrency=1,
            )

    assert expired == 2
    assert storage.max_active == 1
    assert storage.deleted == ["private/batch-0.png", "private/batch-1.png"]
    assert [item.status for item in evidence] == ["expired", "expired", "available"]


@pytest.mark.asyncio
async def test_retention_worker_discovers_tenants_but_keeps_a_global_batch_bound(
    tenancy_session_factory,
) -> None:
    await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 5, tzinfo=UTC)
    fixtures = (
        (ORG_A, USER_A, "camp-a-1", "a", now - timedelta(seconds=2)),
        (ORG_B, USER_B, "camp-b-1", "b", now - timedelta(seconds=1)),
    )
    for org_id, user_id, runtime_campaign_id, suffix, retention_until in fixtures:
        with tenant_context(org_id):
            async with tenancy_session_factory() as db:
                campaign = ServiceCampaign(
                    id=f"service-retention-{suffix}",
                    org_id=org_id,
                    runtime_campaign_id=runtime_campaign_id,
                    owner_id=user_id,
                    package_name=f"com.example.retention.{suffix}",
                    timezone="UTC",
                    plan_version="retention-v1",
                )
                attempt = RunAttempt(
                    id=f"attempt-retention-{suffix}",
                    org_id=org_id,
                    service_campaign_id=campaign.id,
                    lane_id=f"lane-retention-{suffix}",
                    slot_id=f"slot-retention-{suffix}",
                    attempt_no=1,
                    execution_id=f"execution-retention-{suffix}",
                    scenario_version_id=f"scenario-retention-{suffix}",
                    app_build_id=f"build-retention-{suffix}",
                    idempotency_key=f"attempt-retention-{suffix}",
                    reason="scheduled",
                )
                db.add_all([campaign, attempt])
                await db.flush()
                await register_evidence(
                    db,
                    RegisterEvidence(
                        org_id=org_id,
                        run_attempt_id=attempt.id,
                        step_path="steps[0]",
                        step_attempt_index=1,
                        kind="screenshot",
                        captured_at=now,
                        retention_until=retention_until,
                        object_key=f"private/tenant-{suffix}.png",
                        content_type="image/png",
                        checksum_sha256=suffix * 64,
                        storage_verified=True,
                    ),
                )
                await db.commit()

    storage = _ConcurrencyTrackingStorage()
    first = await run_evidence_retention_batch(
        tenancy_session_factory,
        now=now,
        storage=storage,
        batch_size=1,
    )
    second = await run_evidence_retention_batch(
        tenancy_session_factory,
        now=now,
        storage=storage,
        batch_size=1,
    )

    statuses = []
    for org_id, _, _, suffix, _ in fixtures:
        with tenant_context(org_id):
            async with tenancy_session_factory() as db:
                statuses.append(
                    (
                        await db.execute(
                            select(EvidenceItem.status).where(
                                EvidenceItem.run_attempt_id
                                == f"attempt-retention-{suffix}"
                            )
                        )
                    ).scalar_one()
                )

    assert first.attempted == first.deleted == 1
    assert second.attempted == second.deleted == 1
    assert storage.deleted == ["private/tenant-a.png", "private/tenant-b.png"]
    assert statuses == ["expired", "expired"]
