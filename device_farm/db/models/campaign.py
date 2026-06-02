from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base
from tenancy.models import TenantScopedModel
from .enums import CampaignStatus
from .utils import _now, _uuid


class Campaign(TenantScopedModel, Base):

    __tablename__ = "campaigns"
    __table_args__ = (
        Index(
            "uq_campaigns_org_name_active",
            "org_id",
            "name_lower",
            unique=True,
            postgresql_where="deleted_at IS NULL AND status != 'archived'",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_lower: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    variables: Mapped[dict] = mapped_column(JSON, default=dict)
    per_device_overrides: Mapped[dict] = mapped_column(JSON, default=dict)
    account_group_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("account_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    scenario_account_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    per_device_accounts: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default=CampaignStatus.DRAFT)
    target_group_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("device_groups.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    user: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="campaigns",
        foreign_keys=[user_id],
    )
    campaign_devices: Mapped[list["CampaignDevice"]] = relationship(
        "CampaignDevice", back_populates="campaign", cascade="all, delete-orphan"
    )
    scenarios: Mapped[list["Scenario"]] = relationship(
        "Scenario", back_populates="campaign", cascade="all, delete-orphan",
        order_by="Scenario.order",
    )
    org_scenario_refs: Mapped[list["CampaignOrgScenarioRef"]] = relationship(
        "CampaignOrgScenarioRef",
        back_populates="campaign",
        cascade="all, delete-orphan",
        order_by="CampaignOrgScenarioRef.order_index",
    )
    tags: Mapped[list["CampaignTag"]] = relationship(
        "CampaignTag",
        back_populates="campaign",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    dispatch_targets: Mapped[list["CampaignTarget"]] = relationship(
        "CampaignTarget",
        back_populates="campaign",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - repr
        return f"<Campaign {self.name} status={self.status}>"


class CampaignTarget(Base):
    """Snapshot of resolved dispatch targets for one fan-out batch (DF-T-04-008)."""

    __tablename__ = "campaign_targets"
    __table_args__ = (
        Index("idx_campaign_targets_campaign", "campaign_id"),
        Index("idx_campaign_targets_dispatch", "dispatch_id"),
        Index("idx_campaign_targets_campaign_dispatch", "campaign_id", "dispatch_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    dispatch_id: Mapped[str] = mapped_column(String(36), nullable=False)
    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    source_ref_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="dispatch_targets")
    device: Mapped["Device"] = relationship("Device")


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
    # Optional link to an account_groups row. NULL means "use the device's
    # primary account" (legacy path). When the group is deleted, the FK is
    # set to NULL so the scenario still runs.
    account_group_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("account_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    order: Mapped[int] = mapped_column(default=0)
    last_validation_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    last_validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="scenarios")


class CampaignTag(Base):
    __tablename__ = "campaign_tags"
    __table_args__ = (
        UniqueConstraint("campaign_id", "tag", name="uq_campaign_tags"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    campaign_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tag: Mapped[str] = mapped_column(String(100), nullable=False)

    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="tags")

