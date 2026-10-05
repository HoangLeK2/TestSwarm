"""Readiness snapshots, durable start intents, and append-only quota ledger."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from tenancy.models import TenantScopedModel

from .utils import _now, _uuid


class ReadinessSnapshot(TenantScopedModel, Base):
    __tablename__ = "readiness_snapshots"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_readiness_snapshots_org_id"),
        UniqueConstraint(
            "org_id", "service_campaign_id", "revision", name="uq_readiness_snapshot_revision"
        ),
        ForeignKeyConstraint(
            ["org_id", "service_campaign_id"],
            ["service_campaigns.org_id", "service_campaigns.id"],
            ondelete="RESTRICT",
            name="fk_readiness_snapshot_campaign_org",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    service_campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class ReadinessCheck(TenantScopedModel, Base):
    __tablename__ = "readiness_checks"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "check_key", name="uq_readiness_check_key"),
        ForeignKeyConstraint(
            ["org_id", "snapshot_id"],
            ["readiness_snapshots.org_id", "readiness_snapshots.id"],
            ondelete="RESTRICT",
            name="fk_readiness_check_snapshot_org",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    check_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    required: Mapped[bool] = mapped_column(nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    owner: Mapped[str] = mapped_column(String(64), nullable=False)
    next_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class SchedulingIntent(TenantScopedModel, Base):
    __tablename__ = "scheduling_intents"
    __table_args__ = (
        UniqueConstraint("org_id", "idempotency_key", name="uq_scheduling_intents_key"),
        UniqueConstraint(
            "org_id", "service_campaign_id", "intent_kind", name="uq_scheduling_intent_campaign_kind"
        ),
        ForeignKeyConstraint(
            ["org_id", "service_campaign_id"],
            ["service_campaigns.org_id", "service_campaigns.id"],
            ondelete="RESTRICT",
            name="fk_scheduling_intent_campaign_org",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    service_campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    intent_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="start")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    readiness_snapshot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("readiness_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class QuotaLedgerEntry(TenantScopedModel, Base):
    __tablename__ = "quota_ledger_entries"
    __table_args__ = (
        UniqueConstraint("org_id", "charge_key", name="uq_quota_ledger_charge_key"),
        ForeignKeyConstraint(
            ["org_id", "service_campaign_id"],
            ["service_campaigns.org_id", "service_campaigns.id"],
            ondelete="RESTRICT",
            name="fk_quota_ledger_campaign_org",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    service_campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    run_attempt_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("run_attempts.id", ondelete="RESTRICT"), nullable=True
    )
    charge_key: Mapped[str] = mapped_column(String(128), nullable=False)
    entry_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
