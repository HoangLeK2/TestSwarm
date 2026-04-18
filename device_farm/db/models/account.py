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
from .enums import AccountStatus
from .utils import _now, _uuid


class Account(Base):
    """
    Social media account managed by Device Farm.

    Passwords are stored Fernet-encrypted when ACCOUNT_ENCRYPTION_KEY env var is set.
    In dev mode (no key) passwords are stored in plaintext.

    Status state machine:
        active ↔ cooldown  (auto via usage limit / background reset)
        active → banned    (manual or auto-detect)
        active → disabled  (manual)
        banned/disabled → active  (manual reset)
    """

    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("platform", "username", name="uq_accounts_platform_username"),
        Index("idx_accounts_platform", "platform"),
        Index("idx_accounts_status", "status"),
        Index("idx_accounts_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    password_encrypted: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(20), default=AccountStatus.ACTIVE)

    # Cooldown: set by account_manager when daily usage limit is hit.
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
        return f"<Account {self.platform}:{self.username!r} status={self.status!r}>"


class DeviceAccount(Base):
    """
    Many-to-many link between Device and Account.

    One device can have multiple accounts (e.g. several FB accounts in rotation),
    but only one is marked is_primary=True per device (per platform, enforced in CRUD).
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

    account: Mapped["Account"] = relationship("Account", back_populates="device_links")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<DeviceAccount device={self.device_id} "
            f"account={self.account_id} primary={self.is_primary}>"
        )
