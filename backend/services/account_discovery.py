"""Account-scoped discovery state without inferring social-account age."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.account import Account
from db.models.account_discovery import AccountDiscoveryState

DEFAULT_DISCOVERY_COOLDOWN = timedelta(minutes=5)
DEFAULT_DISCOVERY_STALE_AFTER = timedelta(minutes=15)


def _normalized_platform(platform: str) -> str:
    value = str(platform or "").strip().casefold()
    if not value or len(value) > 32:
        raise ValueError("platform is required and must be at most 32 characters")
    return value


async def _assert_owned_platform_account(
    db: AsyncSession, *, org_id: str, account_id: str, platform: str
) -> Account:
    account = (
        await db.execute(
            select(Account).where(Account.org_id == org_id, Account.id == account_id)
        )
    ).scalar_one_or_none()
    if account is None or str(account.platform or "").casefold() != platform:
        raise LookupError(f"{platform} account not found in organization")
    return account


async def get_account_discovery_state(
    db: AsyncSession, *, org_id: str, account_id: str, platform: str
) -> AccountDiscoveryState | None:
    platform = _normalized_platform(platform)
    await _assert_owned_platform_account(
        db, org_id=org_id, account_id=account_id, platform=platform
    )
    return (
        await db.execute(
            select(AccountDiscoveryState).where(
                AccountDiscoveryState.org_id == org_id,
                AccountDiscoveryState.account_id == account_id,
                AccountDiscoveryState.platform == platform,
            )
        )
    ).scalar_one_or_none()


async def request_account_discovery(
    db: AsyncSession,
    *,
    org_id: str,
    account_id: str,
    platform: str,
    cooldown: timedelta = DEFAULT_DISCOVERY_COOLDOWN,
) -> tuple[AccountDiscoveryState, bool]:
    """Create an idempotent discovery request; repeated empty polls do not write."""
    platform = _normalized_platform(platform)
    await _assert_owned_platform_account(
        db, org_id=org_id, account_id=account_id, platform=platform
    )
    query = select(AccountDiscoveryState).where(
        AccountDiscoveryState.org_id == org_id,
        AccountDiscoveryState.account_id == account_id,
        AccountDiscoveryState.platform == platform,
    )
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        insert_stmt = postgresql_insert(AccountDiscoveryState)
    elif dialect == "sqlite":
        insert_stmt = sqlite_insert(AccountDiscoveryState)
    else:
        raise RuntimeError(f"account discovery does not support {dialect}")
    await db.execute(
        insert_stmt.values(
            org_id=org_id, account_id=account_id, platform=platform
        ).on_conflict_do_nothing(
            index_elements=["org_id", "account_id", "platform"]
        )
    )
    state = (await db.execute(query.with_for_update())).scalar_one()

    now = datetime.now(UTC)
    if state.status == "discovery_requested":
        return state, False
    if state.status == "discovering":
        if (
            state.discovery_started_at is not None
            and state.discovery_started_at > now - DEFAULT_DISCOVERY_STALE_AFTER
        ):
            return state, False
        state.discovery_started_at = None
    if state.next_discovery_at is not None and state.next_discovery_at > now:
        if state.status != "discovering":
            return state, False
    state.status = "discovery_requested"
    state.discovery_requested_at = now
    state.next_discovery_at = now + cooldown
    state.last_error = None
    state.updated_at = now
    await db.flush()
    return state, True


async def mark_account_discovery_started(
    db: AsyncSession, *, org_id: str, account_id: str, platform: str
) -> AccountDiscoveryState:
    state = await _locked_state(
        db, org_id=org_id, account_id=account_id, platform=platform
    )
    if state.status != "discovery_requested":
        raise ValueError(
            f"account discovery in {state.status} cannot transition to discovering"
        )
    now = datetime.now(UTC)
    state.status = "discovering"
    state.discovery_started_at = now
    state.updated_at = now
    await db.flush()
    return state


async def claim_account_discovery_request(
    db: AsyncSession, *, org_id: str, account_id: str, platform: str
) -> AccountDiscoveryState | None:
    """Atomically claim one requested discovery without a select/update round trip."""
    platform = _normalized_platform(platform)
    now = datetime.now(UTC)
    return (
        await db.execute(
            update(AccountDiscoveryState)
            .where(
                AccountDiscoveryState.org_id == org_id,
                AccountDiscoveryState.account_id == account_id,
                AccountDiscoveryState.platform == platform,
                AccountDiscoveryState.status == "discovery_requested",
            )
            .values(
                status="discovering",
                discovery_started_at=now,
                updated_at=now,
            )
            .returning(AccountDiscoveryState)
        )
    ).scalar_one_or_none()


async def mark_account_discovery_completed(
    db: AsyncSession,
    *,
    org_id: str,
    account_id: str,
    platform: str,
    candidate_count: int,
    state: AccountDiscoveryState | None = None,
) -> AccountDiscoveryState:
    if candidate_count < 0:
        raise ValueError("candidate_count must be non-negative")
    if state is None:
        state = await _locked_state(
            db, org_id=org_id, account_id=account_id, platform=platform
        )
    elif (
        state.org_id != org_id
        or state.account_id != account_id
        or state.platform != _normalized_platform(platform)
    ):
        raise ValueError("account discovery state identity does not match")
    if state.status != "discovering":
        raise ValueError(
            f"account discovery in {state.status} cannot be completed"
        )
    now = datetime.now(UTC)
    state.status = "active" if candidate_count else "ready"
    state.initialized_at = state.initialized_at or now
    state.last_discovery_at = now
    state.discovery_started_at = None
    state.last_error = None
    state.updated_at = now
    await db.flush()
    return state


async def mark_account_discovery_failed(
    db: AsyncSession,
    *,
    org_id: str,
    account_id: str,
    platform: str,
    error: str,
) -> AccountDiscoveryState:
    state = await _locked_state(
        db, org_id=org_id, account_id=account_id, platform=platform
    )
    if state.status != "discovering":
        raise ValueError(f"account discovery in {state.status} cannot fail")
    state.status = "error"
    state.last_error = str(error or "discovery failed")[:1000]
    state.discovery_started_at = None
    state.updated_at = datetime.now(UTC)
    await db.flush()
    return state


async def _locked_state(
    db: AsyncSession, *, org_id: str, account_id: str, platform: str
) -> AccountDiscoveryState:
    platform = _normalized_platform(platform)
    state = (
        await db.execute(
            select(AccountDiscoveryState)
            .where(
                AccountDiscoveryState.org_id == org_id,
                AccountDiscoveryState.account_id == account_id,
                AccountDiscoveryState.platform == platform,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if state is None:
        raise LookupError("account discovery state not found")
    return state
