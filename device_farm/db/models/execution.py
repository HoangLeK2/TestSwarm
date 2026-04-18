"""DF-011: Execution coordinator — central table linking campaign, scenario,
devices, content_items and per-device results."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base
from .enums import ExecutionStatus, ExecutionResultStatus
from .utils import _now, _uuid


class ExecutionDevice(Base):
    """Join table: n-n between executions and devices."""

    __tablename__ = "execution_devices"
    __table_args__ = (UniqueConstraint("execution_id", "device_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    execution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("executions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )

    execution: Mapped["Execution"] = relationship("Execution", back_populates="execution_devices")
    device: Mapped["Device"] = relationship("Device")


class Execution(Base):
    """Central coordinator for any kind of run (campaign_run, testrun, schedule_run, …).

    Relationships:
      - 1-1 → Campaign   (optional)
      - 1-1 → Scenario   (optional)
      - n-n → Device     (via ExecutionDevice join table)
      - 1-n → ContentItem
      - 1-n → ExecutionResult (one per device)
    """

    __tablename__ = "executions"
    __table_args__ = (
        Index("idx_executions_run_type", "run_type"),
        Index("idx_executions_status", "status"),
        Index("idx_executions_campaign", "campaign_id"),
        Index("idx_executions_scenario", "scenario_id"),
        Index("idx_executions_user", "user_id"),
        Index("idx_executions_created", "created_at"),
        Index("idx_executions_sv", "scenario_version_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ExecutionStatus.PENDING)

    # 1-1 optional FK references
    campaign_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True
    )
    scenario_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("scenarios.id", ondelete="SET NULL"), nullable=True
    )
    scenario_version_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("scenario_versions.id", ondelete="SET NULL"), nullable=True
    )

    # Behaviour configuration
    device_config: Mapped[dict] = mapped_column(JSON, default=dict)
    loop_config: Mapped[dict] = mapped_column(JSON, default=dict)
    error_config: Mapped[dict] = mapped_column(JSON, default=dict)
    # NOTE: column named "meta" — "metadata" is reserved by SQLAlchemy's DeclarativeBase
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    # Ownership
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Scenario executor resumes from this index on restart (steps must be idempotent).
    checkpoint_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    campaign: Mapped[Optional["Campaign"]] = relationship("Campaign")
    scenario: Mapped[Optional["Scenario"]] = relationship("Scenario")
    scenario_version: Mapped[Optional["ScenarioVersion"]] = relationship("ScenarioVersion")
    execution_devices: Mapped[list["ExecutionDevice"]] = relationship(
        "ExecutionDevice", back_populates="execution", cascade="all, delete-orphan"
    )
    results: Mapped[list["ExecutionResult"]] = relationship(
        "ExecutionResult", back_populates="execution", cascade="all, delete-orphan"
    )
    content_items: Mapped[list["ContentItem"]] = relationship(
        "ContentItem",
        back_populates="execution",
        foreign_keys="ContentItem.execution_id",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Execution {self.id[:8]} run_type={self.run_type} status={self.status}>"


class ExecutionResult(Base):
    """Per-device result for an execution — one row per (execution, device) pair."""

    __tablename__ = "execution_results"
    __table_args__ = (
        UniqueConstraint("execution_id", "device_id", name="uq_execution_result_exec_device"),
        Index("idx_exec_results_execution", "execution_id"),
        Index("idx_exec_results_device", "device_id"),
        Index("idx_exec_results_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    execution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("executions.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ExecutionResultStatus.PENDING)
    run_time_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    passed_steps: Mapped[list] = mapped_column(JSON, default=list)
    failed_steps: Mapped[list] = mapped_column(JSON, default=list)
    error_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    execution: Mapped["Execution"] = relationship("Execution", back_populates="results")
    device: Mapped["Device"] = relationship("Device")
