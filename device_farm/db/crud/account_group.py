"""CRUD + rotation primitives for ``account_groups`` and ``account_group_members``.

Ownership rule: every mutation that takes a ``group_id`` MUST also receive the
caller's ``user_id`` via ``get_group(db, group_id, user_id=...)`` so a user
cannot read or mutate another user's pools. Routes are responsible for calling
``get_group`` with the user scope before invoking any member mutation.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional, Tuple

from sqlalchemy import (
    and_,
    delete,
    func,
    or_,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.account import Account
from db.models.account_group import AccountGroup, AccountGroupMember
from db.models.utils import _now


# ── Groups ──────────────────────────────────────────────────────────────────

async def create_group(
    db: AsyncSession,
    *,
    user_id: Optional[str],
    name: str,
    description: str = "",
    platform: str,
    rotation_strategy: str = "round_robin",
) -> AccountGroup:
    group = AccountGroup(
        user_id=user_id,
        name=name,
        description=description,
        platform=platform,
        rotation_strategy=rotation_strategy,
    )
    db.add(group)
    await db.flush()
    return group


async def get_group(
    db: AsyncSession,
    group_id: str,
    *,
    user_id: Optional[str] = None,
) -> Optional[AccountGroup]:
    q = select(AccountGroup).where(AccountGroup.id == group_id)
    if user_id is not None:
        q = q.where(AccountGroup.user_id == user_id)
    result = await db.execute(q)
    return result.scalar_one_or_none()


async def list_groups(
    db: AsyncSession,
    *,
    user_id: Optional[str],
    platform: Optional[str] = None,
) -> List[Tuple[AccountGroup, int]]:
    """Return ``(group, member_count)`` tuples, newest first.

    Uses a single JOIN against a count subquery to avoid N+1 queries.
    """
    count_sq = (
        select(
            AccountGroupMember.group_id.label("group_id"),
            func.count().label("cnt"),
        )
        .group_by(AccountGroupMember.group_id)
        .subquery()
    )
    q = (
        select(AccountGroup, func.coalesce(count_sq.c.cnt, 0))
        .outerjoin(count_sq, count_sq.c.group_id == AccountGroup.id)
        .where(AccountGroup.user_id == user_id)
        .order_by(AccountGroup.created_at.desc())
    )
    if platform:
        q = q.where(AccountGroup.platform == platform)
    rows = (await db.execute(q)).all()
    return [(g, int(c or 0)) for g, c in rows]


_UPDATABLE_FIELDS = {"name", "description", "rotation_strategy"}


async def update_group(
    db: AsyncSession, group_id: str, **fields: Any
) -> None:
    clean = {k: v for k, v in fields.items() if k in _UPDATABLE_FIELDS and v is not None}
    if not clean:
        return
    clean["updated_at"] = _now()
    await db.execute(
        update(AccountGroup).where(AccountGroup.id == group_id).values(**clean)
    )


async def delete_group(db: AsyncSession, group_id: str) -> None:
    # Members cascade via FK. Scenarios referencing this group get account_group_id=NULL
    # via the SET NULL FK added in migration 029 (Phase 4).
    await db.execute(
        delete(AccountGroup).where(AccountGroup.id == group_id)
    )


# ── Members ─────────────────────────────────────────────────────────────────

async def _max_position(db: AsyncSession, group_id: str) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(AccountGroupMember.position), -1)).where(
            AccountGroupMember.group_id == group_id,
        )
    )
    return int(result.scalar_one())


async def add_members(
    db: AsyncSession,
    *,
    group: AccountGroup,
    account_ids: List[str],
) -> Tuple[int, int]:
    """Append accounts to the group. Returns ``(added, skipped)``.

    Skips: accounts belonging to another user, accounts on another platform,
    and accounts already in the group.
    """
    if not account_ids:
        return 0, 0

    # Filter eligible accounts in one query: same platform, visible to the group's owner.
    eligible_rows = (await db.execute(
        select(Account.id).where(
            Account.id.in_(account_ids),
            Account.platform == group.platform,
            or_(
                Account.user_id == group.user_id,
                # Allow accounts with no owner to join any group owned by a user.
                Account.user_id.is_(None),
            ),
        )
    )).all()
    eligible_ids = {row[0] for row in eligible_rows}
    skipped_platform = len(set(account_ids)) - len(eligible_ids)

    # Skip accounts already in the group.
    if eligible_ids:
        existing_rows = (await db.execute(
            select(AccountGroupMember.account_id).where(
                AccountGroupMember.group_id == group.id,
                AccountGroupMember.account_id.in_(eligible_ids),
            )
        )).all()
        existing_ids = {row[0] for row in existing_rows}
    else:
        existing_ids = set()

    to_add = [aid for aid in eligible_ids if aid not in existing_ids]
    if not to_add:
        return 0, skipped_platform + len(existing_ids)

    start_pos = await _max_position(db, group.id) + 1
    for offset, account_id in enumerate(to_add):
        db.add(
            AccountGroupMember(
                group_id=group.id,
                account_id=account_id,
                position=start_pos + offset,
            )
        )
    await db.flush()
    return len(to_add), skipped_platform + len(existing_ids)


async def remove_member(
    db: AsyncSession, *, group_id: str, account_id: str
) -> bool:
    result = await db.execute(
        delete(AccountGroupMember).where(
            and_(
                AccountGroupMember.group_id == group_id,
                AccountGroupMember.account_id == account_id,
            )
        )
    )
    return (result.rowcount or 0) > 0


async def list_members(
    db: AsyncSession, group_id: str
) -> List[dict]:
    """Return a list of dicts with the columns needed by AccountGroupMemberOut."""
    rows = (await db.execute(
        select(
            AccountGroupMember.account_id,
            Account.username,
            Account.display_name,
            Account.status,
            AccountGroupMember.position,
            AccountGroupMember.last_used_at,
            AccountGroupMember.added_at,
        )
        .join(Account, Account.id == AccountGroupMember.account_id)
        .where(AccountGroupMember.group_id == group_id)
        .order_by(AccountGroupMember.position.asc())
    )).all()
    return [
        {
            "account_id": r[0],
            "username": r[1],
            "display_name": r[2] or "",
            "status": r[3],
            "position": int(r[4] or 0),
            "last_used_at": r[5],
            "added_at": r[6],
        }
        for r in rows
    ]


# ── Rotation primitive ──────────────────────────────────────────────────────

async def pick_next_batch(
    db: AsyncSession,
    group_id: str,
    count: int,
) -> List[Account]:
    """Return up to ``count`` distinct usable accounts from the group, advancing state.

    Supports two strategies (column ``rotation_strategy``):

    - ``round_robin`` (default): walks members by ``position`` starting at
      ``rotation_cursor``; the cursor is bumped atomically so that two
      concurrent dispatchers on the same group do not hand out the same
      account. Serialised via ``SELECT ... FOR UPDATE`` on the group row.

    - ``least_recent``: orders members by ``last_used_at ASC NULLS FIRST``,
      which picks never-used members first, then the oldest. ``last_used_at``
      is updated atomically inside the same transaction to prevent two
      concurrent callers picking the same stale members.

    Filters out accounts that are not ``status='active'`` and accounts whose
    ``cooldown_until`` is still in the future. An empty group (or a group
    where every account is banned/cooldown) returns ``[]``.

    Callers MUST commit the surrounding transaction; the cursor/last_used_at
    updates are buffered until commit, so a rollback undoes the rotation.
    """
    if count <= 0:
        return []

    # Acquire a row-level lock on the group to serialise concurrent pickers.
    lock_row = await db.execute(
        select(AccountGroup.id, AccountGroup.rotation_strategy, AccountGroup.rotation_cursor)
        .where(AccountGroup.id == group_id)
        .with_for_update()
    )
    row = lock_row.first()
    if row is None:
        return []
    strategy = row.rotation_strategy
    cursor = int(row.rotation_cursor or 0)

    now = _now()

    # Usable-member query common to both strategies.
    base_q = (
        select(AccountGroupMember.id, Account)
        .join(Account, Account.id == AccountGroupMember.account_id)
        .where(
            AccountGroupMember.group_id == group_id,
            Account.status == "active",
            or_(
                Account.cooldown_until.is_(None),
                Account.cooldown_until <= now,
            ),
        )
    )

    usable_count_result = await db.execute(
        select(func.count(AccountGroupMember.id))
        .select_from(AccountGroupMember)
        .join(Account, Account.id == AccountGroupMember.account_id)
        .where(
            AccountGroupMember.group_id == group_id,
            Account.status == "active",
            or_(
                Account.cooldown_until.is_(None),
                Account.cooldown_until <= now,
            ),
        )
    )
    total = int(usable_count_result.scalar_one() or 0)
    if total == 0:
        return []

    want = min(count, total)
    picks: List[Tuple[str, Account]] = []

    if strategy == "least_recent":
        ordered_q = base_q.order_by(
            AccountGroupMember.last_used_at.asc().nulls_first(),
            AccountGroupMember.position.asc(),
        ).limit(want)
        rows = (await db.execute(ordered_q)).all()
        picks = [(r[0], r[1]) for r in rows]
    else:
        ordered_q = base_q.order_by(AccountGroupMember.position.asc())
        start = cursor % total
        first_take = min(want, total - start)
        if first_take > 0:
            rows1 = (
                await db.execute(ordered_q.offset(start).limit(first_take))
            ).all()
            picks.extend((r[0], r[1]) for r in rows1)
        remaining = want - len(picks)
        if remaining > 0:
            rows2 = (await db.execute(ordered_q.limit(remaining))).all()
            picks.extend((r[0], r[1]) for r in rows2)
        new_cursor = (start + len(picks)) % total
        await db.execute(
            update(AccountGroup)
            .where(AccountGroup.id == group_id)
            .values(rotation_cursor=new_cursor)
        )

    member_ids = [m_id for m_id, _ in picks]
    if member_ids:
        await db.execute(
            update(AccountGroupMember)
            .where(AccountGroupMember.id.in_(member_ids))
            .values(last_used_at=now)
        )

    return [acc for _, acc in picks]
