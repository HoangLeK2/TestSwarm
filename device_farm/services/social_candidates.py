"""Platform-neutral API for the connection-candidate pipeline.

`services/facebook_candidates.py` holds the implementation for historical
reasons; nothing in it is actually Facebook-specific now that every row carries
a `platform` column (migration 113). This module is the name new code should
import, so a later rename of the implementation module and its tables is a
mechanical change rather than a repo-wide edit.

It also owns the operations that only make sense across platforms — recording
that a connection request left the device, which must behave differently for a
two-sided `friend_request` platform and a unilateral `follow` platform.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.external_entity import ExternalEntity
from db.models.facebook_candidate import SocialCandidate
from services.facebook_candidates import (
    assert_candidate_action_allowed,
    complete_candidate_lease,
    defer_candidate_lease_by_entity,
    get_candidate_detail,
    get_candidate_settings,
    lease_next_ready_candidate,
    list_candidates,
    normalize_vietnamese_text,
    observe_candidate,
    recompute_candidates,
    release_candidate_lease,
    release_candidate_lease_by_entity,
    release_candidate_leases_for_execution,
    review_candidate,
    update_candidate_settings,
)
from services.social_ext import connection_kind
from services.social_identity import identity_confidence, profile_identity_key

__all__ = [
    "assert_candidate_action_allowed",
    "complete_candidate_lease",
    "defer_candidate_lease_by_entity",
    "get_candidate_detail",
    "get_candidate_settings",
    "lease_next_ready_candidate",
    "list_candidates",
    "normalize_vietnamese_text",
    "observe_candidate",
    "recompute_candidates",
    "record_connection_request",
    "release_candidate_lease",
    "release_candidate_lease_by_entity",
    "release_candidate_leases_for_execution",
    "review_candidate",
    "requested_status_for",
    "update_candidate_settings",
]


def requested_status_for(platform: str) -> str:
    """Candidate status right after a connection request is verified as sent.

    A follow takes effect immediately, so there is nothing to reconcile later;
    a friend request waits on the other person.
    """
    return (
        "connected" if connection_kind(platform) == "follow" else "request_pending"
    )


async def record_connection_request(
    db: AsyncSession,
    *,
    org_id: str,
    account_id: str,
    platform: str,
    display_name: str,
    external_id: str | None = None,
    source: str = "visible_people_surface",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Record that a connection request was sent to a profile seen on screen.

    The on-device UI scan can send requests without ever consulting the
    candidate pipeline. Left unrecorded, those people stay `ready_to_connect` in
    the database and get leased again later — the same account asks the same
    person twice. This closes that gap by minting the *same* identity key the
    content-author discovery uses, so both paths converge on one row.

    Creates the entity and candidate when they do not exist yet, which is the
    normal case for someone Facebook suggested but our crawl never saw.
    """
    stamp = now or datetime.now(UTC)
    normalized_platform = str(platform or "").strip().casefold()
    normalized_name = normalize_vietnamese_text(display_name or "")
    if not normalized_name and not str(external_id or "").strip():
        raise ValueError("display_name or external_id is required")

    key = profile_identity_key(
        normalized_platform,
        external_id=external_id,
        normalized_name=normalized_name,
    )

    entity = (
        await db.execute(
            select(ExternalEntity).where(
                ExternalEntity.org_id == org_id,
                ExternalEntity.platform == normalized_platform,
                ExternalEntity.entity_type == "profile",
                ExternalEntity.identity_key == key,
            )
        )
    ).scalar_one_or_none()
    if entity is None:
        entity = ExternalEntity(
            id=str(uuid4()),
            org_id=org_id,
            platform=normalized_platform,
            entity_type="profile",
            identity_key=key,
            identity_confidence=identity_confidence(external_id),
            external_id=str(external_id or "").strip() or None,
            display_name=display_name or normalized_name,
            status="candidate",
            current_attributes={
                "normalized_name": normalized_name,
                "discovery_source": source,
            },
            current_metrics={},
            first_seen_at=stamp,
            last_seen_at=stamp,
            created_at=stamp,
            updated_at=stamp,
        )
        db.add(entity)
        await db.flush()
    else:
        entity.last_seen_at = stamp
        entity.updated_at = stamp

    status = requested_status_for(normalized_platform)
    candidate = (
        await db.execute(
            select(SocialCandidate).where(
                SocialCandidate.org_id == org_id,
                SocialCandidate.account_id == account_id,
                SocialCandidate.external_entity_id == entity.id,
            )
        )
    ).scalar_one_or_none()
    created = candidate is None
    if candidate is None:
        candidate = SocialCandidate(
            id=str(uuid4()),
            org_id=org_id,
            account_id=account_id,
            platform=normalized_platform,
            external_entity_id=entity.id,
            status=status,
            reasons=[{"code": "connection_request_sent", "source": source}],
            matched_keywords=[],
            negative_keywords=[],
            first_observed_at=stamp,
            last_observed_at=stamp,
            requested_at=stamp,
            created_at=stamp,
            updated_at=stamp,
        )
        db.add(candidate)
    else:
        candidate.status = status
        candidate.platform = candidate.platform or normalized_platform
        candidate.last_observed_at = stamp
        candidate.requested_at = stamp
        candidate.updated_at = stamp
        # A request is out; the lease has served its purpose either way.
        candidate.lease_token = None
        candidate.leased_by_execution_id = None
        candidate.lease_expires_at = None
    await db.flush()

    return {
        "candidate_id": str(candidate.id),
        "external_entity_id": str(entity.id),
        "identity_key": key,
        "identity_confidence": entity.identity_confidence,
        "status": status,
        "created": created,
    }
