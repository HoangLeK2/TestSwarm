"""Encrypted job-scoped secrets and ephemeral worker capabilities."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from tenancy.models import TenantScopedModel

from .utils import _now, _uuid


class SecretRecord(TenantScopedModel, Base):
    __tablename__ = "secret_records"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_secret_records_org_id"),
        UniqueConstraint("opaque_ref", name="uq_secret_records_opaque_ref"),
        ForeignKeyConstraint(
            ["org_id", "service_campaign_id"],
            ["service_campaigns.org_id", "service_campaigns.id"],
            ondelete="RESTRICT",
            name="fk_secret_records_campaign_org",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    service_campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    opaque_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    secret_type: Mapped[str] = mapped_column(String(64), nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    key_version: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_policy: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class JobSecretCapability(TenantScopedModel, Base):
    __tablename__ = "job_secret_capabilities"
    __table_args__ = (
        UniqueConstraint("org_id", "capability_ref", name="uq_job_secret_capability_ref"),
        ForeignKeyConstraint(
            ["org_id", "secret_record_id"],
            ["secret_records.org_id", "secret_records.id"],
            ondelete="RESTRICT",
            name="fk_job_secret_capability_secret_org",
        ),
        Index("idx_job_secret_capability_attempt", "run_attempt_id", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    capability_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    secret_record_id: Mapped[str] = mapped_column(String(36), nullable=False)
    service_campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    lane_id: Mapped[str] = mapped_column(String(36), nullable=False)
    run_attempt_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("run_attempts.id", ondelete="RESTRICT"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False
    )
    worker_principal: Mapped[str] = mapped_column(String(255), nullable=False)
    allowed_operation: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    max_resolves: Mapped[int] = mapped_column(nullable=False, default=1)
    resolve_count: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class SecretAccessAudit(TenantScopedModel, Base):
    __tablename__ = "secret_access_audits"
    __table_args__ = (Index("idx_secret_access_audits_capability_time", "capability_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    capability_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("job_secret_capabilities.id", ondelete="RESTRICT"), nullable=False
    )
    worker_principal: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
