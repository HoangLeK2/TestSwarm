"""Per-organization reconnect backoff policy (DF-T-02-006)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from .utils import _now


class ReconnectPolicy(Base):
    __tablename__ = "reconnect_policies"

    org_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    interval_base_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    max_interval_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=60000)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    jitter_factor: Mapped[float] = mapped_column(Float, nullable=False, default=0.2)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
