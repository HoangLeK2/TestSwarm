"""Durable farm delivery, event inbox, and immutable evidence manifest."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from tenancy.models import TenantScopedModel

from .utils import _now, _uuid


class FarmJob(TenantScopedModel, Base):
    __tablename__ = "farm_jobs"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_farm_jobs_org_id"),
        UniqueConstraint("org_id", "run_attempt_id", name="uq_farm_jobs_attempt"),
        UniqueConstraint("org_id", "idempotency_key", name="uq_farm_jobs_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_attempt_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("run_attempts.id", ondelete="RESTRICT"), nullable=False
    )
    reservation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("device_reservations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    scenario_approval_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("scenario_approvals.id", ondelete="RESTRICT"),
        nullable=False,
    )
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    device_id: Mapped[str] = mapped_column(String(36), nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)
    terminal_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class FarmJobOutbox(TenantScopedModel, Base):
    __tablename__ = "farm_job_outbox"
    __table_args__ = (
        UniqueConstraint("org_id", "job_id", name="uq_farm_job_outbox_job"),
        Index(
            "idx_farm_job_outbox_delivery",
            "status",
            "available_at",
            "lease_until",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("farm_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    delivery_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class FarmEventInbox(TenantScopedModel, Base):
    __tablename__ = "farm_event_inbox"
    __table_args__ = (
        UniqueConstraint("source", "event_id", name="uq_farm_event_source_id"),
        ForeignKeyConstraint(
            ["org_id", "job_id"],
            ["farm_jobs.org_id", "farm_jobs.id"],
            ondelete="RESTRICT",
            name="fk_farm_event_job_org",
        ),
        Index("idx_farm_event_job_time", "job_id", "occurred_at", "received_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(String(36), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    assertion_passed: Mapped[bool | None] = mapped_column(nullable=True)
    step_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    step_attempt_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    artifact_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class EvidenceItem(TenantScopedModel, Base):
    __tablename__ = "evidence_items"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_evidence_items_org_id"),
        UniqueConstraint(
            "org_id",
            "run_attempt_id",
            "step_path",
            "step_attempt_index",
            "kind",
            name="uq_evidence_item_step_kind",
        ),
        Index("idx_evidence_items_attempt", "run_attempt_id", "captured_at"),
        Index(
            "idx_evidence_items_retention",
            "status",
            "pinned_by_report",
            "retention_until",
            "org_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    service_campaign_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("service_campaigns.id", ondelete="RESTRICT"),
        nullable=False,
    )
    run_attempt_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("run_attempts.id", ondelete="RESTRICT"), nullable=False
    )
    execution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("executions.id", ondelete="RESTRICT"), nullable=False
    )
    step_path: Mapped[str] = mapped_column(String(255), nullable=False)
    step_attempt_index: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    capture_error_code: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    retention_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    pinned_by_report: Mapped[bool] = mapped_column(nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
