from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base
from tenancy.models import TenantScopedModel
from .utils import _now, _uuid, _api_key


class Device(TenantScopedModel, Base):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("org_id", "id", name="uq_devices_org_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    serial: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    device_serial: Mapped[str] = mapped_column(String(128), default="", index=True)
    relay_serial: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, default=None, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(20), default="paired", index=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    # device_key is embedded in the QR code WebSocket URL so the server
    # can authenticate which user this device belongs to.
    device_key: Mapped[str] = mapped_column(String(64), unique=True, default=_api_key, index=True)

    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Device metadata (filled from Android hello/status messages)
    brand: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    android_version: Mapped[str] = mapped_column(String(32), default="")
    sdk_version: Mapped[int] = mapped_column(Integer, default=0)
    screen_width: Mapped[int] = mapped_column(Integer, default=0)
    screen_height: Mapped[int] = mapped_column(Integer, default=0)

    # ADB connection info (last known). Optional; used for diagnostics / future reconnect flows.
    adb_serial: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, default=None, index=True)
    adb_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, default=None)
    adb_port: Mapped[int] = mapped_column(Integer, nullable=False, default=5555)

    tags: Mapped[str] = mapped_column(String(500), default="")

    relay_scrcpy_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    paired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    unpaired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[Optional["User"]] = relationship("User", back_populates="devices")
    sessions: Mapped[list["DeviceSession"]] = relationship(
        "DeviceSession", back_populates="device"
    )
    def __repr__(self) -> str:  # pragma: no cover - repr
        return f"<Device {self.serial} model={self.brand}/{self.model}>"


class DeviceSession(Base):
    """Records every WebSocket connection from a device agent."""

    __tablename__ = "device_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_ip: Mapped[str] = mapped_column(String(64), default="")
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    disconnected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    device: Mapped["Device"] = relationship("Device", back_populates="sessions")

    def __repr__(self) -> str:  # pragma: no cover - repr
        return f"<DeviceSession device={self.device_id} ip={self.client_ip}>"
