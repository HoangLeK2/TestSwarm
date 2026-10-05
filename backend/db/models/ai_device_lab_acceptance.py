"""Versioned launch acceptance inventory and signed decisions."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from tenancy.models import TenantScopedModel

from .utils import _now, _uuid


class AcceptanceCandidate(TenantScopedModel, Base):
    __tablename__ = "acceptance_candidates"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_acceptance_candidates_org_id"),
        UniqueConstraint("org_id", "version", name="uq_acceptance_candidate_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    environment: Mapped[str] = mapped_column(String(64), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    rollback_owner: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    oncall_owner: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    frozen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class AcceptanceRequirement(TenantScopedModel, Base):
    __tablename__ = "acceptance_requirements"
    __table_args__ = (
        UniqueConstraint("org_id", "candidate_id", "requirement_key", name="uq_acceptance_requirement"),
        ForeignKeyConstraint(
            ["org_id", "candidate_id"],
            ["acceptance_candidates.org_id", "acceptance_candidates.id"],
            ondelete="RESTRICT",
            name="fk_acceptance_requirement_candidate_org",
        ),
        Index("idx_acceptance_requirement_status", "candidate_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    candidate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    requirement_key: Mapped[str] = mapped_column(String(128), nullable=False)
    adl_id: Mapped[str] = mapped_column(String(16), nullable=False)
    acceptance_id: Mapped[str] = mapped_column(String(32), nullable=False)
    test_id: Mapped[str] = mapped_column(String(32), nullable=False)
    expected: Mapped[str] = mapped_column(Text, nullable=False)
    observed: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    required_evidence_level: Mapped[str] = mapped_column(String(16), nullable=False)
    observed_evidence_level: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    reviewer_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    blocker: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class AcceptanceDecision(TenantScopedModel, Base):
    __tablename__ = "acceptance_decisions"
    __table_args__ = (
        UniqueConstraint("org_id", "candidate_id", "evaluation_key", name="uq_acceptance_decision_key"),
        ForeignKeyConstraint(
            ["org_id", "candidate_id"],
            ["acceptance_candidates.org_id", "acceptance_candidates.id"],
            ondelete="RESTRICT",
            name="fk_acceptance_decision_candidate_org",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    candidate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    evaluation_key: Mapped[str] = mapped_column(String(128), nullable=False)
    verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    blockers: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    requirement_summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    pack_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    signer_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
