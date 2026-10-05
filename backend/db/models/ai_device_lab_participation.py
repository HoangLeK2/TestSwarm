"""Play-track participation evidence without storing raw account identity."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from tenancy.models import TenantScopedModel

from .utils import _now, _uuid


class TrackParticipation(TenantScopedModel, Base):
    """One canonical pseudonymous account identity on an app testing track."""

    __tablename__ = "track_participations"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_track_participations_org_id"),
        UniqueConstraint(
            "org_id",
            "package_name",
            "track_name",
            "pseudonymous_account_ref",
            name="uq_track_participations_identity",
        ),
        Index(
            "idx_track_participations_campaign_status",
            "service_campaign_id",
            "current_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    service_campaign_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("service_campaigns.id", ondelete="RESTRICT"), nullable=True
    )
    package_name: Mapped[str] = mapped_column(String(255), nullable=False)
    track_name: Mapped[str] = mapped_column(String(64), nullable=False)
    pseudonymous_account_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    masked_label: Mapped[str] = mapped_column(String(128), nullable=False)
    current_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    evidence_grade: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    active_segment_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_observed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    gap_reason: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class ParticipationEvent(TenantScopedModel, Base):
    """Append-only observation; corrections reference rather than rewrite events."""

    __tablename__ = "participation_events"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_participation_events_org_id"),
        ForeignKeyConstraint(
            ["org_id", "participation_id"],
            ["track_participations.org_id", "track_participations.id"],
            ondelete="RESTRICT",
            name="fk_participation_events_identity_org",
        ),
        Index(
            "idx_participation_events_identity_time",
            "participation_id",
            "observed_at",
            "recorded_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    participation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    evidence_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    evidence_grade: Mapped[str] = mapped_column(String(32), nullable=False)
    review_state: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    recorded_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reviewed_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    segment_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correction_of_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("participation_events.id", ondelete="RESTRICT"), nullable=True
    )
    limitations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

