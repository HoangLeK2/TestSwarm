from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base
from tenancy.models import TenantScopedModel
from .enums import DevicePlatformLoginAttemptState
from .utils import _now, _uuid


class DevicePlatformLoginAttempt(TenantScopedModel, Base):
    """Operator-guided login attempt bound to a device reserve session."""

    __tablename__ = "device_platform_login_attempts"
    __table_args__ = (
        Index("idx_device_platform_login_attempts_org_device_state", "org_id", "device_id", "state"),
        Index("idx_device_platform_login_attempts_org_account_state", "org_id", "account_id", "state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    device_id: Mapped[str] = mapped_column(String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    account_id: Mapped[str] = mapped_column(String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=DevicePlatformLoginAttemptState.PENDING.value,
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reserve_session_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("device_reserve_sessions.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    device: Mapped["Device"] = relationship("Device")
    account: Mapped["Account"] = relationship("Account")
