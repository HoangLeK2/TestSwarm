"""Org-scoped scenario library entity (DF-T-04-001).

Distinct from campaign-embedded ``Scenario`` rows in ``campaign.py`` — this
model backs ``GET/POST /api/scenarios`` for reusable scenario definitions.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base
from db.models.enums import OrgScenarioStatus, ScenarioKind
from tenancy.models import TenantScopedModel
from .utils import _now, _uuid

if TYPE_CHECKING:
    from db.models.campaign import Campaign


class OrgScenario(TenantScopedModel, Base):
    __tablename__ = "org_scenarios"
    __table_args__ = (
        Index("idx_org_scenarios_org_status", "org_id", "status"),
        Index(
            "uq_org_scenarios_org_name_active",
            "org_id",
            "name_lower",
            unique=True,
            postgresql_where="deleted_at IS NULL AND status != 'archived'",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_lower: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ScenarioKind.SEQUENCE.value
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=OrgScenarioStatus.DRAFT.value
    )
    scenario_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    body_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    last_validation_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    last_validated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    tags: Mapped[list["OrgScenarioTag"]] = relationship(
        "OrgScenarioTag",
        back_populates="scenario",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<OrgScenario {self.name!r} v={self.scenario_version} status={self.status}>"


class OrgScenarioTag(Base):
    __tablename__ = "org_scenario_tags"
    __table_args__ = (
        UniqueConstraint("org_scenario_id", "tag", name="uq_org_scenario_tags"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_scenario_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("org_scenarios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tag: Mapped[str] = mapped_column(String(100), nullable=False)

    scenario: Mapped["OrgScenario"] = relationship("OrgScenario", back_populates="tags")


class CampaignOrgScenarioRef(Base):
    """Links campaigns to org-scoped scenarios with pinned version (DF-T-04-006)."""

    __tablename__ = "campaign_org_scenario_refs"
    __table_args__ = (
        UniqueConstraint("campaign_id", "org_scenario_id", name="uq_campaign_org_scenario"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    campaign_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    org_scenario_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("org_scenarios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pinned_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="org_scenario_refs")
    org_scenario: Mapped["OrgScenario"] = relationship("OrgScenario")
