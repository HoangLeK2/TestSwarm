from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base
from .utils import _now, _uuid


class Campaign(Base):

    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    scenario: Mapped[dict] = mapped_column(JSON, default=dict)
    variables: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="idle")
    target_group_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("device_groups.id", ondelete="SET NULL"), nullable=True
    )  
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    user: Mapped[Optional["User"]] = relationship("User", back_populates="campaigns")
    campaign_devices: Mapped[list["CampaignDevice"]] = relationship(
        "CampaignDevice", back_populates="campaign", cascade="all, delete-orphan"
    )
    scenarios: Mapped[list["Scenario"]] = relationship(
        "Scenario", back_populates="campaign", cascade="all, delete-orphan",
        order_by="Scenario.order",
    )

    def __repr__(self) -> str:  # pragma: no cover - repr
        return f"<Campaign {self.name} status={self.status}>"


class CampaignDevice(Base):
    __tablename__ = "campaign_devices"
    __table_args__ = (UniqueConstraint("campaign_id", "device_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )

    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="campaign_devices")
    device: Mapped["Device"] = relationship("Device")


class Scenario(Base):
    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="Scenario")
    instructions: Mapped[str] = mapped_column(Text, default="")
    steps: Mapped[list] = mapped_column(JSON, default=list)
    nodes: Mapped[list] = mapped_column(JSON, default=list)
    edges: Mapped[list] = mapped_column(JSON, default=list)
    variables: Mapped[dict] = mapped_column(JSON, default=dict)
    order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="scenarios")


class CampaignRun(Base):
    """Tracks each campaign execution run — one record per enqueue_campaign_run call."""

    __tablename__ = "campaign_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    device_serials: Mapped[list] = mapped_column(JSON, default=list)
    workflow_ids: Mapped[list] = mapped_column(JSON, default=list)
    scenarios_count: Mapped[int] = mapped_column(default=0)
    # Summary populated when run completes
    total_saved: Mapped[int] = mapped_column(default=0)
    total_duplicate: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    campaign: Mapped["Campaign"] = relationship("Campaign")

