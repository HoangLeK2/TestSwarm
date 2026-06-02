"""ExecutionStep — per-step checkpoint row for Epic 04 runtime (DF-T-04-010)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from .utils import _now, _uuid


class ExecutionStep(Base):
    """One row per scenario step index within an execution."""

    __tablename__ = "execution_steps"
    __table_args__ = (
        UniqueConstraint("execution_id", "step_index", name="uq_execution_steps_exec_index"),
        Index("idx_execution_steps_exec_index", "execution_id", "step_index"),
        Index("idx_execution_steps_exec_status", "execution_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    execution_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("executions.id", ondelete="CASCADE"),
        nullable=False,
    )
    device_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("devices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    step_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    step_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    error_json: Mapped[dict] = mapped_column(JSON, default=dict)
    effective_config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    artifacts_json: Mapped[list] = mapped_column(JSON, default=list)
    attempts_json: Mapped[list] = mapped_column(JSON, default=list)
    marked_ignored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ExecutionStep exec={self.execution_id[:8]} "
            f"idx={self.step_index} status={self.status}>"
        )
