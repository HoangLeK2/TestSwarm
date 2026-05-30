"""Device FSM persistence — current state + transition history (DF-T-02-002)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from db.models.enums import DeviceFsmState
from db.models.utils import _now


class DeviceFsmSnapshot(Base):
    """One row per device — canonical FSM state at control plane."""

    __tablename__ = "device_states"

    device_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("devices.id", ondelete="CASCADE"),
        primary_key=True,
    )
    state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=DeviceFsmState.UNKNOWN.value,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
    )
    last_event_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    reconnecting_since: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class DeviceStateTransition(Base):
    """Append-only transition audit log."""

    __tablename__ = "device_state_transitions"
    __table_args__ = (
        Index(
            "ix_device_state_transitions_device_ts",
            "device_id",
            "timestamp",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_state: Mapped[str] = mapped_column(String(32), nullable=False)
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    event_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
    )
    payload: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<DeviceStateTransition device={self.device_id} "
            f"{self.from_state}->{self.to_state} event={self.event}>"
        )
