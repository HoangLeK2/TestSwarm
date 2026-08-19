"""Candidate scoring and review orchestration for Facebook connection actions."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any
from uuid import uuid4

from sqlalchemy import func, literal_column, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from db.models.account import Account
from db.models.external_entity import ExternalEntity
from db.models.facebook_candidate import (
    FACEBOOK_CANDIDATE_STATUSES,
    FacebookCandidate,
    FacebookCandidateEmbedding,
    FacebookCandidateEvidence,
    FacebookCandidateKeyword,
    FacebookCandidateReview,
    FacebookCandidateSettings,
)

DEFAULT_RELATIONSHIP_WEIGHT = 0.4
DEFAULT_KEYWORD_WEIGHT = 0.35
DEFAULT_SEMANTIC_WEIGHT = 0.25
DEFAULT_REVIEW_THRESHOLD = 0.55
DEFAULT_AUTO_READY_THRESHOLD = 0.75
DEFAULT_AUTO_READY_MIN_EVIDENCE = 2
DEFAULT_EMBEDDING_MODEL = "multilingual-e5-small"
DEFAULT_EMBEDDING_DIMENSIONS = 384
POLARS_BATCH_MIN_CANDIDATES = 8
POLARS_MAX_KEYWORDS = 256
KeywordCounts = dict[str, tuple[str, int]]
CandidateScoreResults = dict[str, tuple[KeywordCounts, KeywordCounts]]

REVIEW_TARGET_STATUSES = frozenset(
    {"approved", "ready_to_connect", "rejected", "deferred"}
)
ACTIVE_ENTITY_STATUSES = frozenset(
    {
        "approved",
        "warming_up",
        "ready_to_connect",
        "request_pending",
        "connected",
    }
)
_REVIEW_TRANSITIONS = {
    "review_required": REVIEW_TARGET_STATUSES,
    "approved": frozenset({"ready_to_connect", "rejected", "deferred"}),
    "deferred": frozenset({"approved", "ready_to_connect", "rejected"}),
    "ready_to_connect": frozenset({"rejected", "deferred"}),
}


@dataclass(frozen=True)
class CandidateSettings:
    org_id: str
    relationship_weight: float = DEFAULT_RELATIONSHIP_WEIGHT
    keyword_weight: float = DEFAULT_KEYWORD_WEIGHT
    semantic_weight: float = DEFAULT_SEMANTIC_WEIGHT
    review_threshold: float = DEFAULT_REVIEW_THRESHOLD
    auto_ready_enabled: bool = True
    auto_ready_threshold: float = DEFAULT_AUTO_READY_THRESHOLD
    auto_ready_min_evidence: int = DEFAULT_AUTO_READY_MIN_EVIDENCE
    positive_keywords: tuple[str, ...] = ()
    negative_keywords: tuple[str, ...] = ()
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS
    updated_at: datetime | None = None


@dataclass(frozen=True)
class CandidateListItem:
    candidate: FacebookCandidate
    external_entity: ExternalEntity


@dataclass(frozen=True)
class CandidateDetail:
    candidate: FacebookCandidate
    external_entity: ExternalEntity
    evidence: tuple[FacebookCandidateEvidence, ...]
    keywords: tuple[FacebookCandidateKeyword, ...]
    embeddings: tuple[FacebookCandidateEmbedding, ...]
    reviews: tuple[FacebookCandidateReview, ...]


@dataclass(frozen=True)
class CandidateLease:
    candidate: FacebookCandidate
    external_entity: ExternalEntity
    lease_token: str


@dataclass(frozen=True)
class CandidateLeaseAttempt:
    lease: CandidateLease | None
    outcome: str
    discovery_requested: bool


def normalize_vietnamese_text(value: str) -> str:
    """Case-fold, remove Vietnamese diacritics, and normalize word separators."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    without_marks = (
        "".join(char for char in decomposed if not unicodedata.combining(char))
        .replace("đ", "d")
        .replace("Đ", "D")
    )
    return re.sub(r"[^a-z0-9]+", " ", without_marks.casefold()).strip()


def _required_org_id(org_id: str) -> str:
    value = str(org_id or "").strip()
    if not value:
        raise ValueError("org_id is required")
    return value


def _bounded_score(value: float | None, field: str) -> float:
    score = float(value or 0.0)
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"{field} must be between 0 and 1")
    return score


def _normalized_keywords(values: Iterable[str]) -> list[tuple[str, str]]:
    by_normalized: dict[str, str] = {}
    for raw in values:
        keyword = str(raw or "").strip()
        if len(keyword) > 255:
            raise ValueError("candidate keywords must be at most 255 characters")
        normalized = normalize_vietnamese_text(keyword)
        if normalized and normalized not in by_normalized:
            by_normalized[normalized] = keyword
    return sorted(by_normalized.items())


def _keyword_counts(
    normalized_texts: Sequence[str], keywords: Iterable[str]
) -> KeywordCounts:
    matches: KeywordCounts = {}
    for normalized, original in _normalized_keywords(keywords):
        needle = f" {normalized} "
        count = sum(f" {text} ".count(needle) for text in normalized_texts)
        if count:
            matches[normalized] = (original, count)
    return matches


@lru_cache(maxsize=1)
def _optional_polars():
    try:
        return importlib.import_module("polars")
    except Exception:
        return None


def _apply_candidate_score_values(
    *,
    candidate: FacebookCandidate,
    settings: CandidateSettings,
    positive: KeywordCounts,
    negative: KeywordCounts,
    evidence_count: int,
    configured_positive_count: int,
) -> None:
    keyword_score = (
        min(1.0, len(positive) / configured_positive_count)
        if configured_positive_count
        else 0.0
    )
    weighted_signals = [
        (candidate.relationship_score, settings.relationship_weight),
    ]
    if configured_positive_count:
        weighted_signals.append((keyword_score, settings.keyword_weight))
    if candidate.semantic_score > 0:
        weighted_signals.append((candidate.semantic_score, settings.semantic_weight))
    weights_total = sum(weight for _, weight in weighted_signals)
    final_score = round(
        sum(score * weight for score, weight in weighted_signals) / weights_total,
        6,
    ) if weights_total else 0.0
    matched_keywords = sorted(original for original, _ in positive.values())
    negative_keywords = sorted(original for original, _ in negative.values())
    candidate.keyword_score = round(keyword_score, 6)
    candidate.final_score = final_score
    candidate.matched_keywords = matched_keywords
    candidate.negative_keywords = negative_keywords
    candidate.evidence_count = evidence_count
    candidate.reasons = [
        {
            "code": "relationship_score",
            "score": round(candidate.relationship_score, 6),
            "weight": settings.relationship_weight,
        },
        {
            "code": "keyword_score",
            "score": candidate.keyword_score,
            "weight": settings.keyword_weight,
            "matches": matched_keywords,
        },
        {
            "code": "semantic_score",
            "score": round(candidate.semantic_score, 6),
            "weight": settings.semantic_weight,
        },
    ]
    if negative_keywords:
        candidate.reasons.append(
            {"code": "negative_keyword_block", "matches": negative_keywords}
        )
        candidate.status = "blocked"
    elif candidate.status in {"discovered", "review_required", "blocked"}:
        candidate.status = (
            "review_required"
            if final_score >= settings.review_threshold
            else "discovered"
        )
    candidate.updated_at = datetime.now(UTC)


def _settings_from_row(
    org_id: str, row: FacebookCandidateSettings | None
) -> CandidateSettings:
    if row is None:
        return CandidateSettings(org_id=org_id)
    return CandidateSettings(
        org_id=org_id,
        relationship_weight=float(row.relationship_weight),
        keyword_weight=float(row.keyword_weight),
        semantic_weight=float(row.semantic_weight),
        review_threshold=float(row.review_threshold),
        auto_ready_enabled=bool(row.auto_ready_enabled),
        auto_ready_threshold=float(row.auto_ready_threshold),
        auto_ready_min_evidence=int(row.auto_ready_min_evidence),
        positive_keywords=tuple(row.positive_keywords or []),
        negative_keywords=tuple(row.negative_keywords or []),
        embedding_model=row.embedding_model,
        embedding_dimensions=row.embedding_dimensions,
        updated_at=row.updated_at,
    )


async def get_candidate_settings(db: AsyncSession, *, org_id: str) -> CandidateSettings:
    org_id = _required_org_id(org_id)
    row = (
        await db.execute(
            select(FacebookCandidateSettings).where(
                FacebookCandidateSettings.org_id == org_id
            )
        )
    ).scalar_one_or_none()
    return _settings_from_row(org_id, row)


async def update_candidate_settings(
    db: AsyncSession,
    *,
    org_id: str,
    relationship_weight: float,
    keyword_weight: float,
    semantic_weight: float,
    review_threshold: float,
    auto_ready_enabled: bool,
    auto_ready_threshold: float,
    auto_ready_min_evidence: int,
    positive_keywords: Sequence[str],
    negative_keywords: Sequence[str],
    embedding_model: str,
    embedding_dimensions: int,
    updated_by: str | None,
) -> CandidateSettings:
    org_id = _required_org_id(org_id)
    weights = (
        _bounded_score(relationship_weight, "relationship_weight"),
        _bounded_score(keyword_weight, "keyword_weight"),
        _bounded_score(semantic_weight, "semantic_weight"),
    )
    if sum(weights) <= 0:
        raise ValueError("at least one scoring weight must be greater than zero")
    review_threshold = _bounded_score(review_threshold, "review_threshold")
    auto_ready_threshold = _bounded_score(
        auto_ready_threshold, "auto_ready_threshold"
    )
    if not 1 <= auto_ready_min_evidence <= 100:
        raise ValueError("auto_ready_min_evidence must be between 1 and 100")
    model = str(embedding_model or "").strip()
    if not model:
        raise ValueError("embedding_model is required")
    if not 1 <= embedding_dimensions <= 4096:
        raise ValueError("embedding_dimensions must be between 1 and 4096")

    row = (
        await db.execute(
            select(FacebookCandidateSettings)
            .where(FacebookCandidateSettings.org_id == org_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        proposed = FacebookCandidateSettings(org_id=org_id)
        try:
            async with db.begin_nested():
                db.add(proposed)
                await db.flush()
            row = proposed
        except IntegrityError:
            row = (
                await db.execute(
                    select(FacebookCandidateSettings)
                    .where(FacebookCandidateSettings.org_id == org_id)
                    .with_for_update()
                )
            ).scalar_one()
    row.relationship_weight, row.keyword_weight, row.semantic_weight = weights
    row.review_threshold = review_threshold
    row.auto_ready_enabled = bool(auto_ready_enabled)
    row.auto_ready_threshold = auto_ready_threshold
    row.auto_ready_min_evidence = auto_ready_min_evidence
    row.positive_keywords = [
        original for _, original in _normalized_keywords(positive_keywords)
    ]
    row.negative_keywords = [
        original for _, original in _normalized_keywords(negative_keywords)
    ]
    row.embedding_model = model
    row.embedding_dimensions = embedding_dimensions
    row.updated_by = updated_by
    row.updated_at = datetime.now(UTC)
    await db.flush()
    return _settings_from_row(org_id, row)


async def _assert_owned_account_and_entity(
    db: AsyncSession, *, org_id: str, account_id: str, external_entity_id: str
) -> tuple[Account, ExternalEntity]:
    account = (
        await db.execute(
            select(Account).where(
                Account.org_id == org_id,
                Account.id == account_id,
                func.lower(Account.platform) == "facebook",
            )
        )
    ).scalar_one_or_none()
    if account is None:
        raise LookupError("Facebook account not found in organization")

    entity = (
        await db.execute(
            select(ExternalEntity).where(
                ExternalEntity.org_id == org_id,
                ExternalEntity.id == external_entity_id,
                func.lower(ExternalEntity.platform) == "facebook",
            )
        )
    ).scalar_one_or_none()
    if entity is None:
        raise LookupError("Facebook external entity not found in organization")
    return account, entity


def _source_hash(evidence: dict[str, Any]) -> str:
    supplied = str(evidence.get("source_hash") or "").strip().lower()
    if supplied:
        if not re.fullmatch(r"[a-f0-9]{64}", supplied):
            raise ValueError("evidence source_hash must be a SHA-256 hex digest")
        return supplied
    canonical = json.dumps(
        {
            "evidence_type": evidence.get("evidence_type"),
            "source": evidence.get("source"),
            "text": evidence.get("text") or "",
            "payload": evidence.get("payload") or {},
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _get_or_create_candidate(
    db: AsyncSession,
    *,
    org_id: str,
    account_id: str,
    external_entity_id: str,
) -> tuple[FacebookCandidate, bool]:
    query = select(FacebookCandidate).where(
        FacebookCandidate.org_id == org_id,
        FacebookCandidate.account_id == account_id,
        FacebookCandidate.external_entity_id == external_entity_id,
    )
    candidate = (await db.execute(query.with_for_update())).scalar_one_or_none()
    if candidate is not None:
        return candidate, False

    candidate = FacebookCandidate(
        org_id=org_id,
        account_id=account_id,
        external_entity_id=external_entity_id,
    )
    try:
        async with db.begin_nested():
            db.add(candidate)
            await db.flush()
        return candidate, True
    except IntegrityError:
        candidate = (await db.execute(query.with_for_update())).scalar_one()
        return candidate, False


async def _upsert_evidence(
    db: AsyncSession,
    *,
    candidate: FacebookCandidate,
    evidence_items: Sequence[dict[str, Any]],
) -> None:
    prepared: dict[str, dict[str, Any]] = {}
    for item in evidence_items:
        evidence_type = str(item.get("evidence_type") or "").strip()
        source = str(item.get("source") or "").strip()
        if not evidence_type or not source:
            raise ValueError("evidence_type and source are required")
        text_value = str(item.get("text") or "")
        source_hash = _source_hash(item)
        prepared.setdefault(
            source_hash,
            {
                "evidence_type": evidence_type,
                "source": source,
                "text": text_value,
                "payload": dict(item.get("payload") or {}),
                "observed_at": item.get("observed_at") or datetime.now(UTC),
            },
        )
    if not prepared:
        return
    now = datetime.now(UTC)
    rows = [
        {
            "id": str(uuid4()),
            "org_id": candidate.org_id,
            "candidate_id": candidate.id,
            "source_hash": source_hash,
            "evidence_type": value["evidence_type"],
            "source": value["source"],
            "text": value["text"],
            "normalized_text": normalize_vietnamese_text(value["text"]),
            "payload": value["payload"],
            "observed_at": value["observed_at"],
            "created_at": now,
        }
        for source_hash, value in prepared.items()
    ]
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        statement = postgresql_insert(FacebookCandidateEvidence).values(rows)
    elif dialect == "sqlite":
        statement = sqlite_insert(FacebookCandidateEvidence).values(rows)
    else:
        db.add_all([FacebookCandidateEvidence(**row) for row in rows])
        return
    await db.execute(
        statement.on_conflict_do_nothing(
            index_elements=["org_id", "candidate_id", "source_hash"]
        )
    )


async def _store_embedding(
    db: AsyncSession,
    *,
    candidate: FacebookCandidate,
    embedding: dict[str, Any] | None,
    settings: CandidateSettings,
) -> None:
    if embedding is None:
        return
    values = [float(value) for value in embedding.get("values") or []]
    dimensions = int(embedding.get("dimensions") or len(values))
    if not values or dimensions != len(values):
        raise ValueError("embedding dimensions must match the number of values")
    model = str(embedding.get("model") or settings.embedding_model).strip()
    source_hash = str(embedding.get("source_hash") or "").strip().lower()
    if not model or not re.fullmatch(r"[a-f0-9]{64}", source_hash):
        raise ValueError("embedding model and SHA-256 source_hash are required")
    exists = (
        await db.execute(
            select(FacebookCandidateEmbedding.id).where(
                FacebookCandidateEmbedding.org_id == candidate.org_id,
                FacebookCandidateEmbedding.candidate_id == candidate.id,
                FacebookCandidateEmbedding.model == model,
                FacebookCandidateEmbedding.source_hash == source_hash,
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        return
    row = FacebookCandidateEmbedding(
        org_id=candidate.org_id,
        candidate_id=candidate.id,
        embedding=values,
        model=model,
        dimensions=dimensions,
        source_hash=source_hash,
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        pass


async def _sync_keyword_rows(
    db: AsyncSession,
    *,
    candidate: FacebookCandidate,
    positive: dict[str, tuple[str, int]],
    negative: dict[str, tuple[str, int]],
    existing_rows: Sequence[FacebookCandidateKeyword] | None = None,
) -> None:
    rows = list(existing_rows or ())
    if existing_rows is None:
        rows = (
            (
                await db.execute(
                    select(FacebookCandidateKeyword).where(
                        FacebookCandidateKeyword.org_id == candidate.org_id,
                        FacebookCandidateKeyword.candidate_id == candidate.id,
                    )
                )
            )
            .scalars()
            .all()
        )
    existing = {(row.keyword_type, row.normalized_keyword): row for row in rows}
    desired = {
        **{("positive", key): value for key, value in positive.items()},
        **{("negative", key): value for key, value in negative.items()},
    }
    now = datetime.now(UTC)
    for key, (keyword, count) in desired.items():
        row = existing.pop(key, None)
        if row is None:
            db.add(
                FacebookCandidateKeyword(
                    org_id=candidate.org_id,
                    candidate_id=candidate.id,
                    keyword=keyword,
                    normalized_keyword=key[1],
                    keyword_type=key[0],
                    match_count=count,
                    first_matched_at=now,
                    last_matched_at=now,
                )
            )
        else:
            row.keyword = keyword
            row.match_count = count
            row.last_matched_at = now
    for stale in existing.values():
        await db.delete(stale)


async def _sync_external_entity_status(
    db: AsyncSession, *, candidate: FacebookCandidate
) -> None:
    entity = (
        await db.execute(
            select(ExternalEntity).where(
                ExternalEntity.org_id == candidate.org_id,
                ExternalEntity.id == candidate.external_entity_id,
            )
        )
    ).scalar_one()
    if candidate.status in ACTIVE_ENTITY_STATUSES:
        entity.status = "approved"
        return
    if candidate.status not in {"rejected", "deferred", "blocked"}:
        return
    active_other = (
        await db.execute(
            select(FacebookCandidate.id)
            .where(
                FacebookCandidate.org_id == candidate.org_id,
                FacebookCandidate.external_entity_id == candidate.external_entity_id,
                FacebookCandidate.account_id != candidate.account_id,
                FacebookCandidate.status.in_(ACTIVE_ENTITY_STATUSES),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if active_other is None:
        entity.status = "candidate"
    else:
        entity.status = "approved"


async def _score_candidate(
    db: AsyncSession,
    *,
    candidate: FacebookCandidate,
    settings: CandidateSettings,
) -> FacebookCandidate:
    evidence = (
        (
            await db.execute(
                select(FacebookCandidateEvidence).where(
                    FacebookCandidateEvidence.org_id == candidate.org_id,
                    FacebookCandidateEvidence.candidate_id == candidate.id,
                )
            )
        )
        .scalars()
        .all()
    )
    positive, negative = _apply_candidate_score(
        candidate=candidate, evidence=evidence, settings=settings
    )
    await _sync_keyword_rows(
        db, candidate=candidate, positive=positive, negative=negative
    )
    await _sync_external_entity_status(db, candidate=candidate)
    await db.flush()
    return candidate


def _apply_candidate_score(
    *,
    candidate: FacebookCandidate,
    evidence: Sequence[FacebookCandidateEvidence],
    settings: CandidateSettings,
) -> tuple[KeywordCounts, KeywordCounts]:
    normalized_texts = [row.normalized_text for row in evidence if row.normalized_text]
    positive = _keyword_counts(normalized_texts, settings.positive_keywords)
    negative = _keyword_counts(normalized_texts, settings.negative_keywords)
    configured_positive_count = len(_normalized_keywords(settings.positive_keywords))
    _apply_candidate_score_values(
        candidate=candidate,
        settings=settings,
        positive=positive,
        negative=negative,
        evidence_count=len(evidence),
        configured_positive_count=configured_positive_count,
    )
    return positive, negative


def _apply_candidate_scores_batch(
    *,
    candidates: Sequence[FacebookCandidate],
    evidence_by_candidate: dict[str, list[FacebookCandidateEvidence]],
    settings: CandidateSettings,
) -> CandidateScoreResults:
    polars_results = _apply_candidate_scores_batch_polars(
        candidates=candidates,
        evidence_by_candidate=evidence_by_candidate,
        settings=settings,
    )
    if polars_results is not None:
        return polars_results

    results: CandidateScoreResults = {}
    for candidate in candidates:
        results[candidate.id] = _apply_candidate_score(
            candidate=candidate,
            evidence=evidence_by_candidate.get(candidate.id, []),
            settings=settings,
        )
    return results


def _apply_candidate_scores_batch_polars(
    *,
    candidates: Sequence[FacebookCandidate],
    evidence_by_candidate: dict[str, list[FacebookCandidateEvidence]],
    settings: CandidateSettings,
) -> CandidateScoreResults | None:
    keyword_specs = [
        ("positive", normalized, original)
        for normalized, original in _normalized_keywords(settings.positive_keywords)
    ] + [
        ("negative", normalized, original)
        for normalized, original in _normalized_keywords(settings.negative_keywords)
    ]
    if (
        len(candidates) < POLARS_BATCH_MIN_CANDIDATES
        or not keyword_specs
        or len(keyword_specs) > POLARS_MAX_KEYWORDS
    ):
        return None
    pl = _optional_polars()
    if pl is None:
        return None

    rows = []
    evidence_counts: dict[str, int] = {}
    for candidate in candidates:
        evidence_rows = evidence_by_candidate.get(candidate.id, [])
        evidence_counts[candidate.id] = len(evidence_rows)
        normalized_text = "  ".join(
            row.normalized_text for row in evidence_rows if row.normalized_text
        )
        rows.append(
            {
                "candidate_id": candidate.id,
                "padded_text": f" {normalized_text} " if normalized_text else "",
            }
        )
    if not rows:
        return None

    expressions = [
        pl.col("padded_text")
        .str.count_matches(f" {normalized} ", literal=True)
        .alias(f"kw_{index}")
        for index, (_, normalized, _) in enumerate(keyword_specs)
    ]
    score_rows = (
        pl.DataFrame(rows)
        .lazy()
        .select("candidate_id", *expressions)
        .collect()
        .iter_rows(named=True)
    )
    counts_by_candidate: dict[str, dict[str, int]] = {
        str(row["candidate_id"]): {
            key: int(value or 0)
            for key, value in row.items()
            if key.startswith("kw_")
        }
        for row in score_rows
    }

    configured_positive_count = len(
        _normalized_keywords(settings.positive_keywords)
    )
    results: CandidateScoreResults = {}
    for candidate in candidates:
        counts = counts_by_candidate.get(candidate.id, {})
        positive: KeywordCounts = {}
        negative: KeywordCounts = {}
        for index, (keyword_type, normalized, original) in enumerate(keyword_specs):
            count = counts.get(f"kw_{index}", 0)
            if count <= 0:
                continue
            target = positive if keyword_type == "positive" else negative
            target[normalized] = (original, count)
        _apply_candidate_score_values(
            candidate=candidate,
            settings=settings,
            positive=positive,
            negative=negative,
            evidence_count=evidence_counts.get(candidate.id, 0),
            configured_positive_count=configured_positive_count,
        )
        results[candidate.id] = (positive, negative)
    return results


def _candidate_meets_keyword_auto_ready(
    candidate: FacebookCandidate,
    settings: CandidateSettings,
) -> bool:
    return (
        settings.auto_ready_enabled
        and bool(_normalized_keywords(settings.positive_keywords))
        and bool(candidate.matched_keywords)
        and not candidate.negative_keywords
        and candidate.status in {"discovered", "review_required", "approved"}
        and candidate.final_score >= settings.auto_ready_threshold
        and candidate.evidence_count >= settings.auto_ready_min_evidence
    )


def _apply_keyword_auto_ready(
    candidate: FacebookCandidate,
    settings: CandidateSettings,
) -> bool:
    if not _candidate_meets_keyword_auto_ready(candidate, settings):
        return False
    candidate.status = "ready_to_connect"
    candidate.reasons = [
        *(candidate.reasons or []),
        {
            "code": "automatic_keyword_readiness",
            "threshold": settings.auto_ready_threshold,
            "minimum_evidence": settings.auto_ready_min_evidence,
            "matches": list(candidate.matched_keywords or []),
        },
    ]
    candidate.updated_at = datetime.now(UTC)
    return True


async def observe_candidate(
    db: AsyncSession,
    *,
    org_id: str,
    account_id: str,
    external_entity_id: str,
    relationship_score: float | None = None,
    semantic_score: float | None = None,
    evidence: Sequence[dict[str, Any]] = (),
    embedding: dict[str, Any] | None = None,
) -> tuple[FacebookCandidate, bool]:
    org_id = _required_org_id(org_id)
    await _assert_owned_account_and_entity(
        db,
        org_id=org_id,
        account_id=account_id,
        external_entity_id=external_entity_id,
    )
    settings = await get_candidate_settings(db, org_id=org_id)
    candidate, created = await _get_or_create_candidate(
        db,
        org_id=org_id,
        account_id=account_id,
        external_entity_id=external_entity_id,
    )
    if relationship_score is not None:
        candidate.relationship_score = _bounded_score(
            relationship_score, "relationship_score"
        )
    if semantic_score is not None:
        candidate.semantic_score = _bounded_score(semantic_score, "semantic_score")
    candidate.last_observed_at = datetime.now(UTC)
    await _upsert_evidence(db, candidate=candidate, evidence_items=evidence)
    await _store_embedding(
        db, candidate=candidate, embedding=embedding, settings=settings
    )
    await db.flush()
    return await _score_candidate(db, candidate=candidate, settings=settings), created


async def list_candidates(
    db: AsyncSession,
    *,
    org_id: str,
    account_id: str | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[CandidateListItem], int]:
    org_id = _required_org_id(org_id)
    conditions = [FacebookCandidate.org_id == org_id]
    if account_id:
        account_exists = (
            await db.execute(
                select(Account.id).where(
                    Account.org_id == org_id,
                    Account.id == account_id,
                    func.lower(Account.platform) == "facebook",
                )
            )
        ).scalar_one_or_none()
        if account_exists is None:
            raise LookupError("Facebook account not found in organization")
        conditions.append(FacebookCandidate.account_id == account_id)
    if status:
        if status not in FACEBOOK_CANDIDATE_STATUSES:
            raise ValueError("invalid candidate status")
        conditions.append(FacebookCandidate.status == status)
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                ExternalEntity.display_name.ilike(pattern),
                ExternalEntity.external_id.ilike(pattern),
            )
        )
    base = (
        select(FacebookCandidate, ExternalEntity)
        .join(
            ExternalEntity,
            (ExternalEntity.org_id == FacebookCandidate.org_id)
            & (ExternalEntity.id == FacebookCandidate.external_entity_id),
        )
        .where(*conditions)
    )
    total = int(
        (
            await db.execute(
                select(func.count()).select_from(base.order_by(None).subquery())
            )
        ).scalar_one()
    )
    rows = (
        await db.execute(
            base.order_by(
                FacebookCandidate.final_score.desc(),
                FacebookCandidate.updated_at.desc(),
                FacebookCandidate.id,
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [
        CandidateListItem(candidate=row[0], external_entity=row[1]) for row in rows
    ], total


async def get_candidate_detail(
    db: AsyncSession, *, org_id: str, candidate_id: str
) -> CandidateDetail | None:
    org_id = _required_org_id(org_id)
    pair = (
        await db.execute(
            select(FacebookCandidate, ExternalEntity)
            .join(
                ExternalEntity,
                (ExternalEntity.org_id == FacebookCandidate.org_id)
                & (ExternalEntity.id == FacebookCandidate.external_entity_id),
            )
            .where(
                FacebookCandidate.org_id == org_id,
                FacebookCandidate.id == candidate_id,
            )
        )
    ).one_or_none()
    if pair is None:
        return None
    evidence = tuple(
        (
            await db.execute(
                select(FacebookCandidateEvidence)
                .where(
                    FacebookCandidateEvidence.org_id == org_id,
                    FacebookCandidateEvidence.candidate_id == candidate_id,
                )
                .order_by(FacebookCandidateEvidence.observed_at.desc())
            )
        ).scalars()
    )
    keywords = tuple(
        (
            await db.execute(
                select(FacebookCandidateKeyword)
                .where(
                    FacebookCandidateKeyword.org_id == org_id,
                    FacebookCandidateKeyword.candidate_id == candidate_id,
                )
                .order_by(
                    FacebookCandidateKeyword.keyword_type,
                    FacebookCandidateKeyword.normalized_keyword,
                )
            )
        ).scalars()
    )
    embeddings = tuple(
        (
            await db.execute(
                select(FacebookCandidateEmbedding)
                .where(
                    FacebookCandidateEmbedding.org_id == org_id,
                    FacebookCandidateEmbedding.candidate_id == candidate_id,
                )
                .order_by(FacebookCandidateEmbedding.created_at.desc())
            )
        ).scalars()
    )
    reviews = tuple(
        (
            await db.execute(
                select(FacebookCandidateReview)
                .where(
                    FacebookCandidateReview.org_id == org_id,
                    FacebookCandidateReview.candidate_id == candidate_id,
                )
                .order_by(FacebookCandidateReview.created_at.desc())
            )
        ).scalars()
    )
    return CandidateDetail(
        candidate=pair[0],
        external_entity=pair[1],
        evidence=evidence,
        keywords=keywords,
        embeddings=embeddings,
        reviews=reviews,
    )


async def review_candidate(
    db: AsyncSession,
    *,
    org_id: str,
    candidate_id: str,
    to_status: str,
    reviewer_id: str,
    note: str | None = None,
    next_eligible_at: datetime | None = None,
) -> FacebookCandidate:
    org_id = _required_org_id(org_id)
    if to_status not in REVIEW_TARGET_STATUSES:
        raise ValueError("invalid review status")
    candidate = (
        await db.execute(
            select(FacebookCandidate)
            .where(
                FacebookCandidate.org_id == org_id,
                FacebookCandidate.id == candidate_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if candidate is None:
        raise LookupError("candidate not found")
    allowed_transitions = _REVIEW_TRANSITIONS.get(candidate.status, frozenset())
    if to_status not in allowed_transitions:
        raise ValueError(f"candidate in {candidate.status} cannot be reviewed")
    if to_status == "deferred" and next_eligible_at is None:
        raise ValueError("next_eligible_at is required when deferring a candidate")

    previous = candidate.status
    now = datetime.now(UTC)
    candidate.status = to_status
    candidate.reviewed_by = reviewer_id
    candidate.reviewed_at = now
    candidate.review_note = note
    candidate.next_eligible_at = next_eligible_at if to_status == "deferred" else None
    candidate.updated_at = now
    db.add(
        FacebookCandidateReview(
            org_id=org_id,
            candidate_id=candidate.id,
            from_status=previous,
            to_status=to_status,
            reviewer_id=reviewer_id,
            note=note,
            score_snapshot={
                "relationship_score": candidate.relationship_score,
                "keyword_score": candidate.keyword_score,
                "semantic_score": candidate.semantic_score,
                "final_score": candidate.final_score,
                "reasons": candidate.reasons,
            },
        )
    )
    await _sync_external_entity_status(db, candidate=candidate)
    await db.flush()
    return candidate


async def recompute_candidates(
    db: AsyncSession,
    *,
    org_id: str,
    candidate_ids: Sequence[str] | None = None,
    account_id: str | None = None,
    limit: int = 500,
    after_id: str | None = None,
) -> list[CandidateListItem]:
    org_id = _required_org_id(org_id)
    settings = await get_candidate_settings(db, org_id=org_id)
    conditions = [FacebookCandidate.org_id == org_id]
    if candidate_ids is not None:
        unique_ids = list(dict.fromkeys(candidate_ids))
        if not unique_ids:
            return []
        conditions.append(FacebookCandidate.id.in_(unique_ids))
    if account_id:
        account = (
            await db.execute(
                select(Account.id).where(
                    Account.org_id == org_id,
                    Account.id == account_id,
                    func.lower(Account.platform) == "facebook",
                )
            )
        ).scalar_one_or_none()
        if account is None:
            raise LookupError("Facebook account not found in organization")
        conditions.append(FacebookCandidate.account_id == account_id)
    if not 1 <= limit <= 500:
        raise ValueError("recompute limit must be between 1 and 500")
    if after_id:
        conditions.append(FacebookCandidate.id > after_id)
    candidates = list(
        (
            await db.execute(
                select(FacebookCandidate)
                .where(*conditions)
                .order_by(FacebookCandidate.id)
                .limit(limit)
                .with_for_update()
            )
        ).scalars()
    )
    if not candidates:
        return []

    candidate_ids_batch = [candidate.id for candidate in candidates]
    evidence_by_candidate: dict[str, list[FacebookCandidateEvidence]] = {
        candidate_id: [] for candidate_id in candidate_ids_batch
    }
    evidence_rows = (
        (
            await db.execute(
                select(FacebookCandidateEvidence).where(
                    FacebookCandidateEvidence.org_id == org_id,
                    FacebookCandidateEvidence.candidate_id.in_(candidate_ids_batch),
                )
            )
        )
        .scalars()
        .all()
    )
    for row in evidence_rows:
        evidence_by_candidate[row.candidate_id].append(row)

    keywords_by_candidate: dict[str, list[FacebookCandidateKeyword]] = {
        candidate_id: [] for candidate_id in candidate_ids_batch
    }
    keyword_rows = (
        (
            await db.execute(
                select(FacebookCandidateKeyword).where(
                    FacebookCandidateKeyword.org_id == org_id,
                    FacebookCandidateKeyword.candidate_id.in_(candidate_ids_batch),
                )
            )
        )
        .scalars()
        .all()
    )
    for row in keyword_rows:
        keywords_by_candidate[row.candidate_id].append(row)

    score_results = _apply_candidate_scores_batch(
        candidates=candidates,
        evidence_by_candidate=evidence_by_candidate,
        settings=settings,
    )
    for candidate in candidates:
        positive, negative = score_results[candidate.id]
        await _sync_keyword_rows(
            db,
            candidate=candidate,
            positive=positive,
            negative=negative,
            existing_rows=keywords_by_candidate[candidate.id],
        )
        _apply_keyword_auto_ready(candidate, settings)
    await db.flush()

    entity_ids = list(
        dict.fromkeys(candidate.external_entity_id for candidate in candidates)
    )
    entities = list(
        (
            await db.execute(
                select(ExternalEntity).where(
                    ExternalEntity.org_id == org_id,
                    ExternalEntity.id.in_(entity_ids),
                )
            )
        ).scalars()
    )
    entity_by_id = {entity.id: entity for entity in entities}
    active_entity_ids = set(
        (
            await db.execute(
                select(FacebookCandidate.external_entity_id)
                .where(
                    FacebookCandidate.org_id == org_id,
                    FacebookCandidate.external_entity_id.in_(entity_ids),
                    FacebookCandidate.status.in_(ACTIVE_ENTITY_STATUSES),
                )
                .distinct()
            )
        ).scalars()
    )
    for candidate in candidates:
        entity = entity_by_id[candidate.external_entity_id]
        if candidate.status in ACTIVE_ENTITY_STATUSES:
            entity.status = "approved"
        elif candidate.status in {"rejected", "deferred", "blocked"}:
            entity.status = (
                "approved"
                if candidate.external_entity_id in active_entity_ids
                else "candidate"
            )
    await db.flush()
    return [
        CandidateListItem(
            candidate=candidate,
            external_entity=entity_by_id[candidate.external_entity_id],
        )
        for candidate in candidates
    ]


async def assert_candidate_action_allowed(
    db: AsyncSession,
    org_id: str,
    account_id: str,
    external_entity_id: str,
    allowed_statuses: Sequence[str] = ("ready_to_connect",),
    lease_token: str | None = None,
) -> FacebookCandidate:
    """Return the exact account candidate when an action is allowed.

    Missing or cross-tenant ownership raises ``LookupError``. A known candidate
    in a disallowed state raises ``ValueError`` so runtime coordinators can
    distinguish stale lifecycle state from a missing contract row.
    """
    org_id = _required_org_id(org_id)
    statuses = tuple(dict.fromkeys(str(status) for status in allowed_statuses))
    if not statuses or any(
        status not in FACEBOOK_CANDIDATE_STATUSES for status in statuses
    ):
        raise ValueError("allowed_statuses must contain valid candidate statuses")
    candidate = (
        await db.execute(
            select(FacebookCandidate).where(
                FacebookCandidate.org_id == org_id,
                FacebookCandidate.account_id == account_id,
                FacebookCandidate.external_entity_id == external_entity_id,
            )
        )
    ).scalar_one_or_none()
    if candidate is None:
        raise LookupError(
            "candidate, account, or external entity not found in organization"
        )
    if candidate.status not in statuses:
        raise ValueError(
            f"candidate status {candidate.status} is not allowed; "
            f"expected one of {statuses}"
        )
    if lease_token is not None:
        now = datetime.now(UTC)
        if (
            not candidate.lease_token
            or candidate.lease_token != lease_token
            or candidate.lease_expires_at is None
            or candidate.lease_expires_at <= now
        ):
            raise ValueError("candidate lease is missing, expired, or owned by another run")
    return candidate


async def lease_next_ready_candidate(
    db: AsyncSession,
    *,
    org_id: str,
    account_id: str,
    execution_id: str | None,
    lease_ttl: timedelta = timedelta(minutes=10),
) -> CandidateLeaseAttempt:
    """Atomically reserve the highest-ranked ready candidate for one account."""
    org_id = _required_org_id(org_id)
    now = datetime.now(UTC)
    pair = (
        await db.execute(
            _ready_candidate_lease_query(
                org_id=org_id, account_id=account_id, now=now
            )
        )
    ).one_or_none()
    if pair is None:
        from services.account_discovery import request_account_discovery

        ready_candidate_exists = (
            await db.execute(
                select(FacebookCandidate.id)
                .where(
                    FacebookCandidate.org_id == org_id,
                    FacebookCandidate.account_id == account_id,
                    FacebookCandidate.status
                    == literal_column("'ready_to_connect'"),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if ready_candidate_exists is not None:
            return CandidateLeaseAttempt(
                lease=None,
                outcome="candidate_busy",
                discovery_requested=False,
            )
        state, _ = await request_account_discovery(
            db,
            org_id=org_id,
            account_id=account_id,
            platform="facebook",
        )
        return CandidateLeaseAttempt(
            lease=None,
            outcome="no_ready_candidate",
            discovery_requested=state.status
            in {"discovery_requested", "discovering"},
        )

    candidate, entity = pair
    token = uuid4().hex
    candidate.lease_token = token
    candidate.leased_by_execution_id = str(execution_id or "")[:64] or None
    candidate.leased_at = now
    candidate.lease_expires_at = now + lease_ttl
    candidate.updated_at = now
    await db.flush()
    return CandidateLeaseAttempt(
        lease=CandidateLease(
            candidate=candidate, external_entity=entity, lease_token=token
        ),
        outcome="leased",
        discovery_requested=False,
    )


def sibling_target_cooldown_days() -> int:
    """How long one org's accounts avoid re-approaching the same person.

    0 disables the guard. Env: SIBLING_TARGET_COOLDOWN_DAYS.
    """
    raw = os.environ.get("SIBLING_TARGET_COOLDOWN_DAYS", "30").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 30


def _sibling_targeted_recently(
    *, org_id: str, account_id: str, now: datetime
):
    """EXISTS: another account in this org already approached this person.

    Accounts in one organisation discover candidates from a shared content pool
    and rank them identically, so without this every account converges on the
    same top profiles. That person then receives near-simultaneous requests from
    several unrelated new accounts — the most conspicuous pattern the farm can
    produce — and the requests after the first are wasted anyway.

    Uses idx_facebook_candidates_entity_status (org_id, external_entity_id,
    status, account_id).
    """
    sibling = aliased(FacebookCandidate)
    cutoff = now - timedelta(days=sibling_target_cooldown_days())
    return (
        select(sibling.id)
        .where(
            sibling.org_id == org_id,
            sibling.external_entity_id == FacebookCandidate.external_entity_id,
            sibling.account_id != account_id,
            sibling.status.in_(("request_pending", "connected")),
            # requested_at is NULL for rows written before migration 113; fall
            # back to updated_at so historical sends still shield the target.
            func.coalesce(sibling.requested_at, sibling.updated_at) >= cutoff,
        )
        .exists()
    )


def _ready_candidate_lease_query(
    *, org_id: str, account_id: str, now: datetime
):
    conditions = [
        FacebookCandidate.org_id == org_id,
        FacebookCandidate.account_id == account_id,
        FacebookCandidate.status == literal_column("'ready_to_connect'"),
        or_(
            FacebookCandidate.lease_token.is_(None),
            FacebookCandidate.lease_expires_at.is_(None),
            FacebookCandidate.lease_expires_at <= now,
        ),
        or_(
            FacebookCandidate.next_eligible_at.is_(None),
            FacebookCandidate.next_eligible_at <= now,
        ),
    ]
    if sibling_target_cooldown_days() > 0:
        conditions.append(
            ~_sibling_targeted_recently(
                org_id=org_id, account_id=account_id, now=now
            )
        )
    return (
        select(FacebookCandidate, ExternalEntity)
        .join(
            ExternalEntity,
            (ExternalEntity.org_id == FacebookCandidate.org_id)
            & (ExternalEntity.id == FacebookCandidate.external_entity_id),
        )
        .where(*conditions)
        .order_by(
            FacebookCandidate.final_score.desc(),
            FacebookCandidate.updated_at.desc(),
            FacebookCandidate.id,
        )
        .limit(1)
        .with_for_update(skip_locked=True, of=FacebookCandidate)
    )


async def release_candidate_lease(
    db: AsyncSession,
    *,
    org_id: str,
    account_id: str,
    candidate_id: str,
    lease_token: str,
) -> FacebookCandidate:
    candidate = await _locked_candidate_lease(
        db,
        org_id=org_id,
        account_id=account_id,
        candidate_id=candidate_id,
        lease_token=lease_token,
    )
    _clear_candidate_lease(candidate)
    candidate.updated_at = datetime.now(UTC)
    await db.flush()
    return candidate


async def release_candidate_lease_by_entity(
    db: AsyncSession,
    *,
    org_id: str,
    account_id: str,
    external_entity_id: str,
    lease_token: str,
) -> FacebookCandidate:
    candidate = (
        await db.execute(
            select(FacebookCandidate)
            .where(
                FacebookCandidate.org_id == _required_org_id(org_id),
                FacebookCandidate.account_id == account_id,
                FacebookCandidate.external_entity_id == external_entity_id,
                FacebookCandidate.lease_token == lease_token,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if candidate is None:
        raise LookupError("active candidate lease not found")
    _clear_candidate_lease(candidate)
    candidate.updated_at = datetime.now(UTC)
    await db.flush()
    return candidate


async def defer_candidate_lease_by_entity(
    db: AsyncSession,
    *,
    org_id: str,
    account_id: str,
    external_entity_id: str,
    lease_token: str,
    next_eligible_at: datetime,
    note: str | None = None,
) -> FacebookCandidate:
    candidate = (
        await db.execute(
            select(FacebookCandidate)
            .where(
                FacebookCandidate.org_id == _required_org_id(org_id),
                FacebookCandidate.account_id == account_id,
                FacebookCandidate.external_entity_id == external_entity_id,
                FacebookCandidate.lease_token == lease_token,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if candidate is None:
        raise LookupError("active candidate lease not found")
    if candidate.status != "ready_to_connect":
        raise ValueError(f"candidate status {candidate.status} cannot be deferred")

    previous = candidate.status
    now = datetime.now(UTC)
    candidate.status = "deferred"
    candidate.next_eligible_at = next_eligible_at
    candidate.reviewed_by = None
    candidate.reviewed_at = now
    candidate.review_note = note
    _clear_candidate_lease(candidate)
    candidate.updated_at = now
    db.add(
        FacebookCandidateReview(
            org_id=org_id,
            candidate_id=candidate.id,
            from_status=previous,
            to_status="deferred",
            reviewer_id=None,
            note=note,
            score_snapshot={
                "relationship_score": candidate.relationship_score,
                "keyword_score": candidate.keyword_score,
                "semantic_score": candidate.semantic_score,
                "final_score": candidate.final_score,
                "reasons": candidate.reasons,
            },
        )
    )
    await _sync_external_entity_status(db, candidate=candidate)
    await db.flush()
    return candidate


async def release_candidate_leases_for_execution(
    db: AsyncSession,
    *,
    org_id: str,
    execution_id: str,
) -> int:
    """Release every unfinished candidate lease owned by a terminal execution."""
    if not execution_id:
        return 0
    result = await db.execute(
        update(FacebookCandidate)
        .where(
            FacebookCandidate.org_id == _required_org_id(org_id),
            FacebookCandidate.leased_by_execution_id == execution_id,
            FacebookCandidate.lease_token.is_not(None),
        )
        .values(
            lease_token=None,
            leased_by_execution_id=None,
            leased_at=None,
            lease_expires_at=None,
            updated_at=datetime.now(UTC),
        )
        .execution_options(synchronize_session=False)
    )
    await db.flush()
    rowcount = getattr(result, "rowcount", 0)
    return rowcount if isinstance(rowcount, int) else 0


async def complete_candidate_lease(
    db: AsyncSession,
    *,
    org_id: str,
    account_id: str,
    candidate_id: str,
    lease_token: str,
) -> FacebookCandidate:
    candidate = await _locked_candidate_lease(
        db,
        org_id=org_id,
        account_id=account_id,
        candidate_id=candidate_id,
        lease_token=lease_token,
    )
    if candidate.status != "ready_to_connect":
        raise ValueError(f"candidate status {candidate.status} cannot be completed")
    candidate.status = "request_pending"
    _clear_candidate_lease(candidate)
    candidate.updated_at = datetime.now(UTC)
    await _sync_external_entity_status(db, candidate=candidate)
    await db.flush()
    return candidate


async def _locked_candidate_lease(
    db: AsyncSession,
    *,
    org_id: str,
    account_id: str,
    candidate_id: str,
    lease_token: str,
) -> FacebookCandidate:
    candidate = (
        await db.execute(
            select(FacebookCandidate)
            .where(
                FacebookCandidate.org_id == _required_org_id(org_id),
                FacebookCandidate.account_id == account_id,
                FacebookCandidate.id == candidate_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if (
        candidate is None
        or not lease_token
        or candidate.lease_token != lease_token
        or candidate.lease_expires_at is None
        or candidate.lease_expires_at <= now
    ):
        raise LookupError("active candidate lease not found")
    return candidate


def _clear_candidate_lease(candidate: FacebookCandidate) -> None:
    candidate.lease_token = None
    candidate.leased_by_execution_id = None
    candidate.leased_at = None
    candidate.lease_expires_at = None
