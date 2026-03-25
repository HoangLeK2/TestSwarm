from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base
from .utils import _now, _uuid, _api_key


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    serial: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")

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
    adb_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, default=None)
    adb_port: Mapped[int] = mapped_column(Integer, nullable=False, default=5555)

    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

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

