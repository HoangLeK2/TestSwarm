"""Immutable report manifests and PDF output metadata."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKeyConstraint, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from tenancy.models import TenantScopedModel

from .utils import _now, _uuid


class ReportSnapshot(TenantScopedModel, Base):
    __tablename__ = "report_snapshots"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_report_snapshots_org_id"),
        UniqueConstraint(
            "org_id", "service_campaign_id", "version", name="uq_report_snapshot_version"
        ),
        UniqueConstraint(
            "org_id", "service_campaign_id", "idempotency_key", name="uq_report_snapshot_key"
        ),
        ForeignKeyConstraint(
            ["org_id", "service_campaign_id"],
            ["service_campaigns.org_id", "service_campaigns.id"],
            ondelete="RESTRICT",
            name="fk_report_snapshot_campaign_org",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    service_campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    builder_version: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest: Mapped[dict] = mapped_column(JSON, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    pdf_object_key: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    pdf_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
