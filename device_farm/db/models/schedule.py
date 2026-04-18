"""
db/models/schedule.py — Schedule + ScheduleRun ORM models (DF-008).

- Schedule: cron config, target, device filter, randomization settings
- ScheduleRun: execution history per schedule trigger
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base
from .enums import RunStatus, ScheduleTargetType
from .utils import _now, _uuid


class Schedule(Base):
    """A recurring cron-based schedule that triggers campaign/template/fleet execution."""

    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")

    # ── Target: what to run ───────────────────────────────────────────────────
    target_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # campaign | template | fleet
    target_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    inline_steps: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    inline_variables: Mapped[dict] = mapped_column(JSON, default=dict)

    # ── Device targeting ──────────────────────────────────────────────────────
    device_group_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("device_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    filter_state: Mapped[str] = mapped_column(String(20), default="READY")
    filter_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    max_devices: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ── Cron config ───────────────────────────────────────────────────────────
    cron_expression: Mapped[str] = mapped_column(String(100), nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Ho_Chi_Minh")

    # ── Randomization ─────────────────────────────────────────────────────────
    random_delay_min: Mapped[int] = mapped_column(Integer, default=0)
    random_delay_max: Mapped[int] = mapped_column(Integer, default=0)
    stagger_devices: Mapped[bool] = mapped_column(Boolean, default=False)
    stagger_interval_seconds: Mapped[int] = mapped_column(Integer, default=60)

    # ── Status ────────────────────────────────────────────────────────────────
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    run_count: Mapped[int] = mapped_column(Integer, default=0)

    # ── Meta ──────────────────────────────────────────────────────────────────
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    runs: Mapped[list["ScheduleRun"]] = relationship(
        "ScheduleRun", back_populates="schedule", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_schedules_enabled", "is_enabled"),
        Index("idx_schedules_next_run", "next_run_at"),
        Index("idx_schedules_user", "user_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Schedule {self.name!r} cron={self.cron_expression!r} enabled={self.is_enabled}>"


class ScheduleRun(Base):
    """Execution history record for a single schedule trigger."""

    __tablename__ = "schedule_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    schedule_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("schedules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), default=RunStatus.PENDING)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    devices_dispatched: Mapped[int] = mapped_column(Integer, default=0)
    devices_succeeded: Mapped[int] = mapped_column(Integer, default=0)
    devices_failed: Mapped[int] = mapped_column(Integer, default=0)
    task_ids: Mapped[list] = mapped_column(JSON, default=list)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # ── Relationships ─────────────────────────────────────────────────────────
    schedule: Mapped["Schedule"] = relationship("Schedule", back_populates="runs")

    __table_args__ = (
        Index("idx_schedule_runs_schedule", "schedule_id"),
        Index("idx_schedule_runs_status", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ScheduleRun schedule={self.schedule_id!r} status={self.status!r}>"
