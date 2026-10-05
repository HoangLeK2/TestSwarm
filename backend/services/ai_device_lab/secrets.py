"""Encrypted secret references resolved only by an exact job capability."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.crypto import decrypt_password, encrypt_password, is_encryption_enabled
from db.models.ai_device_lab import ServiceCampaign, ServiceLane
from db.models.ai_device_lab_secrets import JobSecretCapability, SecretAccessAudit, SecretRecord


class SecretAccessDenied(ValueError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class CreateSecret:
    org_id: str
    service_campaign_id: str
    secret_type: str
    plaintext: str
    key_version: str
    retention_policy: str
    created_by: str
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class IssueCapability:
    org_id: str
    secret_record_id: str
    service_campaign_id: str
    lane_id: str
    run_attempt_id: str
    device_id: str
    worker_principal: str
    allowed_operation: str
    expires_at: datetime
    max_resolves: int = 1


async def create_secret(db: AsyncSession, command: CreateSecret) -> SecretRecord:
    if not command.plaintext:
        raise SecretAccessDenied("SECRET_VALUE_REQUIRED")
    if not is_encryption_enabled():
        raise SecretAccessDenied("SECRET_ENCRYPTION_UNAVAILABLE")
    campaign = await db.scalar(
        select(ServiceCampaign.id).where(
            ServiceCampaign.id == command.service_campaign_id,
            ServiceCampaign.org_id == command.org_id,
        )
    )
    if campaign is None:
        raise SecretAccessDenied("CAMPAIGN_SCOPE_MISMATCH")
    record = SecretRecord(
        org_id=command.org_id,
        service_campaign_id=command.service_campaign_id,
        opaque_ref=f"sec_{secrets.token_urlsafe(24)}",
        secret_type=command.secret_type,
        ciphertext=encrypt_password(command.plaintext),
        key_version=command.key_version,
        expires_at=command.expires_at,
        retention_policy=command.retention_policy,
        created_by=command.created_by,
    )
    db.add(record)
    await db.flush()
    return record


async def issue_capability(
    db: AsyncSession,
    command: IssueCapability,
) -> JobSecretCapability:
    if command.expires_at <= datetime.now(timezone.utc):
        raise SecretAccessDenied("CAPABILITY_EXPIRY_REQUIRED")
    if command.max_resolves < 1 or command.max_resolves > 3:
        raise SecretAccessDenied("CAPABILITY_RESOLVE_LIMIT_INVALID")
    secret_record = (
        await db.execute(
            select(SecretRecord).where(
                SecretRecord.id == command.secret_record_id,
                SecretRecord.org_id == command.org_id,
                SecretRecord.service_campaign_id == command.service_campaign_id,
                SecretRecord.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    lane = await db.scalar(
        select(ServiceLane.id).where(
            ServiceLane.id == command.lane_id,
            ServiceLane.org_id == command.org_id,
            ServiceLane.service_campaign_id == command.service_campaign_id,
        )
    )
    if secret_record is None or lane is None:
        raise SecretAccessDenied("CAPABILITY_SCOPE_MISMATCH")
    capability = JobSecretCapability(
        org_id=command.org_id,
        capability_ref=f"cap_{secrets.token_urlsafe(24)}",
        secret_record_id=secret_record.id,
        service_campaign_id=command.service_campaign_id,
        lane_id=command.lane_id,
        run_attempt_id=command.run_attempt_id,
        device_id=command.device_id,
        worker_principal=command.worker_principal,
        allowed_operation=command.allowed_operation,
        expires_at=command.expires_at,
        max_resolves=command.max_resolves,
        resolve_count=0,
    )
    db.add(capability)
    await db.flush()
    return capability


async def resolve_secret(
    db: AsyncSession,
    *,
    org_id: str,
    capability_ref: str,
    worker_principal: str,
    run_attempt_id: str,
    device_id: str,
    operation: str,
    now: datetime,
) -> str:
    capability = (
        await db.execute(
            select(JobSecretCapability)
            .where(
                JobSecretCapability.org_id == org_id,
                JobSecretCapability.capability_ref == capability_ref,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if capability is None:
        raise SecretAccessDenied("CAPABILITY_NOT_FOUND")
    reason = "ALLOWED"
    if capability.revoked_at is not None:
        reason = "CAPABILITY_REVOKED"
    elif now >= capability.expires_at.replace(tzinfo=capability.expires_at.tzinfo or timezone.utc):
        reason = "CAPABILITY_EXPIRED"
    elif capability.worker_principal != worker_principal:
        reason = "WORKER_SCOPE_MISMATCH"
    elif capability.run_attempt_id != run_attempt_id:
        reason = "ATTEMPT_SCOPE_MISMATCH"
    elif capability.device_id != device_id:
        reason = "DEVICE_SCOPE_MISMATCH"
    elif capability.allowed_operation != operation:
        reason = "OPERATION_SCOPE_MISMATCH"
    elif capability.resolve_count >= capability.max_resolves:
        reason = "CAPABILITY_EXHAUSTED"
    secret_record = await db.get(SecretRecord, capability.secret_record_id)
    if reason == "ALLOWED" and (
        secret_record is None or secret_record.revoked_at is not None
    ):
        reason = "SECRET_REVOKED_OR_MISSING"
    elif reason == "ALLOWED" and secret_record.expires_at is not None and now >= secret_record.expires_at.replace(
        tzinfo=secret_record.expires_at.tzinfo or timezone.utc
    ):
        reason = "SECRET_EXPIRED"
    audit = SecretAccessAudit(
        org_id=org_id,
        capability_id=capability.id,
        worker_principal=worker_principal,
        action="resolve",
        outcome="allowed" if reason == "ALLOWED" else "denied",
        reason_code=reason,
    )
    db.add(audit)
    if reason != "ALLOWED":
        await db.flush()
        raise SecretAccessDenied(reason)
    value = decrypt_password(secret_record.ciphertext)
    if not value:
        audit.outcome = "denied"
        audit.reason_code = "SECRET_DECRYPTION_FAILED"
        await db.flush()
        raise SecretAccessDenied("SECRET_DECRYPTION_FAILED")
    capability.resolve_count += 1
    await db.flush()
    return value


async def revoke_secret(db: AsyncSession, *, org_id: str, secret_record_id: str) -> None:
    record = (
        await db.execute(
            select(SecretRecord)
            .where(SecretRecord.id == secret_record_id, SecretRecord.org_id == org_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if record is None:
        return
    record.revoked_at = record.revoked_at or datetime.now(timezone.utc)
    capabilities = list(
        (
            await db.execute(
                select(JobSecretCapability).where(
                    JobSecretCapability.org_id == org_id,
                    JobSecretCapability.secret_record_id == record.id,
                    JobSecretCapability.revoked_at.is_(None),
                )
            )
        ).scalars()
    )
    for capability in capabilities:
        capability.revoked_at = record.revoked_at
    await db.flush()
