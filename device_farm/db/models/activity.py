from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from .utils import _now, _uuid


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    entity_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    device_serial: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

    __table_args__ = (
        Index("idx_activity_created", "created_at"),
        Index("idx_activity_action", "action"),
        Index("idx_activity_device", "device_serial"),
        Index("idx_activity_user_created", "user_id", "created_at"),
    )
