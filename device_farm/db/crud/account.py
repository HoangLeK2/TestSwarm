from __future__ import annotations

import inspect
import logging
from datetime import date, datetime, timezone
from typing import Any, List, Optional, Tuple

from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models.account import Account, DeviceAccount
from db.models.enums import DISPATCHABLE_STATES, AccountState

logger = logging.getLogger(__name__)

_BULK_BATCH_SIZE = 500  # rows per INSERT batch

_ACCOUNT_METADATA_ALIASES = {
    "email": "email",
    "login_email": "email",
    "account_email": "email",
    "totp_secret": "totp_secret",
    "two_factor_secret": "totp_secret",
    "authenticator_secret": "totp_secret",
    "otp_secret": "totp_secret",
    "2fa_secret": "totp_secret",
    "cookies": "cookies",
    "cookie": "cookies",
    "token": "token",
}


# ── Account CRUD ───────────────────────────────────────────────────────────────


def _clean_metadata_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    return value


def _metadata_from_import_row(row: dict) -> dict:
    metadata: dict[str, Any] = {}
    for source_key in ("metadata", "account_metadata"):
        raw = row.get(source_key)
        if isinstance(raw, dict):
            metadata.update(
                {
                    str(key): _clean_metadata_value(value)
                    for key, value in raw.items()
                    if _clean_metadata_value(value) not in (None, "")
                }
            )

    for source_key, target_key in _ACCOUNT_METADATA_ALIASES.items():
        value = _clean_metadata_value(row.get(source_key))
        if value in (None, ""):
            continue
        if target_key == "totp_secret" and isinstance(value, str):
            value = value.replace(" ", "")
        metadata[target_key] = value

    return metadata


async def create_account(
    db: AsyncSession,
    *,
    platform: str,
    username: str,
    password_encrypted: Optional[str] = None,
    display_name: str = "",
    notes: str = "",
    tags: str = "",
    user_id: Optional[str] = None,
    org_id: Optional[str] = None,
    account_metadata: Optional[dict] = None,
) -> Account:
    now = datetime.now(timezone.utc)
    account = Account(
        platform=platform,
        username=username,
        password_encrypted=password_encrypted,
        display_name=display_name,
        notes=notes,
        tags=tags,
        user_id=user_id,
        org_id=org_id,
        account_metadata=account_metadata or {},
        status=AccountState.UNASSIGNED.value,
        state=AccountState.UNASSIGNED.value,
        state_changed_at=now,
    )
    db.add(account)
    await db.flush()
    return account


async def lookup_account_org_id(db: AsyncSession, account_id: str) -> str | None:
    """Resolve account org without tenant context (Temporal/background paths)."""
    table = Account.__table__
    result = await db.execute(
        select(table.c.org_id).where(table.c.id == account_id).limit(1)
    )
    return result.scalar_one_or_none()


async def get_account(db: AsyncSession, account_id: str) -> Optional[Account]:
    result = await db.execute(
        select(Account)
        .options(selectinload(Account.device_links))
        .where(Account.id == account_id)
    )
    return result.scalar_one_or_none()


async def get_accounts_by_ids(
    db: AsyncSession,
    account_ids: list[str],
    *,
    org_id: str | None = None,
) -> dict[str, Account]:
    """Batch-load accounts by id; optional org scope filter for dispatch/bind validation."""
    if not account_ids:
        return {}
    unique = list(dict.fromkeys(account_ids))
    stmt = select(Account).where(Account.id.in_(unique))
    if org_id is not None:
        stmt = stmt.where(Account.org_id == org_id)
    result = await db.execute(stmt)
    return {row.id: row for row in result.scalars().all()}


async def get_account_by_platform_username(
    db: AsyncSession, platform: str, username: str
) -> Optional[Account]:
    result = await db.execute(
        select(Account).where(
            Account.platform == platform,
            Account.username == username,
        )
    )
    return result.scalar_one_or_none()


async def list_accounts(
    db: AsyncSession,
    *,
    platform: Optional[str] = None,
    status: Optional[str] = None,
    state: Optional[str] = None,
    include_states: Optional[List[str]] = None,
    tags: Optional[str] = None,
    search: Optional[str] = None,
    user_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Account]:
    stmt = select(Account).order_by(Account.created_at.desc())
    if platform:
        stmt = stmt.where(Account.platform == platform)
    if include_states:
        stmt = stmt.where(Account.state.in_(include_states))
    elif state:
        stmt = stmt.where(Account.state == state)
    elif status:
        stmt = stmt.where(Account.state == status)
    if tags:
        # Substring match on comma-separated tags field.
        stmt = stmt.where(Account.tags.contains(tags))
    if user_id:
        stmt = stmt.where(Account.user_id == user_id)
    if search and search.strip():
        # A picker can only show a handful of rows, so the match has to happen
        # here — filtering one page client-side would hide every account that
        # did not make it into that page.
        needle = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Account.username.ilike(needle),
                Account.display_name.ilike(needle),
            )
        )
    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_account(
    db: AsyncSession,
    account_id: str,
    *,
    password_encrypted: Optional[str] = None,
    display_name: Optional[str] = None,
    status: Optional[str] = None,
    state: Optional[str] = None,
    state_reason: Optional[str] = None,
    state_changed_at: Optional[datetime] = None,
    cooldown_until: Optional[datetime] = None,
    clear_cooldown_until: bool = False,
    proxy_id: Optional[str] = None,
    notes: Optional[str] = None,
    tags: Optional[str] = None,
    account_metadata: Optional[dict] = None,
    last_used_at: Optional[datetime] = None,
    total_usage_minutes: Optional[float] = None,
    usage_today_minutes: Optional[float] = None,
    usage_reset_date: Optional[date] = None,
    reload: bool = True,
) -> Optional[Account]:
    values: dict = {}
    if password_encrypted is not None:
        values["password_encrypted"] = password_encrypted
    if display_name is not None:
        values["display_name"] = display_name
    if status is not None:
        values["status"] = status
        values.setdefault("state", status)
    if state is not None:
        values["state"] = state
        values["status"] = state
    if state_reason is not None:
        values["state_reason"] = state_reason
    if state_changed_at is not None:
        values["state_changed_at"] = state_changed_at
    if clear_cooldown_until:
        values["cooldown_until"] = None
    elif cooldown_until is not None:
        values["cooldown_until"] = cooldown_until
    if proxy_id is not None:
        values["proxy_id"] = proxy_id
    if notes is not None:
        values["notes"] = notes
    if tags is not None:
        values["tags"] = tags
    if account_metadata is not None:
        values["account_metadata"] = account_metadata
    if last_used_at is not None:
        values["last_used_at"] = last_used_at
    if total_usage_minutes is not None:
        values["total_usage_minutes"] = total_usage_minutes
    if usage_today_minutes is not None:
        values["usage_today_minutes"] = usage_today_minutes
    if usage_reset_date is not None:
        values["usage_reset_date"] = usage_reset_date
    if not values:
        return await get_account(db, account_id) if reload else None
    if reload:
        await db.execute(
            update(Account).where(Account.id == account_id).values(**values)
        )
        return await get_account(db, account_id)
    result = await db.execute(
        update(Account)
        .where(Account.id == account_id)
        .values(**values)
        .returning(Account)
    )
    return result.scalar_one_or_none()


async def delete_account(db: AsyncSession, account_id: str) -> bool:
    result = await db.execute(delete(Account).where(Account.id == account_id))
    return result.rowcount > 0


def _prepare_account_row(
    row: dict,
    user_id: Optional[str],
    org_id: Optional[str] = None,
) -> Optional[dict]:
    """
    Validate and normalise a raw import row dict.
    Returns a DB-ready dict, or None if the row is malformed (platform/username missing).
    Password encryption is the caller's responsibility (to allow batch pre-processing).
    """
    platform = (row.get("platform") or "").strip().lower()
    username = (row.get("username") or "").strip()
    if not platform or not username:
        return None
    return {
        "platform": platform,
        "username": username,
        "password_encrypted": row.get("password_encrypted"),  # already encrypted
        "display_name": (row.get("display_name") or "").strip(),
        "notes": (row.get("notes") or "").strip(),
        "tags": (row.get("tags") or "").strip(),
        "user_id": user_id,
        "org_id": org_id,
        "metadata": _metadata_from_import_row(row),
        "status": AccountState.UNASSIGNED.value,
        "state": AccountState.UNASSIGNED.value,
        "total_usage_minutes": 0.0,
        "usage_today_minutes": 0.0,
    }


async def _insert_batch(db: AsyncSession, batch: List[dict]) -> int:
    """
    Batch INSERT using PostgreSQL ON CONFLICT DO NOTHING.
    Returns the number of rows actually inserted (conflicts are silently skipped).
    """
    stmt = (
        pg_insert(Account.__table__)
        .values(batch)
        .on_conflict_do_nothing(index_elements=["org_id", "platform", "username"])
    )
    result = await db.execute(stmt)
    return result.rowcount


async def bulk_create_accounts(
    db: AsyncSession,
    rows: List[dict],
    *,
    user_id: Optional[str] = None,
    org_id: Optional[str] = None,
) -> Tuple[int, int]:
    """
    Batch bulk import with upsert-skip semantics.

    Uses ``INSERT … ON CONFLICT (platform, username) DO NOTHING`` in batches of
    _BULK_BATCH_SIZE rows so there is only one DB round-trip per batch instead of
    two per row (SELECT + INSERT).

    Passwords in ``row["password"]`` / ``row["password_plain"]`` are encrypted
    before storage. ``row["password_encrypted"]`` is written as-is (pre-encrypted).

    Returns (created_count, skipped_count).
    """
    from common.crypto import encrypt_password

    batch: List[dict] = []
    invalid = 0
    created = 0

    for row in rows:
        prepared = _prepare_account_row(row, user_id, org_id=org_id)
        if prepared is None:
            invalid += 1
            continue

        # Encrypt password only when a plaintext value is provided.
        if prepared["password_encrypted"] is None:
            plain_pw = (row.get("password") or row.get("password_plain") or "").strip()
            prepared["password_encrypted"] = encrypt_password(plain_pw) if plain_pw else None

        batch.append(prepared)

        if len(batch) >= _BULK_BATCH_SIZE:
            created += await _insert_batch(db, batch)
            batch.clear()

    if batch:
        created += await _insert_batch(db, batch)

    total_valid = len(rows) - invalid
    skipped = total_valid - created
    return created, skipped + invalid


async def get_available_account(
    db: AsyncSession,
    platform: str,
    user_id: Optional[str] = None,
) -> Optional[Account]:
    """Phase 2 — pick least-recently-used active account for `platform` not in cooldown.

    Used for rotation when crawling to distribute load across accounts and avoid
    hammering a single identity (anti-detection).

    Returns None if no eligible account.
    """
    now = datetime.now(timezone.utc)
    stmt = (
        select(Account)
        .where(Account.platform == platform)
        .where(Account.state.in_(DISPATCHABLE_STATES))
        .where((Account.cooldown_until.is_(None)) | (Account.cooldown_until < now))
    )
    if user_id is not None:
        stmt = stmt.where(Account.user_id == user_id)
    # NULLS FIRST so never-used accounts come before recently-used ones.
    stmt = stmt.order_by(Account.last_used_at.asc().nullsfirst()).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# ── DeviceAccount CRUD ─────────────────────────────────────────────────────────


async def sync_account_link_state(db: AsyncSession, account_id: str) -> None:
    """Keep ``unassigned``/``assigned`` in step with the device links.

    ``unassigned`` means "no DeviceAccount row", ``assigned`` means "linked but
    not logged in". Linking stops at ``assigned`` on purpose: only a verified
    platform session may promote to ``active``
    (``services.device_platform_session.mark_active``). Both directions run here
    — the single chokepoint every link/unlink path routes through — so the state
    can never drift from the link table. Terminal and operator-set states
    (``banned``, ``retired``, ``suspended``) are left alone: linking a device to
    a banned account must not silently reactivate it.
    """
    from db.models.enums import AccountState
    from services.account_state.exceptions import AccountStateError
    from services.account_state.service import AccountStateService

    account = await get_account(db, account_id)
    if account is None:
        return

    current = (getattr(account, "state", None) or account.status or "").lower()
    linked = (
        await db.execute(
            select(DeviceAccount.account_id)
            .where(DeviceAccount.account_id == account_id)
            .limit(1)
        )
    ).first() is not None

    if linked and current == AccountState.UNASSIGNED.value:
        target, reason = AccountState.ASSIGNED, "device linked"
    elif not linked and current in {
        AccountState.ASSIGNED.value,
        AccountState.ACTIVE.value,
    }:
        # The session died with the link — no device, no session.
        target, reason = AccountState.UNASSIGNED, "no device linked"
    else:
        return

    try:
        await AccountStateService().transition(
            db, account_id, to=target, reason=reason, actor="system"
        )
    except AccountStateError as exc:
        logger.warning(
            "account %s link-state sync to %s failed: %s", account_id, target.value, exc
        )


async def _clear_primary_for_device(db: AsyncSession, device_id: str) -> None:
    """Strip is_primary from all current primary links for a device."""
    await db.execute(
        update(DeviceAccount)
        .where(
            DeviceAccount.device_id == device_id,
            DeviceAccount.is_primary.is_(True),
        )
        .values(is_primary=False)
    )


async def assign_account_to_device(
    db: AsyncSession,
    device_id: str,
    account_id: str,
    *,
    is_primary: bool = False,
) -> DeviceAccount:
    """
    Link an account to a device. If the link already exists, update is_primary if needed.
    Setting is_primary=True will demote any existing primary link for the device first.
    """
    result = await db.execute(
        select(DeviceAccount).where(
            DeviceAccount.device_id == device_id,
            DeviceAccount.account_id == account_id,
        )
    )
    link = result.scalar_one_or_none()
    if link:
        if is_primary and not link.is_primary:
            await _clear_primary_for_device(db, device_id)
            link.is_primary = True
            await db.flush()
        return link

    if is_primary:
        await _clear_primary_for_device(db, device_id)

    link = DeviceAccount(
        device_id=device_id,
        account_id=account_id,
        is_primary=is_primary,
    )
    db.add(link)
    await db.flush()
    await sync_account_link_state(db, account_id)
    return link


async def set_primary_account(
    db: AsyncSession,
    device_id: str,
    account_id: str,
) -> Optional[DeviceAccount]:
    """Promote an existing device-account link to primary. Returns None if link not found."""
    await _clear_primary_for_device(db, device_id)
    result = await db.execute(
        select(DeviceAccount).where(
            DeviceAccount.device_id == device_id,
            DeviceAccount.account_id == account_id,
        )
    )
    link = result.scalar_one_or_none()
    if not link:
        return None
    link.is_primary = True
    await db.flush()
    return link


async def unassign_account_from_device(
    db: AsyncSession, device_id: str, account_id: str
) -> bool:
    result = await db.execute(
        delete(DeviceAccount).where(
            DeviceAccount.device_id == device_id,
            DeviceAccount.account_id == account_id,
        )
    )
    if result.rowcount > 0:
        await sync_account_link_state(db, account_id)
        return True
    return False


async def list_device_accounts(
    db: AsyncSession,
    device_id: str,
) -> List[DeviceAccount]:
    """Return all account links for a device, primary first."""
    result = await db.execute(
        select(DeviceAccount)
        .options(selectinload(DeviceAccount.account))
        .where(DeviceAccount.device_id == device_id)
        .order_by(DeviceAccount.is_primary.desc(), DeviceAccount.assigned_at)
    )
    return list(result.scalars().all())


async def list_account_devices(
    db: AsyncSession,
    account_id: str,
) -> List[DeviceAccount]:
    """Return all device links for an account."""
    result = await db.execute(
        select(DeviceAccount)
        .where(DeviceAccount.account_id == account_id)
        .order_by(DeviceAccount.assigned_at)
    )
    return list(result.scalars().all())


async def get_primary_account_for_device(
    db: AsyncSession,
    device_id: str,
    platform: str,
) -> Optional[Account]:
    """
    Return the primary dispatchable account for a device filtered by platform.
    Used by campaign_dispatch to inject __ACCOUNT_* variables into scenario tasks.

    ``assigned`` counts as dispatchable — the login scenario needs these
    variables before a session (and therefore ``active``) can exist at all.
    """
    result = await db.execute(
        select(Account)
        .join(DeviceAccount, DeviceAccount.account_id == Account.id)
        .where(
            DeviceAccount.device_id == device_id,
            DeviceAccount.is_primary.is_(True),
            Account.platform == platform,
            Account.state.in_(DISPATCHABLE_STATES),
        )
    )
    return result.scalar_one_or_none()


async def get_primary_accounts_for_devices(
    db: AsyncSession,
    device_ids: list[str],
    platform: str,
) -> dict[str, Account]:
    """Return primary dispatchable accounts keyed by device id in one round-trip."""
    if not device_ids:
        return {}
    result = await db.execute(
        select(DeviceAccount.device_id, Account)
        .join(Account, DeviceAccount.account_id == Account.id)
        .where(
            DeviceAccount.device_id.in_(device_ids),
            DeviceAccount.is_primary.is_(True),
            Account.platform == platform,
            Account.state.in_(DISPATCHABLE_STATES),
        )
    )
    out: dict[str, Account] = {}
    rows = result.all()
    if inspect.isawaitable(rows):
        rows = await rows
    for device_id, account in rows:
        out[str(device_id)] = account
    return out


async def list_active_account_ids(
    db: AsyncSession, account_ids: List[str]
) -> List[str]:
    """Return subset of account_ids that are dispatchable (round-robin pool)."""
    if not account_ids:
        return []
    result = await db.execute(
        select(Account.id).where(
            Account.id.in_(account_ids),
            Account.state.in_(DISPATCHABLE_STATES),
        )
    )
    return [str(r[0]) for r in result.all()]


async def round_robin_assign(
    db: AsyncSession,
    account_ids: List[str],
    device_ids: List[str],
) -> int:
    """
    Assign accounts to devices in round-robin order.

    Device[0] → Account[0], Device[1] → Account[1], …, Device[N] → Account[N % len(accounts)].
    Existing links are skipped (idempotent). Returns count of newly created links.
    """
    if not account_ids or not device_ids:
        return 0

    # Pre-fetch existing links to avoid N+1 per-device queries.
    existing_result = await db.execute(
        select(DeviceAccount.device_id, DeviceAccount.account_id).where(
            DeviceAccount.device_id.in_(device_ids),
            DeviceAccount.account_id.in_(account_ids),
        )
    )
    existing_pairs = {(r.device_id, r.account_id) for r in existing_result}

    created = 0
    new_links: list[DeviceAccount] = []
    for i, device_id in enumerate(device_ids):
        account_id = account_ids[i % len(account_ids)]
        if (device_id, account_id) in existing_pairs:
            continue
        new_links.append(
            DeviceAccount(
                device_id=device_id,
                account_id=account_id,
                is_primary=True,
            )
        )
        created += 1

    if new_links:
        db.add_all(new_links)
        await db.flush()
    return created
