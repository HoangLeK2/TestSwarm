from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base
from tenancy.models import TenantScopedModel
from .enums import DevicePlatformSessionState
from .utils import _now, _uuid


class DevicePlatformSession(TenantScopedModel, Base):
    """Provenance for the platform account currently believed active on a device."""

    __tablename__ = "device_platform_sessions"
    __table_args__ = (
        UniqueConstraint("org_id", "device_id", "platform", name="uq_device_platform_sessions_device_platform"),
        Index("idx_device_platform_sessions_org_platform_state", "org_id", "platform", "state"),
        Index("idx_device_platform_sessions_org_account_state", "org_id", "account_id", "state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    state: Mapped[str] = mapped_column(
        String(32), nullable=False, default=DevicePlatformSessionState.UNKNOWN.value
    )
    state_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    established_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ready_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    login_attempt_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    establishment_method: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    app_package: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    app_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    display_name_observed: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    device: Mapped["Device"] = relationship("Device")
    account: Mapped[Optional["Account"]] = relationship("Account")
