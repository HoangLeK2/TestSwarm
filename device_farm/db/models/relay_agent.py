from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
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
    user_id:  Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    enrollment_token_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("relay_agent_tokens.id", ondelete="SET NULL"), nullable=True, index=True
    )

    connected_at:      Mapped[datetime]           = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    disconnected_at:   Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at:        Mapped[datetime]           = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class RelayAgentToken(Base):
    __tablename__ = "relay_agent_tokens"

    id:         Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id:    Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name:       Mapped[str] = mapped_column(String(255), default="", nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    prefix:     Mapped[str] = mapped_column(String(24), default="", nullable=False)
    status:     Mapped[str] = mapped_column(String(16), default="active", nullable=False, index=True)

    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at:   Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at:   Mapped[datetime]           = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class RelayAgentJob(Base):
    __tablename__ = "relay_agent_jobs"

    id:       Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id:  Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    relay_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    kind:     Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status:   Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)

    total:   Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ok:      Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed:  Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pending: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at:  Mapped[datetime]           = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    started_at:  Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at:  Mapped[datetime]           = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class RelayAgentJobItem(Base):
    __tablename__ = "relay_agent_job_items"

    id:        Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id:    Mapped[str] = mapped_column(String(36), ForeignKey("relay_agent_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    serial:    Mapped[str] = mapped_column(String(255), nullable=False)
    device_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("devices.id", ondelete="SET NULL"), nullable=True, index=True)
    status:    Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    step:      Mapped[str] = mapped_column(String(64), default="", nullable=False)
    attempts:  Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error:     Mapped[str] = mapped_column(Text, default="", nullable=False)
    result:    Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    created_at:  Mapped[datetime]           = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    started_at:  Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at:  Mapped[datetime]           = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
