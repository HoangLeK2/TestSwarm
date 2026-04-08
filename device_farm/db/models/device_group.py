from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base
from .utils import _now, _uuid


class DeviceGroup(Base):
    """
    A logical grouping of devices (e.g. "FB Farm", "TikTok Farm").

    Campaigns and fleet runs can target a group instead of individual devices.
    Unique per (name, user_id): two users can share a group name without conflict.
    """

    __tablename__ = "device_groups"
    __table_args__ = (
        UniqueConstraint("name", "user_id", name="uq_device_groups_name_user"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(7), default="#6366f1")
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    members: Mapped[list["DeviceGroupMember"]] = relationship(
        "DeviceGroupMember", back_populates="group", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DeviceGroup {self.name!r}>"


class DeviceGroupMember(Base):
    """
    Maps a device to a group (many-to-many with extra metadata).

    A device can belong to multiple groups.
    Cascade DELETE on group removal — the device itself is untouched.
    """

    __tablename__ = "device_group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "device_id", name="uq_dgm_group_device"),
        Index("idx_dgm_group", "group_id"),
        Index("idx_dgm_device", "device_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("device_groups.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    group: Mapped["DeviceGroup"] = relationship("DeviceGroup", back_populates="members")
    device: Mapped["Device"] = relationship("Device")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DeviceGroupMember group={self.group_id} device={self.device_id}>"
