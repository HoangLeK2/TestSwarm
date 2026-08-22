"""Org-scoped social connection candidate models.

The table names still say "facebook" for historical reasons, but the model is
platform-neutral: every row carries `platform`, and TikTok/Instagram/Threads
reuse these tables rather than duplicating the schema. New code should import
the neutral aliases (`SocialCandidate`, `SOCIAL_CANDIDATE_STATUSES`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    desc,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base
from tenancy.models import TenantScopedModel

from .utils import _now, _uuid

_JSON_DOCUMENT = JSON().with_variant(JSONB, "postgresql")

FACEBOOK_CANDIDATE_STATUSES = (
    "discovered",
    "review_required",
    "approved",
    "rejected",
    "deferred",
    "warming_up",
    "ready_to_connect",
    "request_pending",
    "connected",
    "blocked",
)


class FacebookCandidate(TenantScopedModel, Base):
    __tablename__ = "facebook_candidates"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "account_id",
            "external_entity_id",
            name="uq_facebook_candidates_identity",
        ),
        UniqueConstraint("org_id", "id", name="uq_facebook_candidates_org_id"),
        ForeignKeyConstraint(
            ["org_id", "external_entity_id"],
            ["external_entities.org_id", "external_entities.id"],
            ondelete="CASCADE",
            name="fk_facebook_candidates_org_entity",
        ),
        CheckConstraint(
            "status IN ("
            + ", ".join(f"'{status}'" for status in FACEBOOK_CANDIDATE_STATUSES)
            + ")",
            name="ck_facebook_candidates_status",
        ),
        Index(
            "idx_facebook_candidates_ranking",
            "org_id",
            "status",
            "final_score",
            "updated_at",
        ),
        Index(
            "idx_facebook_candidates_account",
            "org_id",
            "account_id",
            "status",
        ),
        Index(
            "idx_facebook_candidates_ready_lease",
            "org_id",
            "account_id",
            desc("final_score"),
            desc("updated_at"),
            "id",
            postgresql_where=text("status = 'ready_to_connect'"),
        ),
        Index(
            "idx_facebook_candidates_entity_status",
            "org_id",
            "external_entity_id",
            "status",
            "account_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalised from accounts.platform so the hot lease query can filter
    # without a join. See migration 113.
    platform: Mapped[str] = mapped_column(
        String(50), nullable=False, default="facebook"
    )
    external_entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="discovered"
    )
    relationship_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    keyword_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    semantic_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    final_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False, default=list
    )
    matched_keywords: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False, default=list
    )
    negative_keywords: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False, default=list
    )
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_eligible_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    leased_by_execution_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    leased_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    last_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    # When the connection request actually left the device. Distinct from
    # updated_at, which any later write overwrites — this one must survive so
    # "how long has this been pending?" stays answerable.
    requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class FacebookCandidateEvidence(TenantScopedModel, Base):
    __tablename__ = "facebook_candidate_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "candidate_id"],
            ["facebook_candidates.org_id", "facebook_candidates.id"],
            ondelete="CASCADE",
            name="fk_facebook_candidate_evidence_org_candidate",
        ),
        UniqueConstraint(
            "org_id",
            "candidate_id",
            "source_hash",
            name="uq_facebook_candidate_evidence_source",
        ),
        Index(
            "idx_facebook_candidate_evidence_candidate_time",
            "org_id",
            "candidate_id",
            "observed_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    candidate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False, default=dict
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class FacebookCandidateKeyword(TenantScopedModel, Base):
    __tablename__ = "facebook_candidate_keywords"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "candidate_id"],
            ["facebook_candidates.org_id", "facebook_candidates.id"],
            ondelete="CASCADE",
            name="fk_facebook_candidate_keywords_org_candidate",
        ),
        UniqueConstraint(
            "org_id",
            "candidate_id",
            "keyword_type",
            "normalized_keyword",
            name="uq_facebook_candidate_keywords_match",
        ),
        CheckConstraint(
            "keyword_type IN ('positive', 'negative')",
            name="ck_facebook_candidate_keywords_type",
        ),
        Index(
            "idx_facebook_candidate_keywords_lookup",
            "org_id",
            "keyword_type",
            "normalized_keyword",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    candidate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    keyword: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_keyword: Mapped[str] = mapped_column(String(255), nullable=False)
    keyword_type: Mapped[str] = mapped_column(String(16), nullable=False)
    match_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_matched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    last_matched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class FacebookCandidateEmbedding(TenantScopedModel, Base):
    __tablename__ = "facebook_candidate_embeddings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "candidate_id"],
            ["facebook_candidates.org_id", "facebook_candidates.id"],
            ondelete="CASCADE",
            name="fk_facebook_candidate_embeddings_org_candidate",
        ),
        UniqueConstraint(
            "org_id",
            "candidate_id",
            "model",
            "source_hash",
            name="uq_facebook_candidate_embeddings_source",
        ),
        Index(
            "idx_facebook_candidate_embeddings_candidate",
            "org_id",
            "candidate_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    candidate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        _JSON_DOCUMENT, nullable=False, default=list
    )
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class FacebookCandidateSettings(TenantScopedModel, Base):
    __tablename__ = "facebook_candidate_settings"
    __table_args__ = (
        UniqueConstraint("org_id", name="uq_facebook_candidate_settings_org"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    relationship_weight: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.4
    )
    keyword_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.35)
    semantic_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.25)
    review_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.55)
    auto_ready_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    auto_ready_threshold: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.75
    )
    auto_ready_min_evidence: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2
    )
    positive_keywords: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False, default=list
    )
    negative_keywords: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False, default=list
    )
    embedding_model: Mapped[str] = mapped_column(
        String(128), nullable=False, default="multilingual-e5-small"
    )
    embedding_dimensions: Mapped[int] = mapped_column(
        Integer, nullable=False, default=384
    )
    updated_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class FacebookCandidateReview(TenantScopedModel, Base):
    __tablename__ = "facebook_candidate_reviews"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "candidate_id"],
            ["facebook_candidates.org_id", "facebook_candidates.id"],
            ondelete="CASCADE",
            name="fk_facebook_candidate_reviews_org_candidate",
        ),
        Index(
            "idx_facebook_candidate_reviews_candidate_time",
            "org_id",
            "candidate_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    candidate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    from_status: Mapped[str] = mapped_column(String(32), nullable=False)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewer_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    score_snapshot: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


# ── Platform-neutral aliases ──────────────────────────────────────────────────
# The tables keep their historical Facebook names, but nothing about the model
# is Facebook-specific. New code imports these names so a future table rename is
# a migration rather than a repo-wide edit.
SOCIAL_CANDIDATE_STATUSES = FACEBOOK_CANDIDATE_STATUSES
SocialCandidate = FacebookCandidate
SocialCandidateEvidence = FacebookCandidateEvidence
SocialCandidateKeyword = FacebookCandidateKeyword
SocialCandidateEmbedding = FacebookCandidateEmbedding
SocialCandidateSettings = FacebookCandidateSettings
SocialCandidateReview = FacebookCandidateReview
