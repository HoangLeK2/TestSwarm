"""Append-only lane assignment and recoverable fleet lifecycle operations."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Index, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from tenancy.models import TenantScopedModel

from .utils import _now, _uuid


class LaneDeviceAssignment(TenantScopedModel, Base):
    __tablename__ = "lane_device_assignments"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_lane_device_assignments_org_id"),
        ForeignKeyConstraint(
            ["org_id", "reservation_id"],
            ["device_reservations.org_id", "device_reservations.id"],
            ondelete="RESTRICT",
            name="fk_lane_assignment_reservation_org",
        ),
        Index(
            "uq_current_lane_device_assignment",
            "org_id",
            "service_campaign_id",
            "lane_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
            sqlite_where=text("ended_at IS NULL"),
        ),
        Index("idx_lane_assignments_history", "lane_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    service_campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("service_campaigns.id", ondelete="RESTRICT"), nullable=False
    )
    lane_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("service_lanes.id", ondelete="RESTRICT"), nullable=False
    )
    reservation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)


class FleetLifecycleOperation(TenantScopedModel, Base):
    __tablename__ = "fleet_lifecycle_operations"
    __table_args__ = (
        UniqueConstraint("org_id", "idempotency_key", name="uq_fleet_operation_key"),
        Index("idx_fleet_operations_campaign_status", "service_campaign_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    service_campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("service_campaigns.id", ondelete="RESTRICT"), nullable=False
    )
    lane_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("service_lanes.id", ondelete="RESTRICT"), nullable=True
    )
    operation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    checkpoint: Mapped[str] = mapped_column(String(64), nullable=False)
    old_reservation_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    new_reservation_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    actor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class ServiceExtension(TenantScopedModel, Base):
    __tablename__ = "service_extensions"
    __table_args__ = (
        UniqueConstraint("org_id", "idempotency_key", name="uq_service_extension_key"),
        ForeignKeyConstraint(
            ["org_id", "service_campaign_id"],
            ["service_campaigns.org_id", "service_campaigns.id"],
            ondelete="RESTRICT",
            name="fk_service_extension_campaign_org",
        ),
        ForeignKeyConstraint(
            ["org_id", "order_id"],
            ["service_orders.org_id", "service_orders.id"],
            ondelete="RESTRICT",
            name="fk_service_extension_order_org",
        ),
        ForeignKeyConstraint(
            ["org_id", "entitlement_id"],
            ["service_entitlements.org_id", "service_entitlements.id"],
            ondelete="RESTRICT",
            name="fk_service_extension_entitlement_org",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    service_campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    previous_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    new_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    added_service_days: Mapped[int] = mapped_column(nullable=False)
    consent_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    order_id: Mapped[str] = mapped_column(String(36), nullable=False)
    entitlement_id: Mapped[str] = mapped_column(String(36), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
