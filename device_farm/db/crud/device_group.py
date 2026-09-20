from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.device_group import DeviceGroup, DeviceGroupMember
from db.models.device import Device
from tenancy.context import get_current_org_id


# ── DeviceGroup CRUD ──────────────────────────────────────────────────────────


async def create_group(
    db: AsyncSession,
    name: str,
    user_id: str | None = None,
    org_id: str | None = None,
    description: str = "",
    color: str = "#6366f1",
) -> DeviceGroup:
    group = DeviceGroup(
        name=name,
        description=description,
        color=color,
        user_id=user_id,
        org_id=org_id or get_current_org_id(),
    )
    db.add(group)
    await db.flush()
    return group


async def get_group(db: AsyncSession, group_id: str) -> Optional[DeviceGroup]:
    result = await db.execute(
        select(DeviceGroup).where(DeviceGroup.id == group_id)
    )
    return result.scalar_one_or_none()


async def list_groups(
    db: AsyncSession, user_id: str | None = None
) -> list[DeviceGroup]:
    q = select(DeviceGroup).order_by(DeviceGroup.created_at.desc())
    if user_id:
        q = q.where(DeviceGroup.user_id == user_id)
    result = await db.execute(q)
    return list(result.scalars().all())


async def update_group(
    db: AsyncSession, group_id: str, **kwargs: Any
) -> None:
    await db.execute(
        update(DeviceGroup).where(DeviceGroup.id == group_id).values(**kwargs)
    )


async def delete_group(db: AsyncSession, group_id: str) -> None:
    # DeviceGroupMember rows are cascade-deleted by the FK constraint.
    await db.execute(delete(DeviceGroup).where(DeviceGroup.id == group_id))


# ── Member management ─────────────────────────────────────────────────────────


async def add_devices_to_group(
    db: AsyncSession,
    group_id: str,
    device_ids: list[str],
    org_id: str | None = None,
) -> int:
    """
    Add multiple devices to a group. Already-present memberships are silently skipped
    (idempotent). Returns the number of new rows inserted.
    """
    # Fetch existing memberships in one query to avoid per-device round-trips.
    existing_result = await db.execute(
        select(DeviceGroupMember.device_id).where(
            DeviceGroupMember.group_id == group_id,
            DeviceGroupMember.device_id.in_(device_ids),
        )
    )
    existing_ids = {row[0] for row in existing_result.all()}
    if org_id is None:
        group_org_result = await db.execute(
            select(DeviceGroup.org_id).where(DeviceGroup.id == group_id)
        )
        org_id = group_org_result.scalar_one_or_none()

    inserted = 0
    for did in device_ids:
        if did not in existing_ids:
            db.add(DeviceGroupMember(group_id=group_id, device_id=did, org_id=org_id))
            inserted += 1

    if inserted:
        await db.flush()
    return inserted


async def remove_device_from_group(
    db: AsyncSession, group_id: str, device_id: str
) -> None:
    await db.execute(
        delete(DeviceGroupMember).where(
            DeviceGroupMember.group_id == group_id,
            DeviceGroupMember.device_id == device_id,
        )
    )


async def list_group_devices(
    db: AsyncSession, group_id: str
) -> list[Device]:
    """Return all Device rows belonging to this group (ordered by creation time)."""
    result = await db.execute(
        select(Device)
        .join(DeviceGroupMember, DeviceGroupMember.device_id == Device.id)
        .where(DeviceGroupMember.group_id == group_id)
        .order_by(Device.created_at)
    )
    return list(result.scalars().all())


async def list_available_group_devices(
    db: AsyncSession,
    group_id: str,
    *,
    org_id: str | None = None,
    user_id: str | None = None,
    include_managed_by_org: bool = False,
    search: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Device], int]:
    """Return visible devices that are not already members of a group."""
    member_device_ids = select(DeviceGroupMember.device_id).where(
        DeviceGroupMember.group_id == group_id
    )
    filters = [Device.id.not_in(member_device_ids)]

    if org_id:
        from db.crud.organization import list_organization_members

        member_rows = await list_organization_members(db, org_id)
        member_ids = [
            str(member.user_id)
            for member, _ in member_rows
            if getattr(member, "user_id", None)
        ]
        if member_ids:
            org_conditions = [
                Device.org_id == org_id,
                and_(Device.org_id.is_(None), Device.user_id.in_(member_ids)),
            ]
            if include_managed_by_org:
                org_conditions.append(Device.managed_by_org_id == org_id)
            filters.append(or_(*org_conditions))
        else:
            org_conditions = [Device.org_id == org_id]
            if include_managed_by_org:
                org_conditions.append(Device.managed_by_org_id == org_id)
            filters.append(or_(*org_conditions))
    elif user_id:
        filters.append(Device.user_id == user_id)

    term = (search or "").strip()
    if term:
        pattern = f"%{term}%"
        filters.append(
            or_(
                Device.name.ilike(pattern),
                Device.serial.ilike(pattern),
                Device.device_serial.ilike(pattern),
                Device.adb_serial.ilike(pattern),
                Device.relay_serial.ilike(pattern),
                Device.brand.ilike(pattern),
                Device.model.ilike(pattern),
            )
        )

    total = int(
        (
            await db.execute(
                select(func.count()).select_from(Device).where(*filters)
            )
        ).scalar_one()
        or 0
    )
    result = await db.execute(
        select(Device)
        .where(*filters)
        .order_by(Device.created_at, Device.id)
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all()), total


async def get_group_device_ids(
    db: AsyncSession, group_id: str
) -> list[str]:
    """Return only device UUIDs for a group (lightweight — no JOIN to Device table)."""
    result = await db.execute(
        select(DeviceGroupMember.device_id).where(
            DeviceGroupMember.group_id == group_id
        )
    )
    return [row[0] for row in result.all()]


async def snapshot_group_device_ids(
    db: AsyncSession,
    group_id: str,
    *,
    for_update: bool = False,
) -> list[str]:
    """Atomically read group membership for dispatch snapshot."""
    stmt = select(DeviceGroupMember.device_id).where(
        DeviceGroupMember.group_id == group_id
    )
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    return [row[0] for row in result.all()]


async def snapshot_groups_device_ids(
    db: AsyncSession,
    group_ids: list[str],
    *,
    for_update: bool = False,
) -> dict[str, list[str]]:
    """Batch snapshot membership for multiple groups in one query."""
    if not group_ids:
        return {}
    stmt = select(DeviceGroupMember.group_id, DeviceGroupMember.device_id).where(
        DeviceGroupMember.group_id.in_(group_ids)
    ).order_by(DeviceGroupMember.group_id, DeviceGroupMember.device_id)
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    out: dict[str, list[str]] = {gid: [] for gid in group_ids}
    for group_id, device_id in result.all():
        out.setdefault(group_id, []).append(device_id)
    return out


async def get_groups_by_ids(
    db: AsyncSession, group_ids: list[str]
) -> dict[str, DeviceGroup]:
    if not group_ids:
        return {}
    result = await db.execute(
        select(DeviceGroup).where(DeviceGroup.id.in_(group_ids))
    )
    return {row.id: row for row in result.scalars().all()}


async def get_group_device_serials(
    db: AsyncSession, group_id: str
) -> frozenset[str]:
    """
    Return the set of device serials for all members of a group.

    Used at fleet/campaign dispatch time to filter live devices.
    Returns a frozenset so callers can do O(1) membership checks.
    """
    result = await db.execute(
        select(Device.serial)
        .join(DeviceGroupMember, DeviceGroupMember.device_id == Device.id)
        .where(DeviceGroupMember.group_id == group_id)
    )
    return frozenset(row[0] for row in result.all())


async def count_group_members(db: AsyncSession, group_id: str) -> int:
    result = await db.execute(
        select(func.count()).where(DeviceGroupMember.group_id == group_id)
    )
    return result.scalar_one() or 0


async def count_group_members_map(
    db: AsyncSession,
    group_ids: list[str],
) -> dict[str, int]:
    ids = [group_id for group_id in dict.fromkeys(group_ids) if group_id]
    if not ids:
        return {}
    result = await db.execute(
        select(DeviceGroupMember.group_id, func.count().label("cnt"))
        .where(DeviceGroupMember.group_id.in_(ids))
        .group_by(DeviceGroupMember.group_id)
    )
    return {str(group_id): int(cnt or 0) for group_id, cnt in result.all()}


# ── Device tags ───────────────────────────────────────────────────────────────


async def update_device_tags(
    db: AsyncSession, device_id: str, tags: str
) -> None:
    """
    Replace a device's tags with a new comma-separated string.

    Normalises the string: strip whitespace, remove empty segments, lowercase.
    e.g. "Fast , WiFi,  " → "fast,wifi"
    """
    normalized = ",".join(
        t.strip().lower()
        for t in tags.split(",")
        if t.strip()
    )
    await db.execute(
        update(Device).where(Device.id == device_id).values(tags=normalized)
    )


async def get_all_device_serial_tags(
    db: AsyncSession,
) -> dict[str, str]:
    """
    Return {serial: tags_string} for all devices.

    Used at fleet dispatch time so the synchronous dispatch function can
    filter by tags without additional DB round-trips.
    """
    result = await db.execute(select(Device.serial, Device.tags))
    return {row[0]: (row[1] or "") for row in result.all()}
