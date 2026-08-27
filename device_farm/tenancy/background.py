"""Helpers for background workers that run outside HTTP request tenant context."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class DeviceRef:
    device_id: str
    serial: str
    user_id: str | None
    org_id: str | None
    name: str
    brand: str = ""
    model: str = ""


async def lookup_device_by_key(
    db: AsyncSession,
    device_key: str,
) -> DeviceRef | None:
    """Load device by pairing key via raw SQL (device-agent WS has no HTTP tenant context)."""
    if not device_key:
        return None
    row = (
        await db.execute(
            text(
                """
                SELECT id, serial, user_id, org_id, name, brand, model
                FROM devices
                WHERE device_key = :device_key
                LIMIT 1
                """
            ),
            {"device_key": device_key},
        )
    ).first()
    if row is None:
        return None
    return DeviceRef(
        device_id=row[0],
        serial=row[1],
        user_id=row[2],
        org_id=row[3],
        name=row[4] or "",
        brand=row[5] or "",
        model=row[6] or "",
    )


async def lookup_device_by_serial(
    db: AsyncSession,
    serial: str,
) -> DeviceRef | None:
    """Load device by serial via raw SQL (no tenant ORM context required)."""
    if not serial:
        return None
    row = (
        await db.execute(
            text(
                """
                SELECT id, serial, user_id, org_id, name, brand, model
                FROM devices
                WHERE serial = :serial OR adb_serial = :serial
                LIMIT 1
                """
            ),
            {"serial": serial},
        )
    ).first()
    if row is None:
        return None
    return DeviceRef(
        device_id=row[0],
        serial=row[1],
        user_id=row[2],
        org_id=row[3],
        name=row[4] or "",
        brand=row[5] or "",
        model=row[6] or "",
    )


async def list_device_serials_for_user(
    db: AsyncSession,
    user_id: str,
    *,
    org_id: str | None = None,
) -> set[str]:
    """Serials visible to ``user_id`` for frontend WS allowlists.

    Org members see all devices in the effective org (JWT ``org_id`` or
    ``users.default_org_id``), not only rows they personally registered.
    """
    if not user_id:
        return set()
    user_row = (
        await db.execute(
            text(
                """
                SELECT default_org_id, role
                FROM users
                WHERE id = :user_id
                LIMIT 1
                """
            ),
            {"user_id": user_id},
        )
    ).first()
    if user_row is None:
        return set()
    default_org_id, role = user_row[0], str(user_row[1] or "")
    requested_org = (org_id or "").strip() or None
    effective_org = (requested_org or default_org_id or "").strip() or None
    if role == "superadmin" and requested_org is None:
        rows = await db.execute(
            text(
                """
                SELECT serial
                FROM devices
                WHERE serial IS NOT NULL
                  AND serial <> ''
                """
            )
        )
        return {str(r[0]) for r in rows.fetchall()}
    if effective_org:
        rows = await db.execute(
            text(
                """
                SELECT serial
                FROM devices
                WHERE org_id = :org_id
                  AND serial IS NOT NULL
                  AND serial <> ''
                """
            ),
            {"org_id": effective_org},
        )
        return {str(r[0]) for r in rows.fetchall()}
    rows = await db.execute(
        text(
            """
            SELECT serial
            FROM devices
            WHERE user_id = :user_id
              AND serial IS NOT NULL
              AND serial <> ''
            """
        ),
        {"user_id": user_id},
    )
    return {str(r[0]) for r in rows.fetchall()}


async def lookup_device_by_id(
    db: AsyncSession,
    device_id: str,
) -> DeviceRef | None:
    """Load device by primary key via raw SQL (no tenant ORM context required)."""
    if not device_id:
        return None
    row = (
        await db.execute(
            text(
                """
                SELECT id, serial, user_id, org_id, name, brand, model
                FROM devices
                WHERE id = :device_id
                LIMIT 1
                """
            ),
            {"device_id": device_id},
        )
    ).first()
    if row is None:
        return None
    return DeviceRef(
        device_id=row[0],
        serial=row[1],
        user_id=row[2],
        org_id=row[3],
        name=row[4] or "",
        brand=row[5] or "",
        model=row[6] or "",
    )


async def lookup_device_owner_by_serial(
    db: AsyncSession,
    serial: str,
) -> tuple[str | None, str | None]:
    """Return ``(user_id, org_id)`` for a device serial."""
    ref = await lookup_device_by_serial(db, serial)
    if ref is None:
        return None, None
    return ref.user_id, ref.org_id


async def ensure_device_org_id(
    db: AsyncSession,
    device_id: str,
    org_id: str,
) -> None:
    """Backfill ``org_id`` on legacy rows created without tenant scoping."""
    await db.execute(
        text(
            """
            UPDATE devices
            SET org_id = :org_id
            WHERE id = :device_id
              AND (org_id IS NULL OR org_id = :org_id)
            """
        ),
        {"org_id": org_id, "device_id": device_id},
    )
