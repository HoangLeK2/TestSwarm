from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models.account import Account, DeviceAccount

_BULK_BATCH_SIZE = 500  # rows per INSERT batch


# ── Account CRUD ───────────────────────────────────────────────────────────────


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
    account_metadata: Optional[dict] = None,
) -> Account:
    account = Account(
        platform=platform,
        username=username,
        password_encrypted=password_encrypted,
        display_name=display_name,
        notes=notes,
        tags=tags,
        user_id=user_id,
        account_metadata=account_metadata or {},
    )
    db.add(account)
    await db.flush()
    return account


async def get_account(db: AsyncSession, account_id: str) -> Optional[Account]:
    result = await db.execute(
        select(Account)
        .options(selectinload(Account.device_links))
        .where(Account.id == account_id)
    )
    return result.scalar_one_or_none()


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
    tags: Optional[str] = None,
    user_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Account]:
    stmt = select(Account).order_by(Account.created_at.desc())
    if platform:
        stmt = stmt.where(Account.platform == platform)
    if status:
        stmt = stmt.where(Account.status == status)
    if tags:
        # Substring match on comma-separated tags field.
        stmt = stmt.where(Account.tags.contains(tags))
    if user_id:
        stmt = stmt.where(Account.user_id == user_id)
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
    cooldown_until: Optional[datetime] = None,
    proxy_id: Optional[str] = None,
    notes: Optional[str] = None,
    tags: Optional[str] = None,
    account_metadata: Optional[dict] = None,
    last_used_at: Optional[datetime] = None,
    total_usage_minutes: Optional[float] = None,
    usage_today_minutes: Optional[float] = None,
    usage_reset_date: Optional[date] = None,
) -> Optional[Account]:
    values: dict = {}
    if password_encrypted is not None:
        values["password_encrypted"] = password_encrypted
    if display_name is not None:
        values["display_name"] = display_name
    if status is not None:
        values["status"] = status
    if cooldown_until is not None:
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
    if values:
        await db.execute(
            update(Account).where(Account.id == account_id).values(**values)
        )
    return await get_account(db, account_id)


async def delete_account(db: AsyncSession, account_id: str) -> bool:
    result = await db.execute(delete(Account).where(Account.id == account_id))
    return result.rowcount > 0


def _prepare_account_row(row: dict, user_id: Optional[str]) -> Optional[dict]:
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
        "metadata": {},
        "status": "active",
        "total_usage_minutes": 0.0,
        "usage_today_minutes": 0.0,
    }


async def _insert_batch(db: AsyncSession, batch: List[dict]) -> int:
    """
    Batch INSERT using PostgreSQL ON CONFLICT DO NOTHING.
    Returns the number of rows actually inserted (conflicts are silently skipped).
    """
    stmt = (
        pg_insert(Account)
        .values(batch)
        .on_conflict_do_nothing(index_elements=["platform", "username"])
    )
    result = await db.execute(stmt)
    return result.rowcount


async def bulk_create_accounts(
    db: AsyncSession,
    rows: List[dict],
    *,
    user_id: Optional[str] = None,
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
        prepared = _prepare_account_row(row, user_id)
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


async def get_expired_cooldown_accounts(db: AsyncSession) -> List[Account]:
    """Return cooldown accounts whose cooldown_until timestamp has passed."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Account).where(
            Account.status == "cooldown",
            Account.cooldown_until <= now,
        )
    )
    return list(result.scalars().all())


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
        .where(Account.status == "active")
        .where((Account.cooldown_until.is_(None)) | (Account.cooldown_until < now))
    )
    if user_id is not None:
        stmt = stmt.where(Account.user_id == user_id)
    # NULLS FIRST so never-used accounts come before recently-used ones.
    stmt = stmt.order_by(Account.last_used_at.asc().nullsfirst()).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# ── DeviceAccount CRUD ─────────────────────────────────────────────────────────


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
    return result.rowcount > 0


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
    Return the primary active account for a device filtered by platform.
    Used by campaign_dispatch to inject __ACCOUNT_* variables into scenario tasks.
    """
    result = await db.execute(
        select(Account)
        .join(DeviceAccount, DeviceAccount.account_id == Account.id)
        .where(
            DeviceAccount.device_id == device_id,
            DeviceAccount.is_primary.is_(True),
            Account.platform == platform,
            Account.status == "active",
        )
    )
    return result.scalar_one_or_none()


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
