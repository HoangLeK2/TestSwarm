from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, JSON, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base
from .utils import _now


class ScenarioDeviceVariable(Base):
    """Per-(scenario, device) variable overrides for runtime interpolation."""

    __tablename__ = "scenario_device_variables"

    scenario_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("scenarios.id", ondelete="CASCADE"),
        primary_key=True,
    )
    device_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("devices.id", ondelete="CASCADE"),
        primary_key=True,
    )
    vars: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
        onupdate=_now,
    )

    scenario: Mapped["Scenario"] = relationship("Scenario")
    device: Mapped["Device"] = relationship("Device")


class CampaignOrgScenarioDeviceVariable(Base):
    """Per-(campaign org-scenario, device) variable overrides.

    Org-scenario ids are reusable across campaigns and are not rows in the
    legacy ``scenarios`` table, so they need their own scoped storage.
    """

    __tablename__ = "campaign_org_scenario_device_variables"

    campaign_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        primary_key=True,
    )
    org_scenario_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("org_scenarios.id", ondelete="CASCADE"),
        primary_key=True,
    )
    device_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("devices.id", ondelete="CASCADE"),
        primary_key=True,
    )
    vars: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
        onupdate=_now,
    )

    device: Mapped["Device"] = relationship("Device")
