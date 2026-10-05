"""Per-account discovery lifecycle shared by social platforms."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from tenancy.models import TenantScopedModel

from .utils import _now, _uuid

ACCOUNT_DISCOVERY_STATUSES = (
    "uninitialized",
    "discovery_requested",
    "discovering",
    "ready",
    "active",
    "error",
)


class AccountDiscoveryState(TenantScopedModel, Base):
    __tablename__ = "account_discovery_states"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "account_id",
            "platform",
            name="uq_account_discovery_states_identity",
        ),
        CheckConstraint(
            "status IN ("
            + ", ".join(f"'{status}'" for status in ACCOUNT_DISCOVERY_STATUSES)
            + ")",
            name="ck_account_discovery_states_status",
        ),
        Index(
            "idx_account_discovery_states_due",
            "org_id",
            "platform",
            "status",
            "next_discovery_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="uninitialized"
    )
    initialized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    discovery_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    discovery_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_discovery_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_discovery_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )
