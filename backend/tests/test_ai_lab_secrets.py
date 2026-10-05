from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

import common.crypto as crypto
from db.models.ai_device_lab import ServiceLane
from db.models.ai_device_lab_secrets import SecretAccessAudit, SecretRecord
from services.ai_device_lab.secrets import (
    CreateSecret,
    IssueCapability,
    SecretAccessDenied,
    create_secret,
    issue_capability,
    resolve_secret,
    revoke_secret,
)
from services.ai_device_lab.service_campaigns import CreateServiceCampaign, create_service_campaign
from tenancy.context import tenant_context
from tests.tenancy_test_support import ORG_A, USER_A, seed_two_org_fixture


@pytest.mark.asyncio
async def test_exact_capability_resolves_once_without_persisting_plaintext(
    tenancy_session_factory,
    monkeypatch,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    canary = "ADL-CANARY-super-secret"
    monkeypatch.setattr(crypto, "_KEY_RAW", Fernet.generate_key().decode())
    now = datetime.now(timezone.utc)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign = await create_service_campaign(
                db,
                CreateServiceCampaign(
                    org_id=ORG_A,
                    owner_id=USER_A,
                    runtime_campaign_id=seeded["campaign_a"],
                    package_name="com.example.app",
                    timezone="UTC",
                    plan_version="adl-14d-v1",
                    lane_count=1,
                ),
            )
            lane = (
                await db.execute(select(ServiceLane).where(ServiceLane.service_campaign_id == campaign.id))
            ).scalar_one()
            record = await create_secret(
                db,
                CreateSecret(
                    org_id=ORG_A,
                    service_campaign_id=campaign.id,
                    secret_type="test_account_password",
                    plaintext=canary,
                    key_version="key-v1",
                    retention_policy="delete_after_campaign",
                    created_by=USER_A,
                ),
            )
            capability = await issue_capability(
                db,
                IssueCapability(
                    org_id=ORG_A,
                    secret_record_id=record.id,
                    service_campaign_id=campaign.id,
                    lane_id=lane.id,
                    run_attempt_id="attempt-1",
                    device_id=seeded["device_a_ids"][0],
                    worker_principal="relay/worker-1",
                    allowed_operation="credential.fill",
                    expires_at=now + timedelta(minutes=2),
                ),
            )
            value = await resolve_secret(
                db,
                org_id=ORG_A,
                capability_ref=capability.capability_ref,
                worker_principal="relay/worker-1",
                run_attempt_id="attempt-1",
                device_id=seeded["device_a_ids"][0],
                operation="credential.fill",
                now=now,
            )
            with pytest.raises(SecretAccessDenied) as exhausted:
                await resolve_secret(
                    db,
                    org_id=ORG_A,
                    capability_ref=capability.capability_ref,
                    worker_principal="relay/worker-1",
                    run_attempt_id="attempt-1",
                    device_id=seeded["device_a_ids"][0],
                    operation="credential.fill",
                    now=now,
                )
            persisted = await db.get(SecretRecord, record.id)
            audits = list((await db.execute(select(SecretAccessAudit))).scalars())

    assert value == canary
    assert persisted is not None and persisted.ciphertext != canary
    assert canary not in repr(persisted.__dict__)
    assert exhausted.value.reason_code == "CAPABILITY_EXHAUSTED"
    assert all(canary not in repr(audit.__dict__) for audit in audits)


@pytest.mark.asyncio
async def test_cross_device_and_revoked_capability_fail_closed(
    tenancy_session_factory,
    monkeypatch,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    monkeypatch.setattr(crypto, "_KEY_RAW", Fernet.generate_key().decode())
    now = datetime.now(timezone.utc)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign = await create_service_campaign(
                db,
                CreateServiceCampaign(
                    org_id=ORG_A,
                    owner_id=USER_A,
                    runtime_campaign_id=seeded["campaign_a"],
                    package_name="com.example.app",
                    timezone="UTC",
                    plan_version="adl-14d-v1",
                    lane_count=1,
                ),
            )
            lane = (
                await db.execute(select(ServiceLane).where(ServiceLane.service_campaign_id == campaign.id))
            ).scalar_one()
            record = await create_secret(
                db,
                CreateSecret(
                    org_id=ORG_A,
                    service_campaign_id=campaign.id,
                    secret_type="password",
                    plaintext="value-never-in-error",
                    key_version="key-v1",
                    retention_policy="delete_after_campaign",
                    created_by=USER_A,
                ),
            )
            capability = await issue_capability(
                db,
                IssueCapability(
                    org_id=ORG_A,
                    secret_record_id=record.id,
                    service_campaign_id=campaign.id,
                    lane_id=lane.id,
                    run_attempt_id="attempt-2",
                    device_id=seeded["device_a_ids"][0],
                    worker_principal="relay/worker-1",
                    allowed_operation="credential.fill",
                    expires_at=now + timedelta(minutes=2),
                ),
            )
            with pytest.raises(SecretAccessDenied) as wrong_device:
                await resolve_secret(
                    db,
                    org_id=ORG_A,
                    capability_ref=capability.capability_ref,
                    worker_principal="relay/worker-1",
                    run_attempt_id="attempt-2",
                    device_id=seeded["device_a_ids"][1],
                    operation="credential.fill",
                    now=now,
                )
            await revoke_secret(db, org_id=ORG_A, secret_record_id=record.id)
            with pytest.raises(SecretAccessDenied) as revoked:
                await resolve_secret(
                    db,
                    org_id=ORG_A,
                    capability_ref=capability.capability_ref,
                    worker_principal="relay/worker-1",
                    run_attempt_id="attempt-2",
                    device_id=seeded["device_a_ids"][0],
                    operation="credential.fill",
                    now=now,
                )

    assert wrong_device.value.reason_code == "DEVICE_SCOPE_MISMATCH"
    assert revoked.value.reason_code == "CAPABILITY_REVOKED"
