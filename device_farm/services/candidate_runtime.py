"""Synchronous runtime bridge for account-scoped connection candidates."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from services.account_actions.coordinator import _resolve_tenant
from services.platform_readiness import DEFAULT_PLATFORM
from tenancy.context import tenant_context


def assert_connection_candidate_allowed(
    *,
    identity: dict[str, str | None],
    external_entity_id: str,
    allowed_statuses: Sequence[str] = ("ready_to_connect",),
    lease_token: str | None = None,
) -> dict[str, Any]:
    from db.database import activity_session, run_activity_coro_blocking
    from services.social_candidates import assert_candidate_action_allowed

    async def assert_allowed() -> dict[str, Any]:
        async with activity_session() as db:
            org_id, account_id, _, _ = await _resolve_tenant(
                db, identity, require_ids=False
            )
            with tenant_context(org_id):
                candidate = await assert_candidate_action_allowed(
                    db,
                    org_id=org_id,
                    account_id=account_id,
                    external_entity_id=external_entity_id,
                    allowed_statuses=allowed_statuses,
                    lease_token=lease_token,
                )
                return {
                    "candidate_id": str(candidate.id),
                    "account_id": account_id,
                    "external_entity_id": external_entity_id,
                    "status": candidate.status,
                }

    return run_activity_coro_blocking(assert_allowed())


def lease_connection_candidate(
    *,
    identity: dict[str, str | None],
    execution_id: str | None,
    platform: str = DEFAULT_PLATFORM,
) -> dict[str, Any]:
    from db.database import activity_session, run_activity_coro_blocking
    from services.account_candidate_discovery import discover_and_lease_candidate

    resolved_platform = str(platform or DEFAULT_PLATFORM).strip().casefold()

    async def lease_candidate() -> dict[str, Any]:
        async with activity_session() as db:
            org_id, account_id, _, _ = await _resolve_tenant(
                db, identity, require_ids=False
            )
            with tenant_context(org_id):
                discovery_result = await discover_and_lease_candidate(
                    db,
                    platform=resolved_platform,
                    org_id=org_id,
                    account_id=account_id,
                    execution_id=execution_id,
                )
                attempt = discovery_result.attempt
                discovery = discovery_result.discovery
                discovery_payload = (
                    {
                        "source_scope": discovery.source_scope,
                        "scanned_count": discovery.scanned_count,
                        "observed_count": discovery.observed_count,
                        "ready_count": discovery.ready_count,
                    }
                    if discovery is not None
                    else None
                )
                if attempt.lease is None:
                    return {
                        "available": False,
                        "account_id": account_id,
                        "outcome": attempt.outcome,
                        "discovery_requested": attempt.discovery_requested,
                        "discovery": discovery_payload,
                        "discovery_error": discovery_result.error,
                    }
                lease = attempt.lease
                entity = lease.external_entity
                return {
                    "available": True,
                    "account_id": account_id,
                    "candidate_id": str(lease.candidate.id),
                    "external_entity_id": str(entity.id),
                    "external_id": entity.external_id,
                    "display_name": entity.display_name,
                    "canonical_url": entity.canonical_url,
                    "final_score": lease.candidate.final_score,
                    "lease_token": lease.lease_token,
                    "lease_expires_at": lease.candidate.lease_expires_at,
                    "outcome": "leased",
                    "discovery_requested": False,
                    "discovery": discovery_payload,
                    "discovery_error": discovery_result.error,
                }

    return run_activity_coro_blocking(lease_candidate())


def complete_connection_candidate(
    *,
    identity: dict[str, str | None],
    candidate_id: str,
    lease_token: str,
) -> dict[str, Any]:
    from db.database import activity_session, run_activity_coro_blocking
    from services.social_candidates import complete_candidate_lease

    async def complete_candidate() -> dict[str, Any]:
        async with activity_session() as db:
            org_id, account_id, _, _ = await _resolve_tenant(
                db, identity, require_ids=False
            )
            with tenant_context(org_id):
                candidate = await complete_candidate_lease(
                    db,
                    org_id=org_id,
                    account_id=account_id,
                    candidate_id=candidate_id,
                    lease_token=lease_token,
                )
                return {
                    "candidate_id": str(candidate.id),
                    "account_id": account_id,
                    "status": candidate.status,
                }

    return run_activity_coro_blocking(complete_candidate())


def record_sent_connection_requests(
    *,
    identity: dict[str, str | None],
    targets: Sequence[dict[str, Any]],
    platform: str = DEFAULT_PLATFORM,
    source: str = "visible_people_surface",
) -> list[dict[str, Any]]:
    """Fold on-device connection requests into the candidate pipeline.

    The visible-people scan finds people through Facebook's own suggestions, so
    there is no lease to complete — the candidate row may not exist at all. Each
    target is recorded (creating entity + candidate as needed) so the pipeline
    stops re-offering someone this account has already asked.

    Best-effort per target: one bad row must not discard the rest, since the
    requests have already left the device and the alternative is losing the
    record entirely.
    """
    from db.database import activity_session, run_activity_coro_blocking
    from services.social_candidates import record_connection_request

    resolved_platform = str(platform or DEFAULT_PLATFORM).strip().casefold()
    clean_targets = [
        target
        for target in targets
        if isinstance(target, dict)
        and (
            str(target.get("name") or "").strip()
            or str(target.get("external_id") or "").strip()
        )
    ]
    if not clean_targets:
        return []

    async def record_all() -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        async with activity_session() as db:
            org_id, account_id, _, _ = await _resolve_tenant(
                db, identity, require_ids=False
            )
            with tenant_context(org_id):
                for target in clean_targets:
                    try:
                        records.append(
                            await record_connection_request(
                                db,
                                org_id=org_id,
                                account_id=account_id,
                                platform=resolved_platform,
                                display_name=str(target.get("name") or ""),
                                external_id=target.get("external_id"),
                                source=str(target.get("source") or source),
                            )
                        )
                    except (LookupError, ValueError) as exc:
                        records.append(
                            {
                                "recorded": False,
                                "name": target.get("name"),
                                "error": str(exc),
                            }
                        )
        return records

    return run_activity_coro_blocking(record_all())


def release_connection_candidate(
    *,
    identity: dict[str, str | None],
    external_entity_id: str,
    lease_token: str,
) -> dict[str, Any]:
    from db.database import activity_session, run_activity_coro_blocking
    from services.social_candidates import release_candidate_lease_by_entity

    async def release_candidate() -> dict[str, Any]:
        async with activity_session() as db:
            org_id, account_id, _, _ = await _resolve_tenant(
                db, identity, require_ids=False
            )
            with tenant_context(org_id):
                candidate = await release_candidate_lease_by_entity(
                    db,
                    org_id=org_id,
                    account_id=account_id,
                    external_entity_id=external_entity_id,
                    lease_token=lease_token,
                )
                return {
                    "candidate_id": str(candidate.id),
                    "account_id": account_id,
                    "released": True,
                }

    return run_activity_coro_blocking(release_candidate())


def defer_connection_candidate(
    *,
    identity: dict[str, str | None],
    external_entity_id: str,
    lease_token: str,
    next_eligible_at: datetime,
    note: str | None = None,
) -> dict[str, Any]:
    from db.database import activity_session, run_activity_coro_blocking
    from services.social_candidates import defer_candidate_lease_by_entity

    async def defer_candidate() -> dict[str, Any]:
        async with activity_session() as db:
            org_id, account_id, _, _ = await _resolve_tenant(
                db, identity, require_ids=False
            )
            with tenant_context(org_id):
                candidate = await defer_candidate_lease_by_entity(
                    db,
                    org_id=org_id,
                    account_id=account_id,
                    external_entity_id=external_entity_id,
                    lease_token=lease_token,
                    next_eligible_at=next_eligible_at,
                    note=note,
                )
                return {
                    "candidate_id": str(candidate.id),
                    "account_id": account_id,
                    "external_entity_id": external_entity_id,
                    "status": candidate.status,
                    "next_eligible_at": candidate.next_eligible_at,
                }

    return run_activity_coro_blocking(defer_candidate())
