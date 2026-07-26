"""Reusable external sources, observations, discoveries, and run assignments."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from tenancy.models import TenantScopedModel
from .utils import _now, _uuid

_JSON_DOCUMENT = JSON().with_variant(JSONB, "postgresql")


class ExternalEntity(TenantScopedModel, Base):
    """Stable org-owned identity for a source on an external platform."""

    __tablename__ = "external_entities"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "platform",
            "entity_type",
            "identity_key",
            name="uq_external_entities_identity",
        ),
        UniqueConstraint("org_id", "id", name="uq_external_entities_org_id"),
        Index(
            "idx_external_entities_catalog",
            "org_id",
            "platform",
            "entity_type",
            "status",
        ),
        Index("idx_external_entities_last_seen", "org_id", "last_seen_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    identity_key: Mapped[str] = mapped_column(String(80), nullable=False)
    identity_confidence: Mapped[str] = mapped_column(
        String(24), nullable=False, default="name_only"
    )
    external_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    canonical_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    display_name: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="candidate")
    current_attributes: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, default=dict
    )
    current_metrics: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, default=dict
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class ExternalEntityObservation(TenantScopedModel, Base):
    """Time-stamped mutable facts observed for an external entity."""

    __tablename__ = "external_entity_observations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "external_entity_id"],
            ["external_entities.org_id", "external_entities.id"],
            ondelete="CASCADE",
            name="fk_external_entity_observations_org_entity",
        ),
        Index(
            "idx_external_entity_observations_entity_time",
            "org_id",
            "external_entity_id",
            "observed_at",
        ),
        Index(
            "idx_external_entity_observations_execution",
            "org_id",
            "execution_id",
        ),
        Index(
            "uq_external_entity_observations_execution_entity",
            "org_id",
            "external_entity_id",
            "execution_id",
            unique=True,
            postgresql_where=text("execution_id IS NOT NULL"),
            sqlite_where=text("execution_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    external_entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    display_name: Mapped[str] = mapped_column(String(500), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, default=dict)
    raw_data: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, default=dict)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    execution_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("executions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class ExternalEntityDiscovery(TenantScopedModel, Base):
    """Search/query context explaining how an entity was discovered."""

    __tablename__ = "external_entity_discoveries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "external_entity_id"],
            ["external_entities.org_id", "external_entities.id"],
            ondelete="CASCADE",
            name="fk_external_entity_discoveries_org_entity",
        ),
        Index(
            "idx_external_entity_discoveries_query_time",
            "org_id",
            "query",
            "observed_at",
        ),
        Index(
            "idx_external_entity_discoveries_entity_time",
            "org_id",
            "external_entity_id",
            "observed_at",
        ),
        Index(
            "uq_external_entity_discoveries_execution_query",
            "org_id",
            "external_entity_id",
            "execution_id",
            "query",
            unique=True,
            postgresql_where=text("execution_id IS NOT NULL"),
            sqlite_where=text("execution_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    external_entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    query: Mapped[str] = mapped_column(String(500), nullable=False)
    rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    context: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, default=dict)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    execution_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("executions.id", ondelete="SET NULL"), nullable=True
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class ExecutionEntityAssignment(TenantScopedModel, Base):
    """Immutable dispatch-time mapping between one execution/device and one entity."""

    __tablename__ = "execution_entity_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "external_entity_id"],
            ["external_entities.org_id", "external_entities.id"],
            ondelete="RESTRICT",
            name="fk_execution_entity_assignments_org_entity",
        ),
        UniqueConstraint(
            "org_id",
            "execution_id",
            "assignment_key",
            name="uq_execution_entity_assignments_execution_key",
        ),
        UniqueConstraint(
            "org_id",
            "dispatch_id",
            "external_entity_id",
            name="uq_execution_entity_assignments_dispatch_entity",
        ),
        Index(
            "idx_execution_entity_assignments_dispatch",
            "org_id",
            "dispatch_id",
        ),
        Index(
            "idx_execution_entity_assignments_device",
            "org_id",
            "device_id",
            "assigned_at",
        ),
        Index(
            "idx_execution_entity_assignments_active_source",
            "org_id",
            "external_entity_id",
            postgresql_where=text(
                "completed_at IS NULL AND status = 'assigned'"
            ),
            sqlite_where=text(
                "completed_at IS NULL AND status = 'assigned'"
            ),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dispatch_id: Mapped[str] = mapped_column(String(36), nullable=False)
    execution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("executions.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    external_entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assignment_key: Mapped[str] = mapped_column(
        String(64), nullable=False, default="primary"
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="assigned")
    snapshot: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, default=dict)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
