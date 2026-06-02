"""ExecutionDLQ — dead-letter queue for persistently failed execution results."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base
from .enums import DLQStatus
from .utils import _now, _uuid


class ExecutionDLQ(Base):
    """Row created when an ExecutionResult reaches status 'failed' or 'error'
    and all Temporal retries have been exhausted.

    Use the API to:
      - list DLQ entries (GET /api/executions/dlq)
      - re-enqueue a failed run (POST /api/executions/dlq/{id}/retry)
      - dismiss without retrying (DELETE /api/executions/dlq/{id})
    """

    __tablename__ = "execution_dlq"
    __table_args__ = (
        Index("idx_dlq_execution", "execution_id"),
        Index("idx_dlq_device", "device_serial"),
        Index("idx_dlq_status", "status"),
        Index("idx_dlq_created", "created_at"),
        Index("idx_dlq_campaign_status", "campaign_id", "status"),
        Index(
            "uq_dlq_open_execution_device",
            "execution_id",
            "device_serial",
            unique=True,
            postgresql_where=text("status IN ('pending','retrying')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    execution_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("executions.id", ondelete="CASCADE"),
        nullable=False,
    )
    device_serial: Mapped[str] = mapped_column(String(128), nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default=DLQStatus.PENDING)

    failed_step_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    close_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    replayed_to_execution_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    artifact_refs: Mapped[dict] = mapped_column(JSON, default=dict)
    campaign_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )

    execution: Mapped["Execution"] = relationship("Execution")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ExecutionDLQ {self.id[:8]} exec={self.execution_id[:8]} device={self.device_serial}>"
