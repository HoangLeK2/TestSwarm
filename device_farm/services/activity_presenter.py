from __future__ import annotations

from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.analytics import ActivityLogOut
from db.models.activity import ActivityLog
from services.notification_service import device_event_label
from tenancy.background import DeviceRef, lookup_device_by_id, lookup_device_by_serial


def _label_from_ref(ref: DeviceRef) -> str:
    return device_event_label(
        serial=ref.serial,
        brand=ref.brand,
        model=ref.model,
        name=ref.name,
    )


def _stored_device_label(details: dict[str, Any]) -> str | None:
    raw = details.get("device_label")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


async def _load_users_by_id(db: AsyncSession, user_ids: set[str]) -> dict[str, str]:
    if not user_ids:
        return {}
    rows = await db.execute(
        text(
            """
            SELECT id, name, email
            FROM users
            WHERE id IN :ids
            """
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": list(user_ids)},
    )
    out: dict[str, str] = {}
    for user_id, name, email in rows.fetchall():
        clean_name = str(name or "").strip()
        clean_email = str(email or "").strip()
        out[str(user_id)] = clean_name or clean_email or str(user_id)
    return out


async def _load_devices_by_id(db: AsyncSession, device_ids: set[str]) -> dict[str, DeviceRef]:
    if not device_ids:
        return {}
    rows = await db.execute(
        text(
            """
            SELECT id, serial, user_id, org_id, name, brand, model
            FROM devices
            WHERE id IN :ids
            """
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": list(device_ids)},
    )
    return {
        str(row[0]): DeviceRef(
            device_id=row[0],
            serial=row[1],
            user_id=row[2],
            org_id=row[3],
            name=row[4] or "",
            brand=row[5] or "",
            model=row[6] or "",
        )
        for row in rows.fetchall()
    }


async def _load_devices_by_serial_keys(
    db: AsyncSession,
    serial_keys: set[str],
) -> dict[str, DeviceRef]:
    if not serial_keys:
        return {}
    rows = await db.execute(
        text(
            """
            SELECT id, serial, user_id, org_id, name, brand, model, adb_serial
            FROM devices
            WHERE serial IN :keys OR adb_serial IN :keys
            """
        ).bindparams(bindparam("keys", expanding=True)),
        {"keys": list(serial_keys)},
    )
    out: dict[str, DeviceRef] = {}
    for row in rows.fetchall():
        ref = DeviceRef(
            device_id=row[0],
            serial=row[1],
            user_id=row[2],
            org_id=row[3],
            name=row[4] or "",
            brand=row[5] or "",
            model=row[6] or "",
        )
        out[str(row[1])] = ref
        adb_serial = row[7]
        if adb_serial:
            out[str(adb_serial)] = ref
    return out


def _path_params(row: ActivityLog) -> dict[str, Any]:
    details = row.details if isinstance(row.details, dict) else {}
    path_params = details.get("path_params")
    return path_params if isinstance(path_params, dict) else {}


async def resolve_device_label_for_audit(
    db: AsyncSession,
    *,
    path_params: dict[str, Any],
    device_serial: str | None = None,
) -> tuple[str | None, str | None]:
    """Return ``(device_serial, display_label)`` for audit rows."""
    serial_key = str(path_params.get("serial") or "").strip()
    device_id = str(path_params.get("device_id") or "").strip()

    ref: DeviceRef | None = None
    if device_serial:
        ref = await lookup_device_by_serial(db, device_serial)
    elif serial_key:
        ref = await lookup_device_by_serial(db, serial_key)
    elif device_id:
        ref = await lookup_device_by_id(db, device_id)

    if ref is None:
        fallback_serial = device_serial or serial_key or None
        if fallback_serial and not _looks_like_uuid(fallback_serial):
            return fallback_serial, fallback_serial
        return fallback_serial, None

    return ref.serial, _label_from_ref(ref)


def _looks_like_uuid(value: str) -> bool:
    parts = value.split("-")
    return len(parts) == 5 and len(value) >= 32


async def present_activity_logs(
    db: AsyncSession,
    rows: list[ActivityLog],
) -> list[ActivityLogOut]:
    user_ids = {str(row.user_id) for row in rows if row.user_id}
    device_ids: set[str] = set()
    serial_keys: set[str] = set()

    for row in rows:
        if row.device_serial:
            serial_keys.add(str(row.device_serial))
        path_params = _path_params(row)
        serial_key = str(path_params.get("serial") or "").strip()
        device_id = str(path_params.get("device_id") or "").strip()
        if serial_key:
            serial_keys.add(serial_key)
        if device_id:
            device_ids.add(device_id)

    users_by_id = await _load_users_by_id(db, user_ids)
    devices_by_id = await _load_devices_by_id(db, device_ids)
    devices_by_serial = await _load_devices_by_serial_keys(db, serial_keys)

    presented: list[ActivityLogOut] = []
    for row in rows:
        details = dict(row.details) if isinstance(row.details, dict) else {}
        device_display = _stored_device_label(details)
        resolved_serial = row.device_serial

        if not device_display:
            path_params = _path_params(row)
            serial_key = str(path_params.get("serial") or "").strip()
            device_id = str(path_params.get("device_id") or "").strip()
            ref: DeviceRef | None = None
            if row.device_serial and row.device_serial in devices_by_serial:
                ref = devices_by_serial[row.device_serial]
            elif serial_key and serial_key in devices_by_serial:
                ref = devices_by_serial[serial_key]
            elif device_id and device_id in devices_by_id:
                ref = devices_by_id[device_id]
            if ref is not None:
                device_display = _label_from_ref(ref)
                resolved_serial = ref.serial
            elif row.device_serial and not _looks_like_uuid(str(row.device_serial)):
                device_display = str(row.device_serial)
            elif serial_key and not _looks_like_uuid(serial_key):
                device_display = serial_key
                resolved_serial = serial_key or resolved_serial

        user_name = users_by_id.get(str(row.user_id)) if row.user_id else None
        presented.append(
            ActivityLogOut(
                id=row.id,
                action=row.action,
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                device_serial=resolved_serial,
                org_id=row.org_id,
                user_id=row.user_id,
                user_name=user_name,
                device_display=device_display,
                method=row.method,
                path=row.path,
                route_template=row.route_template,
                status_code=row.status_code,
                request_id=row.request_id,
                ip_address=row.ip_address,
                user_agent=row.user_agent,
                outcome=row.outcome,
                duration_ms=row.duration_ms,
                details=details,
                created_at=row.created_at,
            )
        )
    return presented
