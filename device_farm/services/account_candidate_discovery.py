"""Platform-neutral candidate discovery orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from services.account_discovery import (
    claim_account_discovery_request,
    mark_account_discovery_completed,
    mark_account_discovery_failed,
)
from services.facebook_candidates import CandidateLeaseAttempt


@dataclass(frozen=True)
class DiscoveryRunResult:
    platform: str
    source_scope: str
    scanned_count: int
    observed_count: int
    ready_count: int


@dataclass(frozen=True)
class DiscoveryLeaseResult:
    attempt: CandidateLeaseAttempt
    discovery: DiscoveryRunResult | None = None
    error: str | None = None


class AccountDiscoveryProvider(Protocol):
    platform: str

    async def lease(
        self,
        db: AsyncSession,
        *,
        org_id: str,
        account_id: str,
        execution_id: str | None,
    ) -> CandidateLeaseAttempt: ...

    async def discover(
        self,
        db: AsyncSession,
        *,
        org_id: str,
        account_id: str,
        limit: int,
    ) -> DiscoveryRunResult: ...


_PROVIDERS: dict[str, AccountDiscoveryProvider] = {}


def register_discovery_provider(provider: AccountDiscoveryProvider) -> None:
    platform = str(provider.platform or "").strip().casefold()
    if not platform:
        raise ValueError("discovery provider platform is required")
    _PROVIDERS[platform] = provider


def get_discovery_provider(platform: str) -> AccountDiscoveryProvider:
    normalized = str(platform or "").strip().casefold()
    if normalized == "facebook" and normalized not in _PROVIDERS:
        from services.facebook_candidate_discovery import facebook_discovery_provider

        register_discovery_provider(facebook_discovery_provider)
    provider = _PROVIDERS.get(normalized)
    if provider is None:
        raise LookupError(f"candidate discovery provider is not registered for {normalized}")
    return provider


async def discover_and_lease_candidate(
    db: AsyncSession,
    *,
    platform: str,
    org_id: str,
    account_id: str,
    execution_id: str | None,
    discovery_limit: int = 500,
) -> DiscoveryLeaseResult:
    """Lease immediately, or discover once and retry the same atomic lease."""
    normalized = str(platform or "").strip().casefold()
    provider = get_discovery_provider(normalized)
    attempt = await provider.lease(
        db,
        org_id=org_id,
        account_id=account_id,
        execution_id=execution_id,
    )
    if attempt.outcome != "no_ready_candidate" or not attempt.discovery_requested:
        return DiscoveryLeaseResult(attempt=attempt)

    state = await claim_account_discovery_request(
        db, org_id=org_id, account_id=account_id, platform=normalized
    )
    if state is None:
        return DiscoveryLeaseResult(attempt=attempt)
    try:
        discovery = await provider.discover(
            db,
            org_id=org_id,
            account_id=account_id,
            limit=discovery_limit,
        )
    except Exception as exc:
        error = str(exc)[:1000] or "candidate discovery failed"
        await mark_account_discovery_failed(
            db,
            org_id=org_id,
            account_id=account_id,
            platform=normalized,
            error=error,
        )
        return DiscoveryLeaseResult(
            attempt=CandidateLeaseAttempt(
                lease=None,
                outcome="discovery_failed",
                discovery_requested=False,
            ),
            error=error,
        )

    await mark_account_discovery_completed(
        db,
        org_id=org_id,
        account_id=account_id,
        platform=normalized,
        candidate_count=discovery.observed_count,
        state=state,
    )
    retry = await provider.lease(
        db,
        org_id=org_id,
        account_id=account_id,
        execution_id=execution_id,
    )
    return DiscoveryLeaseResult(attempt=retry, discovery=discovery)
