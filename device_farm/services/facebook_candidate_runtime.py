"""Synchronous runtime bridge for account-scoped Facebook candidates."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from services.account_actions.coordinator import _resolve_tenant
from tenancy.context import tenant_context


def assert_connection_candidate_allowed(
    *,
    identity: dict[str, str | None],
    external_entity_id: str,
    allowed_statuses: Sequence[str] = ("ready_to_connect",),
    lease_token: str | None = None,
) -> dict[str, Any]:
    from db.database import activity_session, run_activity_coro_blocking
    from services.facebook_candidates import assert_candidate_action_allowed

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
    *, identity: dict[str, str | None], execution_id: str | None
) -> dict[str, Any]:
    from db.database import activity_session, run_activity_coro_blocking
    from services.account_candidate_discovery import discover_and_lease_candidate

    async def lease_candidate() -> dict[str, Any]:
        async with activity_session() as db:
            org_id, account_id, _, _ = await _resolve_tenant(
                db, identity, require_ids=False
            )
            with tenant_context(org_id):
                discovery_result = await discover_and_lease_candidate(
                    db,
                    platform="facebook",
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
    from services.facebook_candidates import complete_candidate_lease

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


def release_connection_candidate(
    *,
    identity: dict[str, str | None],
    external_entity_id: str,
    lease_token: str,
) -> dict[str, Any]:
    from db.database import activity_session, run_activity_coro_blocking
    from services.facebook_candidates import release_candidate_lease_by_entity

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
    from services.facebook_candidates import defer_candidate_lease_by_entity

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
