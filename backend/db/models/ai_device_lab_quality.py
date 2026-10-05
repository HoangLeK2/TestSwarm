"""App issue and retest lineage over immutable build/run snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from tenancy.models import TenantScopedModel

from .utils import _now, _uuid


class AppIssue(TenantScopedModel, Base):
    __tablename__ = "app_issues"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_app_issues_org_id"),
        ForeignKeyConstraint(
            ["org_id", "source_attempt_id"],
            ["run_attempts.org_id", "run_attempts.id"],
            ondelete="RESTRICT",
            name="fk_app_issue_source_attempt_org",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    service_campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_attempt_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_build_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("app_builds.id", ondelete="RESTRICT"), nullable=False
    )
    source_scenario_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scenario_versions.id", ondelete="RESTRICT"), nullable=False
    )
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    assertion_key: Mapped[str] = mapped_column(String(255), nullable=False)
    expected: Mapped[str] = mapped_column(Text, nullable=False)
    actual: Mapped[str] = mapped_column(Text, nullable=False)
    reproduction: Mapped[dict] = mapped_column(JSON, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class RetestRequest(TenantScopedModel, Base):
    __tablename__ = "retest_requests"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_retest_requests_org_id"),
        UniqueConstraint("org_id", "idempotency_key", name="uq_retest_requests_idempotency"),
        ForeignKeyConstraint(
            ["org_id", "issue_id"],
            ["app_issues.org_id", "app_issues.id"],
            ondelete="RESTRICT",
            name="fk_retest_request_issue_org",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    issue_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_attempt_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("run_attempts.id", ondelete="RESTRICT"), nullable=False
    )
    target_build_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("app_builds.id", ondelete="RESTRICT"), nullable=False
    )
    target_scenario_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scenario_versions.id", ondelete="RESTRICT"), nullable=False
    )
    lane_scope: Mapped[list] = mapped_column(JSON, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    consent_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="requested")
    new_attempt_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("run_attempts.id", ondelete="RESTRICT"), nullable=True
    )
    verdict: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    verdict_reason: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    requested_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class IssueTransition(TenantScopedModel, Base):
    __tablename__ = "issue_transitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    issue_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("app_issues.id", ondelete="RESTRICT"), nullable=False
    )
    from_status: Mapped[str] = mapped_column(String(32), nullable=False)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
