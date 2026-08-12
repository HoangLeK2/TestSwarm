"""API contracts for Facebook candidate ranking and review."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

CandidateStatus = Literal[
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
]
ReviewStatus = Literal["approved", "ready_to_connect", "rejected", "deferred"]


class FacebookCandidateEvidenceIn(BaseModel):
    evidence_type: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=128)
    text: str = Field(default="", max_length=100_000)
    payload: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime | None = None
    source_hash: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")


class FacebookCandidateEmbeddingIn(BaseModel):
    values: list[float] = Field(min_length=1, max_length=4096)
    model: str | None = Field(default=None, max_length=128)
    dimensions: int | None = Field(default=None, ge=1, le=4096)
    source_hash: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


class FacebookCandidateObserveIn(BaseModel):
    account_id: str = Field(min_length=1, max_length=36)
    external_entity_id: str = Field(min_length=1, max_length=36)
    relationship_score: float | None = Field(default=None, ge=0, le=1)
    semantic_score: float | None = Field(default=None, ge=0, le=1)
    evidence: list[FacebookCandidateEvidenceIn] = Field(
        default_factory=list, max_length=100
    )
    embedding: FacebookCandidateEmbeddingIn | None = None


class FacebookCandidateOut(BaseModel):
    id: str
    org_id: str
    account_id: str
    external_entity_id: str
    external_entity_display_name: str
    external_entity_status: str
    status: CandidateStatus
    relationship_score: float
    keyword_score: float
    semantic_score: float
    final_score: float
    reasons: list[dict[str, Any]] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    negative_keywords: list[str] = Field(default_factory=list)
    evidence_count: int
    next_eligible_at: datetime | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    first_observed_at: datetime
    last_observed_at: datetime
    created_at: datetime
    updated_at: datetime


class FacebookCandidateObserveOut(BaseModel):
    candidate: FacebookCandidateOut
    created: bool


class FacebookCandidateListOut(BaseModel):
    items: list[FacebookCandidateOut]
    total: int
    limit: int
    offset: int


class FacebookCandidateEvidenceOut(BaseModel):
    id: str
    evidence_type: str
    source: str
    source_hash: str
    text: str
    payload: dict[str, Any]
    observed_at: datetime
    created_at: datetime


class FacebookCandidateKeywordOut(BaseModel):
    keyword: str
    normalized_keyword: str
    keyword_type: Literal["positive", "negative"]
    match_count: int
    first_matched_at: datetime
    last_matched_at: datetime


class FacebookCandidateEmbeddingOut(BaseModel):
    id: str
    embedding: list[float]
    model: str
    dimensions: int
    source_hash: str
    created_at: datetime


class FacebookCandidateReviewOut(BaseModel):
    id: str
    from_status: CandidateStatus
    to_status: CandidateStatus
    reviewer_id: str | None = None
    note: str | None = None
    score_snapshot: dict[str, Any]
    created_at: datetime


class FacebookCandidateDetailOut(FacebookCandidateOut):
    evidence: list[FacebookCandidateEvidenceOut]
    keyword_matches: list[FacebookCandidateKeywordOut]
    embeddings: list[FacebookCandidateEmbeddingOut]
    reviews: list[FacebookCandidateReviewOut]


class FacebookCandidateReviewIn(BaseModel):
    status: ReviewStatus
    note: str | None = Field(default=None, max_length=4000)
    next_eligible_at: datetime | None = None


class FacebookCandidateRecomputeIn(BaseModel):
    candidate_ids: list[str] | None = Field(default=None, max_length=500)
    account_id: str | None = Field(default=None, max_length=36)
    limit: int = Field(default=500, ge=1, le=500)
    after_id: str | None = Field(default=None, max_length=36)


class FacebookCandidateRecomputeOut(BaseModel):
    items: list[FacebookCandidateOut]
    recomputed_count: int
    next_cursor: str | None = None


class FacebookCandidateSettingsIn(BaseModel):
    relationship_weight: float = Field(default=0.4, ge=0, le=1)
    keyword_weight: float = Field(default=0.35, ge=0, le=1)
    semantic_weight: float = Field(default=0.25, ge=0, le=1)
    review_threshold: float = Field(default=0.55, ge=0, le=1)
    auto_ready_enabled: bool = True
    auto_ready_threshold: float = Field(default=0.75, ge=0, le=1)
    auto_ready_min_evidence: int = Field(default=2, ge=1, le=100)
    positive_keywords: list[str] = Field(default_factory=list, max_length=500)
    negative_keywords: list[str] = Field(default_factory=list, max_length=500)
    embedding_model: str = Field(
        default="multilingual-e5-small", min_length=1, max_length=128
    )
    embedding_dimensions: int = Field(default=384, ge=1, le=4096)


class FacebookCandidateSettingsOut(FacebookCandidateSettingsIn):
    org_id: str
    updated_at: datetime | None = None
