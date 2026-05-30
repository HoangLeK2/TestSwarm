"""Control-plane device reserve sessions (DF-T-02-003)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from .utils import _now, _uuid


class DeviceReserveSession(Base):
    """At most one active row per device (released_at IS NULL)."""

    __tablename__ = "device_reserve_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    owner_type: Mapped[str] = mapped_column(String(20), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    released_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_heartbeat: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ttl_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    release_reason: Mapped[Optional[str]] = mapped_column(String(20))
    ctx: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(String(36))
