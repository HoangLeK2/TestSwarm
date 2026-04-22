from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from .utils import _now, _uuid


class RelayAgent(Base):
    __tablename__ = "relay_agents"

    id:       Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    relay_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    hostname: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    ip:       Mapped[str] = mapped_column(String(64),  default="", nullable=False)
    version:  Mapped[str] = mapped_column(String(32),  default="", nullable=False)
    serials:  Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status:   Mapped[str] = mapped_column(String(16), default="online", nullable=False)

    connected_at:      Mapped[datetime]           = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    disconnected_at:   Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at:        Mapped[datetime]           = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
