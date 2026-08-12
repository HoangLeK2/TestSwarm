"""Org-scoped Facebook candidate API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import DB, CurrentUser, require_permission
from api.schemas.facebook_candidate import (
    FacebookCandidateDetailOut,
    FacebookCandidateEmbeddingOut,
    FacebookCandidateEvidenceOut,
    FacebookCandidateKeywordOut,
    FacebookCandidateListOut,
    FacebookCandidateObserveIn,
    FacebookCandidateObserveOut,
    FacebookCandidateOut,
    FacebookCandidateRecomputeIn,
    FacebookCandidateRecomputeOut,
    FacebookCandidateReviewIn,
    FacebookCandidateReviewOut,
    FacebookCandidateSettingsIn,
    FacebookCandidateSettingsOut,
)
from db.models.external_entity import ExternalEntity
from db.models.facebook_candidate import FacebookCandidate
from services.facebook_candidates import (
    CandidateDetail,
    CandidateSettings,
    get_candidate_detail,
    get_candidate_settings,
    list_candidates,
    observe_candidate,
    recompute_candidates,
    review_candidate,
    update_candidate_settings,
)

router = APIRouter(tags=["facebook-candidates"])


def _org_id(user: CurrentUser) -> str:
    org_id = str(getattr(user, "org_id", None) or "").strip()
    if not org_id:
        raise HTTPException(status_code=404, detail={"code": "NO_ORGANIZATION"})
    return org_id


def _candidate_out(
    candidate: FacebookCandidate, entity: ExternalEntity
) -> FacebookCandidateOut:
    return FacebookCandidateOut(
        id=candidate.id,
        org_id=candidate.org_id,
        account_id=candidate.account_id,
        external_entity_id=candidate.external_entity_id,
        external_entity_display_name=entity.display_name,
        external_entity_status=entity.status,
        status=candidate.status,
        relationship_score=candidate.relationship_score,
        keyword_score=candidate.keyword_score,
        semantic_score=candidate.semantic_score,
        final_score=candidate.final_score,
        reasons=candidate.reasons or [],
        matched_keywords=candidate.matched_keywords or [],
        negative_keywords=candidate.negative_keywords or [],
        evidence_count=candidate.evidence_count,
        next_eligible_at=candidate.next_eligible_at,
        reviewed_by=candidate.reviewed_by,
        reviewed_at=candidate.reviewed_at,
        review_note=candidate.review_note,
        first_observed_at=candidate.first_observed_at,
        last_observed_at=candidate.last_observed_at,
        created_at=candidate.created_at,
        updated_at=candidate.updated_at,
    )


def _detail_out(detail: CandidateDetail) -> FacebookCandidateDetailOut:
    base = _candidate_out(detail.candidate, detail.external_entity).model_dump()
    return FacebookCandidateDetailOut(
        **base,
        evidence=[
            FacebookCandidateEvidenceOut(
                id=row.id,
                evidence_type=row.evidence_type,
                source=row.source,
                source_hash=row.source_hash,
                text=row.text,
                payload=row.payload or {},
                observed_at=row.observed_at,
                created_at=row.created_at,
            )
            for row in detail.evidence
        ],
        keyword_matches=[
            FacebookCandidateKeywordOut(
                keyword=row.keyword,
                normalized_keyword=row.normalized_keyword,
                keyword_type=row.keyword_type,
                match_count=row.match_count,
                first_matched_at=row.first_matched_at,
                last_matched_at=row.last_matched_at,
            )
            for row in detail.keywords
        ],
        embeddings=[
            FacebookCandidateEmbeddingOut(
                id=row.id,
                embedding=row.embedding or [],
                model=row.model,
                dimensions=row.dimensions,
                source_hash=row.source_hash,
                created_at=row.created_at,
            )
            for row in detail.embeddings
        ],
        reviews=[
            FacebookCandidateReviewOut(
                id=row.id,
                from_status=row.from_status,
                to_status=row.to_status,
                reviewer_id=row.reviewer_id,
                note=row.note,
                score_snapshot=row.score_snapshot or {},
                created_at=row.created_at,
            )
            for row in detail.reviews
        ],
    )


def _settings_out(settings: CandidateSettings) -> FacebookCandidateSettingsOut:
    return FacebookCandidateSettingsOut(
        org_id=settings.org_id,
        relationship_weight=settings.relationship_weight,
        keyword_weight=settings.keyword_weight,
        semantic_weight=settings.semantic_weight,
        review_threshold=settings.review_threshold,
        auto_ready_enabled=settings.auto_ready_enabled,
        auto_ready_threshold=settings.auto_ready_threshold,
        auto_ready_min_evidence=settings.auto_ready_min_evidence,
        positive_keywords=list(settings.positive_keywords),
        negative_keywords=list(settings.negative_keywords),
        embedding_model=settings.embedding_model,
        embedding_dimensions=settings.embedding_dimensions,
        updated_at=settings.updated_at,
    )


def _service_error(exc: ValueError | LookupError) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(
            status_code=404,
            detail={"code": "FACEBOOK_CANDIDATE_NOT_FOUND", "message": str(exc)},
        )
    return HTTPException(
        status_code=400,
        detail={"code": "INVALID_FACEBOOK_CANDIDATE", "message": str(exc)},
    )


@router.get(
    "/facebook-candidates",
    response_model=FacebookCandidateListOut,
    dependencies=[Depends(require_permission("accounts", "read"))],
)
async def list_facebook_candidates_route(
    db: DB,
    user: CurrentUser,
    account_id: str | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> FacebookCandidateListOut:
    try:
        rows, total = await list_candidates(
            db,
            org_id=_org_id(user),
            account_id=account_id,
            status=status,
            search=search,
            limit=limit,
            offset=offset,
        )
    except (ValueError, LookupError) as exc:
        raise _service_error(exc) from exc
    return FacebookCandidateListOut(
        items=[_candidate_out(row.candidate, row.external_entity) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/facebook-candidates",
    response_model=FacebookCandidateObserveOut,
    dependencies=[Depends(require_permission("content", "create"))],
)
async def observe_facebook_candidate_route(
    body: FacebookCandidateObserveIn, db: DB, user: CurrentUser
) -> FacebookCandidateObserveOut:
    try:
        candidate, created = await observe_candidate(
            db,
            org_id=_org_id(user),
            account_id=body.account_id,
            external_entity_id=body.external_entity_id,
            relationship_score=body.relationship_score,
            semantic_score=body.semantic_score,
            evidence=[item.model_dump() for item in body.evidence],
            embedding=body.embedding.model_dump() if body.embedding else None,
        )
        detail = await get_candidate_detail(
            db, org_id=_org_id(user), candidate_id=candidate.id
        )
    except (ValueError, LookupError) as exc:
        raise _service_error(exc) from exc
    assert detail is not None
    return FacebookCandidateObserveOut(
        candidate=_candidate_out(candidate, detail.external_entity), created=created
    )


@router.post(
    "/facebook-candidates/recompute",
    response_model=FacebookCandidateRecomputeOut,
    dependencies=[Depends(require_permission("accounts", "update"))],
)
async def recompute_facebook_candidates_route(
    body: FacebookCandidateRecomputeIn, db: DB, user: CurrentUser
) -> FacebookCandidateRecomputeOut:
    org_id = _org_id(user)
    try:
        items = await recompute_candidates(
            db,
            org_id=org_id,
            candidate_ids=body.candidate_ids,
            account_id=body.account_id,
            limit=body.limit,
            after_id=body.after_id,
        )
    except (ValueError, LookupError) as exc:
        raise _service_error(exc) from exc
    response_items = [
        _candidate_out(item.candidate, item.external_entity) for item in items
    ]
    return FacebookCandidateRecomputeOut(
        items=response_items,
        recomputed_count=len(response_items),
        next_cursor=(
            items[-1].candidate.id if len(items) == body.limit else None
        ),
    )


@router.get(
    "/facebook-candidates/{candidate_id}",
    response_model=FacebookCandidateDetailOut,
    dependencies=[Depends(require_permission("accounts", "read"))],
)
async def get_facebook_candidate_route(
    candidate_id: str, db: DB, user: CurrentUser
) -> FacebookCandidateDetailOut:
    detail = await get_candidate_detail(
        db, org_id=_org_id(user), candidate_id=candidate_id
    )
    if detail is None:
        raise HTTPException(
            status_code=404, detail={"code": "FACEBOOK_CANDIDATE_NOT_FOUND"}
        )
    return _detail_out(detail)


@router.patch(
    "/facebook-candidates/{candidate_id}/review",
    response_model=FacebookCandidateDetailOut,
    dependencies=[Depends(require_permission("accounts", "update"))],
)
async def review_facebook_candidate_route(
    candidate_id: str,
    body: FacebookCandidateReviewIn,
    db: DB,
    user: CurrentUser,
) -> FacebookCandidateDetailOut:
    org_id = _org_id(user)
    try:
        await review_candidate(
            db,
            org_id=org_id,
            candidate_id=candidate_id,
            to_status=body.status,
            reviewer_id=user.id,
            note=body.note,
            next_eligible_at=body.next_eligible_at,
        )
    except (ValueError, LookupError) as exc:
        raise _service_error(exc) from exc
    detail = await get_candidate_detail(db, org_id=org_id, candidate_id=candidate_id)
    assert detail is not None
    return _detail_out(detail)


@router.get(
    "/facebook-candidate-settings",
    response_model=FacebookCandidateSettingsOut,
    dependencies=[Depends(require_permission("accounts", "read"))],
)
async def get_facebook_candidate_settings_route(
    db: DB, user: CurrentUser
) -> FacebookCandidateSettingsOut:
    return _settings_out(await get_candidate_settings(db, org_id=_org_id(user)))


@router.put(
    "/facebook-candidate-settings",
    response_model=FacebookCandidateSettingsOut,
    dependencies=[Depends(require_permission("accounts", "update"))],
)
async def update_facebook_candidate_settings_route(
    body: FacebookCandidateSettingsIn, db: DB, user: CurrentUser
) -> FacebookCandidateSettingsOut:
    try:
        settings = await update_candidate_settings(
            db,
            org_id=_org_id(user),
            updated_by=user.id,
            **body.model_dump(),
        )
    except ValueError as exc:
        raise _service_error(exc) from exc
    return _settings_out(settings)
