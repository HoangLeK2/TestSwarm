from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base
from tenancy.models import TenantScopedModel
from .utils import _now, _uuid


class AccountGroup(TenantScopedModel, Base):
    """Logical pool of accounts used for per-device rotation within a scenario run.

    `rotation_cursor` is bumped atomically inside `pick_next_batch`
    (see db/crud/account_group.py) via `SELECT ... FOR UPDATE` so concurrent
    dispatchers on the same group serialise without an external lock.
    """

    __tablename__ = "account_groups"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_account_groups_user_name"),
        Index("idx_account_groups_user", "user_id"),
        Index("idx_account_groups_platform", "platform"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    rotation_strategy: Mapped[str] = mapped_column(
        String(32), default="round_robin", nullable=False
    )
    rotation_cursor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    members: Mapped[list["AccountGroupMember"]] = relationship(
        "AccountGroupMember",
        back_populates="group",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<AccountGroup id={self.id} name={self.name!r} platform={self.platform!r}>"
        )


class AccountGroupMember(TenantScopedModel, Base):
    """Link row between `account_groups` and `accounts`.

    `position` is preserved by CRUD so round-robin walks members in insertion
    order. `last_used_at` is set by the LRU strategy and by the cursor-based
    strategy as a telemetry signal (used by the UI to highlight stale members).
    """

    __tablename__ = "account_group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "account_id", name="uq_agm_group_account"),
        Index("idx_agm_group_position", "group_id", "position"),
        Index("idx_agm_group_lru", "group_id", "last_used_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    group_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("account_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    group: Mapped["AccountGroup"] = relationship(
        "AccountGroup", back_populates="members"
    )
