"""Fast Facebook candidate discovery from already persisted crawl data."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.account import Account
from db.models.content import ContentItem
from db.models.external_entity import ExternalEntity
from db.models.facebook_candidate import (
    FacebookCandidate,
    FacebookCandidateEvidence,
    FacebookCandidateKeyword,
)
from services.account_candidate_discovery import DiscoveryRunResult
from services.facebook_candidates import (
    CandidateLeaseAttempt,
    get_candidate_settings,
    normalize_vietnamese_text,
    _apply_candidate_scores_batch,
    _apply_keyword_auto_ready,
    _sync_keyword_rows,
)


@dataclass(frozen=True)
class _SourceRow:
    content_hash: str
    author: str
    author_id: str | None
    body: str
    title: str
    url: str | None
    extracted_at: datetime


def _dialect_insert(db: AsyncSession, model):
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        return postgresql_insert(model)
    if dialect == "sqlite":
        return sqlite_insert(model)
    raise RuntimeError(f"candidate discovery does not support {dialect}")


def _identity_key(author_id: str | None, normalized_author: str) -> str:
    source = f"id:{author_id}" if author_id else f"name:{normalized_author}"
    return f"fb-profile:{hashlib.sha256(source.encode('utf-8')).hexdigest()}"


def _source_query(*, org_id: str, account_id: str | None, limit: int):
    conditions = [
        ContentItem.org_id == org_id,
        ContentItem.deleted_at.is_(None),
        ContentItem.author.is_not(None),
        ContentItem.platform == "facebook",
    ]
    if account_id is not None:
        conditions.append(ContentItem.account_id == account_id)
    return (
        select(
            ContentItem.content_hash,
            ContentItem.author,
            ContentItem.author_id,
            ContentItem.body,
            ContentItem.title,
            ContentItem.url,
            ContentItem.extracted_at,
        )
        .where(*conditions)
        .order_by(ContentItem.extracted_at.desc())
        .limit(limit)
    )


class FacebookContentAuthorDiscoveryProvider:
    platform = "facebook"

    async def lease(
        self,
        db: AsyncSession,
        *,
        org_id: str,
        account_id: str,
        execution_id: str | None,
    ) -> CandidateLeaseAttempt:
        from services.facebook_candidates import lease_next_ready_candidate

        return await lease_next_ready_candidate(
            db,
            org_id=org_id,
            account_id=account_id,
            execution_id=execution_id,
        )

    async def discover(
        self,
        db: AsyncSession,
        *,
        org_id: str,
        account_id: str,
        limit: int,
    ) -> DiscoveryRunResult:
        if not 1 <= limit <= 2000:
            raise ValueError("discovery limit must be between 1 and 2000")
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

        rows = (await db.execute(
            _source_query(org_id=org_id, account_id=account_id, limit=limit)
        )).all()
        source_scope = "account"
        if not rows:
            rows = (await db.execute(
                _source_query(org_id=org_id, account_id=None, limit=limit)
            )).all()
            source_scope = "organization"

        own_names = {
            normalized
            for normalized in (
                normalize_vietnamese_text(account.username),
                normalize_vietnamese_text(account.display_name),
            )
            if normalized
        }
        grouped: dict[str, list[_SourceRow]] = defaultdict(list)
        identity_meta: dict[str, tuple[str, str | None, str]] = {}
        for row in rows:
            author = str(row.author or "").strip()
            normalized_author = normalize_vietnamese_text(author)
            if not normalized_author or normalized_author in own_names:
                continue
            key = _identity_key(row.author_id, normalized_author)
            grouped[key].append(
                _SourceRow(
                    content_hash=str(row.content_hash),
                    author=author,
                    author_id=str(row.author_id).strip() if row.author_id else None,
                    body=str(row.body or ""),
                    title=str(row.title or ""),
                    url=row.url,
                    extracted_at=row.extracted_at,
                )
            )
            identity_meta.setdefault(key, (author, row.author_id, normalized_author))

        ranked_keys = sorted(
            grouped,
            key=lambda key: (-len(grouped[key]), key),
        )[: min(100, limit)]
        if not ranked_keys:
            return DiscoveryRunResult(
                platform=self.platform,
                source_scope=source_scope,
                scanned_count=len(rows),
                observed_count=0,
                ready_count=0,
            )

        now = datetime.now(UTC)
        entity_values = []
        for key in ranked_keys:
            display_name, external_id, normalized_name = identity_meta[key]
            entity_values.append(
                {
                    "id": str(uuid4()),
                    "org_id": org_id,
                    "platform": self.platform,
                    "entity_type": "profile",
                    "identity_key": key,
                    "identity_confidence": "external_id" if external_id else "name_only",
                    "external_id": external_id,
                    "canonical_url": None,
                    "display_name": display_name,
                    "status": "candidate",
                    "current_attributes": {
                        "normalized_name": normalized_name,
                        "discovery_source": "content_author",
                    },
                    "current_metrics": {"evidence_count": len(grouped[key])},
                    "first_seen_at": now,
                    "last_seen_at": now,
                    "created_at": now,
                    "updated_at": now,
                }
            )
        entity_insert = _dialect_insert(db, ExternalEntity).values(entity_values)
        await db.execute(
            entity_insert.on_conflict_do_nothing(
                index_elements=["org_id", "platform", "entity_type", "identity_key"]
            )
        )
        entities = list(
            (
                await db.execute(
                    select(ExternalEntity).where(
                        ExternalEntity.org_id == org_id,
                        ExternalEntity.platform == self.platform,
                        ExternalEntity.entity_type == "profile",
                        ExternalEntity.identity_key.in_(ranked_keys),
                    )
                )
            ).scalars()
        )
        entity_by_key = {entity.identity_key: entity for entity in entities}
        entity_by_id = {entity.id: entity for entity in entities}

        candidate_values = [
            {
                "id": str(uuid4()),
                "org_id": org_id,
                "account_id": account_id,
                "external_entity_id": entity_by_key[key].id,
                "status": "discovered",
                "relationship_score": 0.0,
                "keyword_score": 0.0,
                "semantic_score": 0.0,
                "final_score": 0.0,
                "reasons": [],
                "matched_keywords": [],
                "negative_keywords": [],
                "evidence_count": 0,
                "first_observed_at": now,
                "last_observed_at": now,
                "created_at": now,
                "updated_at": now,
            }
            for key in ranked_keys
        ]
        candidate_insert = _dialect_insert(db, FacebookCandidate).values(
            candidate_values
        )
        await db.execute(
            candidate_insert.on_conflict_do_nothing(
                index_elements=["org_id", "account_id", "external_entity_id"]
            )
        )
        entity_ids = [entity_by_key[key].id for key in ranked_keys]
        candidates = list(
            (
                await db.execute(
                    select(FacebookCandidate).where(
                        FacebookCandidate.org_id == org_id,
                        FacebookCandidate.account_id == account_id,
                        FacebookCandidate.external_entity_id.in_(entity_ids),
                    )
                )
            ).scalars()
        )
        candidate_by_entity = {
            candidate.external_entity_id: candidate for candidate in candidates
        }

        evidence_values = []
        for key in ranked_keys:
            candidate = candidate_by_entity[entity_by_key[key].id]
            evidence_count = len(grouped[key])
            base = 0.60 if source_scope == "account" else 0.45
            candidate.relationship_score = min(1.0, base + 0.15 * (evidence_count - 1))
            candidate.last_observed_at = now
            for row in grouped[key]:
                evidence_values.append(
                    {
                        "id": str(uuid4()),
                        "org_id": org_id,
                        "candidate_id": candidate.id,
                        "evidence_type": "content_author",
                        "source": "content_author_discovery",
                        "source_hash": hashlib.sha256(
                            f"{row.content_hash}:{key}".encode("utf-8")
                        ).hexdigest(),
                        "text": " ".join(
                            part for part in (row.title, row.body) if part
                        )[:100_000],
                        "normalized_text": normalize_vietnamese_text(
                            " ".join(part for part in (row.title, row.body) if part)
                        ),
                        "payload": {
                            "content_hash": row.content_hash,
                            "source_scope": source_scope,
                            "source_url": row.url,
                        },
                        "observed_at": row.extracted_at,
                        "created_at": now,
                    }
                )
        evidence_insert = _dialect_insert(db, FacebookCandidateEvidence).values(
            evidence_values
        )
        await db.execute(
            evidence_insert.on_conflict_do_nothing(
                index_elements=["org_id", "candidate_id", "source_hash"]
            )
        )
        await db.flush()

        candidate_ids = [candidate.id for candidate in candidates]
        settings = await get_candidate_settings(db, org_id=org_id)
        evidence_rows = list(
            (
                await db.execute(
                    select(FacebookCandidateEvidence).where(
                        FacebookCandidateEvidence.org_id == org_id,
                        FacebookCandidateEvidence.candidate_id.in_(candidate_ids),
                    )
                )
            ).scalars()
        )
        evidence_by_candidate: dict[str, list[FacebookCandidateEvidence]] = defaultdict(list)
        for evidence_row in evidence_rows:
            evidence_by_candidate[evidence_row.candidate_id].append(evidence_row)
        keyword_rows = list(
            (
                await db.execute(
                    select(FacebookCandidateKeyword).where(
                        FacebookCandidateKeyword.org_id == org_id,
                        FacebookCandidateKeyword.candidate_id.in_(candidate_ids),
                    )
                )
            ).scalars()
        )
        keywords_by_candidate: dict[str, list[FacebookCandidateKeyword]] = defaultdict(list)
        for keyword_row in keyword_rows:
            keywords_by_candidate[keyword_row.candidate_id].append(keyword_row)

        score_results = _apply_candidate_scores_batch(
            candidates=candidates,
            evidence_by_candidate=evidence_by_candidate,
            settings=settings,
        )
        ready_count = 0
        for candidate in candidates:
            positive, negative = score_results[candidate.id]
            await _sync_keyword_rows(
                db,
                candidate=candidate,
                positive=positive,
                negative=negative,
                existing_rows=keywords_by_candidate[candidate.id],
            )
            if _apply_keyword_auto_ready(candidate, settings):
                entity_by_id[candidate.external_entity_id].status = "approved"
                ready_count += 1
        await db.flush()
        return DiscoveryRunResult(
            platform=self.platform,
            source_scope=source_scope,
            scanned_count=len(rows),
            observed_count=len(candidates),
            ready_count=ready_count,
        )


facebook_discovery_provider = FacebookContentAuthorDiscoveryProvider()
