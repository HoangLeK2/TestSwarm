"""Signed operational targets and short-lived dependency readiness assessments."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Index, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from tenancy.models import TenantScopedModel

from .utils import _now, _uuid


class OperationalTarget(TenantScopedModel, Base):
    __tablename__ = "operational_targets"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_operational_targets_org_id"),
        UniqueConstraint("org_id", "version", name="uq_operational_target_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    capacity: Mapped[dict] = mapped_column(JSON, nullable=False)
    slo: Mapped[dict] = mapped_column(JSON, nullable=False)
    recovery: Mapped[dict] = mapped_column(JSON, nullable=False)
    alerting: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="signed")
    signed_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class OperationalReadinessAssessment(TenantScopedModel, Base):
    __tablename__ = "operational_readiness_assessments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "target_id"],
            ["operational_targets.org_id", "operational_targets.id"],
            ondelete="RESTRICT",
            name="fk_operational_assessment_target_org",
        ),
        Index("idx_operational_assessment_latest", "org_id", "observed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    checks: Mapped[dict] = mapped_column(JSON, nullable=False)
    build_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
