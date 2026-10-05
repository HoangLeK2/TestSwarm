"""Append-only, privacy-bounded acquisition funnel events."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKeyConstraint,
    Index,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from tenancy.models import TenantScopedModel

from .utils import _now, _uuid


class AiLabFunnelEvent(TenantScopedModel, Base):
    __tablename__ = "ai_lab_funnel_events"
    __table_args__ = (
        UniqueConstraint("org_id", "event_id", name="uq_ai_lab_funnel_event_id"),
        UniqueConstraint(
            "org_id",
            "service_campaign_id",
            "event_name",
            name="uq_ai_lab_funnel_campaign_step",
        ),
        ForeignKeyConstraint(
            ["org_id", "service_campaign_id"],
            ["service_campaigns.org_id", "service_campaigns.id"],
            ondelete="RESTRICT",
            name="fk_ai_lab_funnel_campaign_org",
        ),
        Index(
            "idx_ai_lab_funnel_campaign_time",
            "org_id",
            "service_campaign_id",
            "source_occurred_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    service_campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    acquisition_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_name: Mapped[str] = mapped_column(String(32), nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attribution: Mapped[dict[str, str]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    source_occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
