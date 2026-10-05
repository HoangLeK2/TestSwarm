"""
db/models/device_event.py — DeviceEvent: persistent device event log.

Tracks state changes, disconnects, errors, reconnects for audit and
real-time notification to the frontend dashboard.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from db.models.utils import _now, _uuid


class DeviceEvent(Base):
    __tablename__ = "device_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    serial: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    event: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reason: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    old_state: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    new_state: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    device_model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    device_brand: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    extra_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False, index=True,
    )
