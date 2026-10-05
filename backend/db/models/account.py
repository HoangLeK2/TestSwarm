from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base
from tenancy.models import TenantScopedModel
from .enums import AccountState, AccountStatus
from .utils import _now, _uuid


class Account(TenantScopedModel, Base):
    """
    Social media account managed by Device Farm.

    Passwords are Fernet-encrypted. Production/staging credential paths reject
    missing or invalid ACCOUNT_ENCRYPTION_KEY before storage or execution.

    Lifecycle FSM (DF-T-07-005) — canonical field ``state``; ``status`` kept in sync.
    """

    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("org_id", "platform", "username", name="uq_accounts_org_platform_username"),
        Index("idx_accounts_org_platform_status", "org_id", "platform", "status"),
        Index("idx_accounts_platform", "platform"),
        Index("idx_accounts_status", "status"),
        Index("idx_accounts_state", "state"),
        Index("idx_accounts_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    password_encrypted: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(20), default=AccountState.ACTIVE)
    state: Mapped[str] = mapped_column(String(20), default=AccountState.ACTIVE)
    state_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    state_changed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    cooldown_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Optional future FK to a proxy pool (DF-013). Not enforced now — just stored.
    proxy_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    # Extra data: cookies, tokens, 2fa_secret, avatar_url, etc.
    # Python attr name differs from column name to avoid SQLAlchemy Base.metadata clash.
    account_metadata: Mapped[dict] = mapped_column(
        "metadata", JSON, default=dict, nullable=False
    )

    notes: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(String(500), default="")

    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Usage tracking (minutes). Reset daily by account_manager background task.
    total_usage_minutes: Mapped[float] = mapped_column(Float, default=0.0)
    usage_today_minutes: Mapped[float] = mapped_column(Float, default=0.0)
    usage_reset_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    device_links: Mapped[list["DeviceAccount"]] = relationship(
        "DeviceAccount", back_populates="account", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Account {self.platform}:{self.username!r} "
            f"state={self.state!r} status={self.status!r}>"
        )


class DeviceAccount(Base):
    """
    Many-to-many link between Device and Account.

    One device can have multiple accounts (e.g. several FB accounts in rotation),
    but only one is marked is_primary=True per device (enforced in CRUD).
    Both sides CASCADE-delete their links, leaving the other entity intact.
    """

    __tablename__ = "device_accounts"
    __table_args__ = (
        UniqueConstraint("device_id", "account_id", name="uq_da_device_account"),
        Index("idx_da_device", "device_id"),
        Index("idx_da_account", "account_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    verification_status: Mapped[str] = mapped_column(String(20), default="unknown")
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verification_attempted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verification_evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    account: Mapped["Account"] = relationship("Account", back_populates="device_links")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<DeviceAccount device={self.device_id} "
            f"account={self.account_id} primary={self.is_primary}>"
        )
