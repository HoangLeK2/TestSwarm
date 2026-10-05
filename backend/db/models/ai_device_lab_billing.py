"""Provider-neutral billing records for the AI Device Lab service."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from tenancy.models import TenantScopedModel

from .utils import _now, _uuid


class ServiceOrder(TenantScopedModel, Base):
    __tablename__ = "service_orders"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_service_orders_org_id"),
        UniqueConstraint("org_id", "idempotency_key", name="uq_service_orders_idempotency"),
        ForeignKeyConstraint(
            ["org_id", "service_campaign_id"],
            ["service_campaigns.org_id", "service_campaigns.id"],
            ondelete="RESTRICT",
            name="fk_service_orders_campaign_org",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    service_campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    plan_version: Mapped[str] = mapped_column(String(64), nullable=False)
    pricing_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    quota_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    refunded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class PaymentIntent(TenantScopedModel, Base):
    __tablename__ = "payment_intents"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_payment_intents_org_id"),
        UniqueConstraint("org_id", "order_id", name="uq_payment_intents_order"),
        UniqueConstraint("provider", "provider_reference", name="uq_payment_intents_provider_ref"),
        UniqueConstraint("org_id", "idempotency_key", name="uq_payment_intents_idempotency"),
        ForeignKeyConstraint(
            ["org_id", "order_id"],
            ["service_orders.org_id", "service_orders.id"],
            ondelete="RESTRICT",
            name="fk_payment_intents_order_org",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    order_id: Mapped[str] = mapped_column(String(36), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    checkout_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class PaymentEvent(TenantScopedModel, Base):
    __tablename__ = "payment_events"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_payment_events_provider_event"),
        ForeignKeyConstraint(
            ["org_id", "order_id"],
            ["service_orders.org_id", "service_orders.id"],
            ondelete="RESTRICT",
            name="fk_payment_events_order_org",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    order_id: Mapped[str] = mapped_column(String(36), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_minor: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    signature_verified: Mapped[bool] = mapped_column(nullable=False)
    source_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    processing_state: Mapped[str] = mapped_column(String(32), nullable=False, default="accepted")
    reason_code: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)


class ServiceEntitlement(TenantScopedModel, Base):
    __tablename__ = "service_entitlements"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_service_entitlements_org_id"),
        UniqueConstraint("org_id", "order_id", name="uq_service_entitlements_order"),
        ForeignKeyConstraint(
            ["org_id", "order_id"],
            ["service_orders.org_id", "service_orders.id"],
            ondelete="RESTRICT",
            name="fk_service_entitlements_order_org",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    order_id: Mapped[str] = mapped_column(String(36), nullable=False)
    service_campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("service_campaigns.id", ondelete="RESTRICT"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ServiceRefund(TenantScopedModel, Base):
    __tablename__ = "service_refunds"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_service_refunds_org_id"),
        UniqueConstraint("org_id", "idempotency_key", name="uq_service_refunds_idempotency"),
        ForeignKeyConstraint(
            ["org_id", "order_id"],
            ["service_orders.org_id", "service_orders.id"],
            ondelete="RESTRICT",
            name="fk_service_refunds_order_org",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    order_id: Mapped[str] = mapped_column(String(36), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class RefundDispatchJob(TenantScopedModel, Base):
    __tablename__ = "refund_dispatch_jobs"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "refund_id",
            name="uq_refund_dispatch_refund",
        ),
        ForeignKeyConstraint(
            ["org_id", "refund_id"],
            ["service_refunds.org_id", "service_refunds.id"],
            ondelete="RESTRICT",
            name="fk_refund_dispatch_refund_org",
        ),
        ForeignKeyConstraint(
            ["org_id", "order_id"],
            ["service_orders.org_id", "service_orders.id"],
            ondelete="RESTRICT",
            name="fk_refund_dispatch_order_org",
        ),
        Index(
            "idx_refund_dispatch_delivery",
            "status",
            "available_at",
            "lease_until",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    refund_id: Mapped[str] = mapped_column(String(36), nullable=False)
    order_id: Mapped[str] = mapped_column(String(36), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    payment_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class PaymentReconciliationJob(TenantScopedModel, Base):
    __tablename__ = "payment_reconciliation_jobs"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "idempotency_key",
            name="uq_payment_reconciliation_idempotency",
        ),
        ForeignKeyConstraint(
            ["org_id", "order_id"],
            ["service_orders.org_id", "service_orders.id"],
            ondelete="RESTRICT",
            name="fk_payment_reconciliation_order_org",
        ),
        Index(
            "idx_payment_reconciliation_delivery",
            "status",
            "available_at",
            "lease_until",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    order_id: Mapped[str] = mapped_column(String(36), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_lookup_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
