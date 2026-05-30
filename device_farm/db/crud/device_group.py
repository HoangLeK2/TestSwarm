from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import delete, func, select, update
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
