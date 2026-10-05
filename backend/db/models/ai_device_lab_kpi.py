"""Versioned KPI definitions, cohorts, assistance events, and immutable snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from tenancy.models import TenantScopedModel

from .utils import _now, _uuid


class KpiMeasurementDefinition(TenantScopedModel, Base):
    __tablename__ = "kpi_measurement_definitions"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_kpi_definitions_org_id"),
        UniqueConstraint("org_id", "version", name="uq_kpi_definition_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    definitions: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    signed_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    signed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class KpiCohort(TenantScopedModel, Base):
    __tablename__ = "kpi_cohorts"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_kpi_cohorts_org_id"),
        UniqueConstraint("org_id", "cohort_key", name="uq_kpi_cohort_key"),
        ForeignKeyConstraint(
            ["org_id", "definition_id"],
            ["kpi_measurement_definitions.org_id", "kpi_measurement_definitions.id"],
            ondelete="RESTRICT",
            name="fk_kpi_cohort_definition_org",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    cohort_key: Mapped[str] = mapped_column(String(128), nullable=False)
    definition_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    frozen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class KpiCohortMember(TenantScopedModel, Base):
    __tablename__ = "kpi_cohort_members"
    __table_args__ = (
        UniqueConstraint("org_id", "cohort_id", "service_campaign_id", name="uq_kpi_cohort_member"),
        ForeignKeyConstraint(
            ["org_id", "cohort_id"],
            ["kpi_cohorts.org_id", "kpi_cohorts.id"],
            ondelete="RESTRICT",
            name="fk_kpi_member_cohort_org",
        ),
        ForeignKeyConstraint(
            ["org_id", "service_campaign_id"],
            ["service_campaigns.org_id", "service_campaigns.id"],
            ondelete="RESTRICT",
            name="fk_kpi_member_campaign_org",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    cohort_id: Mapped[str] = mapped_column(String(36), nullable=False)
    service_campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    eligible: Mapped[bool] = mapped_column(nullable=False, default=True)
    exclusion_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class KpiAssistanceEvent(TenantScopedModel, Base):
    __tablename__ = "kpi_assistance_events"
    __table_args__ = (
        UniqueConstraint("org_id", "event_id", name="uq_kpi_assistance_event"),
        ForeignKeyConstraint(
            ["org_id", "service_campaign_id"],
            ["service_campaigns.org_id", "service_campaigns.id"],
            ondelete="RESTRICT",
            name="fk_kpi_assistance_campaign_org",
        ),
        Index("idx_kpi_assistance_campaign_time", "service_campaign_id", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    service_campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    assistance_type: Mapped[str] = mapped_column(String(64), nullable=False)
    classification: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class KpiSnapshot(TenantScopedModel, Base):
    __tablename__ = "kpi_snapshots"
    __table_args__ = (
        UniqueConstraint("org_id", "cohort_id", "query_version", name="uq_kpi_snapshot_query"),
        ForeignKeyConstraint(
            ["org_id", "cohort_id"],
            ["kpi_cohorts.org_id", "kpi_cohorts.id"],
            ondelete="RESTRICT",
            name="fk_kpi_snapshot_cohort_org",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    cohort_id: Mapped[str] = mapped_column(String(36), nullable=False)
    query_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    result_status: Mapped[str] = mapped_column(String(32), nullable=False)
    self_serve_numerator: Mapped[int] = mapped_column(nullable=False)
    self_serve_denominator: Mapped[int] = mapped_column(nullable=False)
    trace_numerator: Mapped[int] = mapped_column(nullable=False)
    trace_denominator: Mapped[int] = mapped_column(nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False)
    data_freshness_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
