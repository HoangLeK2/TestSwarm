"""Long-lived fleet reservation and physical-device hygiene state."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from tenancy.models import TenantScopedModel

from .utils import _now, _uuid


class DeviceHygieneState(Base):
    """Global physical-device reuse state, independent of online health."""

    __tablename__ = "device_hygiene_states"

    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="RESTRICT"), primary_key=True
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="dirty")
    protocol_version: Mapped[str] = mapped_column(String(64), nullable=False)
    last_service_campaign_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("service_campaigns.id", ondelete="RESTRICT"),
        nullable=True,
    )
    verification_evidence_ref: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verified_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    reason_code: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class DeviceHygieneAudit(Base):
    """Append-only physical cleanup observation."""

    __tablename__ = "device_hygiene_audits"
    __table_args__ = (
        Index("idx_hygiene_audits_device_time", "device_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    from_state: Mapped[str] = mapped_column(String(32), nullable=False)
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class DeviceReservation(TenantScopedModel, Base):
    """Service interval on one canonical physical device."""

    __tablename__ = "device_reservations"
    __table_args__ = (
        CheckConstraint("starts_at < ends_at", name="chk_device_reservation_interval"),
        ExcludeConstraint(
            ("device_id", "="),
            (text("tstzrange(starts_at, ends_at, '[)')"), "&&"),
            where=text("state IN ('active', 'draining')"),
            name="ex_device_reservation_overlap",
            using="gist",
        ).ddl_if(dialect="postgresql"),
        UniqueConstraint("org_id", "id", name="uq_device_reservations_org_id"),
        Index(
            "uq_active_reservation_lane",
            "org_id",
            "service_campaign_id",
            "lane_id",
            unique=True,
            postgresql_where=text("state IN ('active', 'draining')"),
            sqlite_where=text("state IN ('active', 'draining')"),
        ),
        ForeignKeyConstraint(
            ["org_id", "service_campaign_id"],
            ["service_campaigns.org_id", "service_campaigns.id"],
            ondelete="RESTRICT",
            name="fk_device_reservation_campaign_org",
        ),
        ForeignKeyConstraint(
            ["org_id", "lane_id", "service_campaign_id"],
            [
                "service_lanes.org_id",
                "service_lanes.id",
                "service_lanes.service_campaign_id",
            ],
            ondelete="RESTRICT",
            name="fk_device_reservation_lane_org",
        ),
        Index(
            "idx_device_reservations_device_interval",
            "device_id",
            "starts_at",
            "ends_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    service_campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    lane_id: Mapped[str] = mapped_column(String(36), nullable=False)
    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    release_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    released_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class ReservationAudit(TenantScopedModel, Base):
    __tablename__ = "reservation_audits"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "reservation_id"],
            ["device_reservations.org_id", "device_reservations.id"],
            ondelete="RESTRICT",
            name="fk_reservation_audit_reservation_org",
        ),
        Index(
            "idx_reservation_audits_reservation_time", "reservation_id", "created_at"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    reservation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
