from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, JSON
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from db.models.utils import _now


class U2RecoveryEvent(Base):
    __tablename__ = "u2_recovery_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    serial: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    event: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    outcome: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    host: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    extra_data: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)

