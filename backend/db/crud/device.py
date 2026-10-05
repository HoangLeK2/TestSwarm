from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import delete

from db.models import Device, CampaignDevice
from db.models.utils import _now
from db.crud.device_state import ensure_device_state


PENDING_SERIAL_PREFIX = "pending-"
_UNSET = object()


async def get_device_by_serial(db: AsyncSession, serial: str) -> Optional[Device]:
    result = await db.execute(select(Device).where(Device.serial == serial))
    return result.scalar_one_or_none()


async def get_device_by_key(db: AsyncSession, device_key: str) -> Optional[Device]:
    result = await db.execute(select(Device).where(Device.device_key == device_key))
    return result.scalar_one_or_none()


async def list_devices_by_serial_aliases(db: AsyncSession, aliases: list[str]) -> list[Device]:
    cleaned = {str(alias or "").strip() for alias in aliases}
    cleaned = {alias for alias in cleaned if alias}
    if not cleaned:
        return []

    ips = {alias.rsplit(":", 1)[0] for alias in cleaned if ":" in alias and alias.rsplit(":", 1)[0]}
    stmt = (
        select(Device)
        .where(
            or_(
                Device.serial.in_(cleaned),
                Device.adb_serial.in_(cleaned),
                Device.adb_ip.in_(cleaned | ips),
            )
        )
        .order_by(Device.created_at)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_device(db: AsyncSession, device_id: str) -> Optional[Device]:
    result = await db.execute(select(Device).where(Device.id == device_id))
    return result.scalar_one_or_none()


async def get_devices_by_ids(
    db: AsyncSession, device_ids: list[str]
) -> dict[str, Device]:
    """Batch load devices by primary key — O(1) round-trip."""
    if not device_ids:
        return {}
    result = await db.execute(select(Device).where(Device.id.in_(device_ids)))
    return {row.id: row for row in result.scalars().all()}


async def get_or_create_device(
    db: AsyncSession, serial: str, user_id: Optional[str] = None, org_id: Optional[str] = None
) -> Device:
    """Get existing device by serial, or create a new one (auto-register)."""
    device = await get_device_by_serial(db, serial)
    if device is None:
        device = Device(serial=serial, device_serial=serial, user_id=user_id, org_id=org_id)  # type: ignore[arg-type]
        db.add(device)
        await db.flush()
        await ensure_device_state(db, device.id)
    return device


async def create_device(
    db: AsyncSession,
    serial: str,
    name: str = "",
    user_id: Optional[str] = None,
    org_id: Optional[str] = None,
) -> Device:
    device = Device(serial=serial, device_serial=serial, name=name, user_id=user_id, org_id=org_id)  # type: ignore[arg-type]
    db.add(device)
    await db.flush()
    await ensure_device_state(db, device.id)
    return device


async def create_pending_device(
    db: AsyncSession,
    user_id: str,
    name: str = "",
    org_id: Optional[str] = None,
) -> Device:
    """Tạo bản ghi thiết bị chưa kết nối (đăng ký). Serial = pending-{uuid}."""
    serial = f"{PENDING_SERIAL_PREFIX}{uuid.uuid4().hex}"
    device = Device(serial=serial, device_serial=serial, name=name or "Thiết bị mới", user_id=user_id, org_id=org_id)  # type: ignore[arg-type]
    db.add(device)
    await db.flush()
    await ensure_device_state(db, device.id)
    return device


async def bind_pending_device(
    db: AsyncSession,
    device_key: str,
    serial: str,
    *,
    brand: str = "",
    model: str = "",
    android_version: str = "",
    sdk_version: int = 0,
    screen_width: int = 0,
    screen_height: int = 0,
    adb_serial: str | object = _UNSET,
    adb_ip: str | object = _UNSET,
    adb_port: int | object = _UNSET,
) -> Optional[Device]:
    """
    Gắn thiết bị pending (tìm theo device_key) với serial thật từ điện thoại.
    """
    device = await get_device_by_key(db, device_key)
    if not device:
        return None

    # Case 1: pending device → bind lần đầu
    if device.serial.startswith(PENDING_SERIAL_PREFIX):
        existing = await get_device_by_serial(db, serial)
        if existing and existing.id != device.id:
            if existing.user_id is not None:
                return None  # serial đã thuộc thiết bị của user khác → reject
            # Auto-created device (không có owner, do phone kết nối trước khi quét QR)
            # → xóa để pending device lấy serial này
            await db.execute(delete(Device).where(Device.id == existing.id))
            await db.flush()
        values = {
            "serial": serial,
            "brand": brand,
            "model": model,
            "android_version": android_version,
            "sdk_version": sdk_version,
            "screen_width": screen_width,
            "screen_height": screen_height,
            "last_seen": _now(),
        }
        if adb_serial is not _UNSET:
            values["adb_serial"] = str(adb_serial or "").strip() or None
        if adb_ip is not _UNSET:
            values["adb_ip"] = str(adb_ip or "").strip() or None
        if adb_port is not _UNSET:
            values["adb_port"] = int(adb_port or 5555)
        await db.execute(update(Device).where(Device.id == device.id).values(**values))
        await db.flush()
        device.serial = serial
    else:
        # Case 2: device đã bind trước đó → cho phép re-connect với cùng serial
        if device.serial != serial:
            return None
        values = {
            "brand": brand,
            "model": model,
            "android_version": android_version,
            "sdk_version": sdk_version,
            "screen_width": screen_width,
            "screen_height": screen_height,
            "last_seen": _now(),
        }
        if adb_serial is not _UNSET:
            values["adb_serial"] = str(adb_serial or "").strip() or None
        if adb_ip is not _UNSET:
            values["adb_ip"] = str(adb_ip or "").strip() or None
        if adb_port is not _UNSET:
            values["adb_port"] = int(adb_port or 5555)
        await db.execute(update(Device).where(Device.id == device.id).values(**values))
        await db.flush()

    device.brand = brand
    device.model = model
    device.android_version = android_version
    device.sdk_version = sdk_version
    device.screen_width = screen_width
    device.screen_height = screen_height
    if adb_serial is not _UNSET:
        device.adb_serial = str(adb_serial or "").strip() or None
    if adb_ip is not _UNSET:
        device.adb_ip = str(adb_ip or "").strip() or None
    if adb_port is not _UNSET:
        device.adb_port = int(adb_port or 5555)
    return device


async def update_device_metadata(
    db: AsyncSession,
    serial: str,
    *,
    brand: str = "",
    model: str = "",
    android_version: str = "",
    sdk_version: int = 0,
    screen_width: int = 0,
    screen_height: int = 0,
    adb_serial: str | None = None,
    adb_ip: str | None = None,
    adb_port: int | None = None,
) -> None:
    values: dict = {
        "brand": brand,
        "model": model,
        "android_version": android_version,
        "sdk_version": sdk_version,
        "screen_width": screen_width,
        "screen_height": screen_height,
        "last_seen": _now(),
    }
    if adb_ip is not None:
        values["adb_ip"] = adb_ip
    if adb_serial is not None:
        values["adb_serial"] = adb_serial or None
    if adb_port is not None:
        values["adb_port"] = adb_port
    await db.execute(
        update(Device)
        .where(Device.serial == serial)
        .values(**values)
    )


async def update_device_adb_identity(
    db: AsyncSession,
    serial: str,
    *,
    adb_serial: str | None = None,
    adb_ip: str | None = None,
    adb_port: int | None = None,
) -> None:
    values: dict = {}
    if adb_serial is not None:
        values["adb_serial"] = str(adb_serial or "").strip() or None
    if adb_ip is not None:
        values["adb_ip"] = str(adb_ip or "").strip() or None
    if adb_port is not None:
        values["adb_port"] = int(adb_port or 5555)
    if not values:
        return
    await db.execute(
        update(Device)
        .where(Device.serial == serial)
        .values(**values)
    )


async def update_device_name(db: AsyncSession, device_id: str, name: str) -> None:
    """Update display name for a device."""
    await db.execute(
        update(Device).where(Device.id == device_id).values(name=name)
    )


async def assign_device_to_user(db: AsyncSession, serial: str, user_id: str) -> None:
    """Assign a device to a user if it has no owner yet."""
    await db.execute(
        update(Device)
        .where(Device.serial == serial)
        .where(Device.user_id.is_(None))
        .values(user_id=user_id)
    )


async def touch_device_last_seen(db: AsyncSession, serial: str) -> None:
    await db.execute(
        update(Device).where(Device.serial == serial).values(last_seen=_now())
    )


async def list_devices(
    db: AsyncSession,
    *,
    org_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> list[Device]:
    q = select(Device).order_by(Device.created_at)
    # Prefer org scoping (multi-user org). `user_id` kept for legacy call sites.
    if org_id:
        from db.crud.organization import list_organization_members

        member_rows = await list_organization_members(db, org_id)
        member_ids = [
            str(member.user_id)
            for member, _ in member_rows
            if getattr(member, "user_id", None)
        ]
        if member_ids:
            q = q.where(
                or_(
                    Device.org_id == org_id,
                    (Device.org_id.is_(None)) & (Device.user_id.in_(member_ids)),
                )
            )
        else:
            q = q.where(Device.org_id == org_id)
    elif user_id:
        q = q.where(Device.user_id == user_id)
    result = await db.execute(q)
    return list(result.scalars().all())


async def relay_scrcpy_auto_attach_allowed(db: AsyncSession, serial: str) -> bool:
    """True if auto-attach is OK: unknown device in DB → allow (default on)."""
    row = await get_device_by_serial(db, serial)
    if row is None:
        return True
    return bool(row.relay_scrcpy_enabled)


async def get_relay_scrcpy_enabled_map(
    db: AsyncSession, serials: list[str]
) -> dict[str, bool]:
    if not serials:
        return {}
    result = await db.execute(
        select(Device.serial, Device.relay_scrcpy_enabled).where(Device.serial.in_(serials))
    )
    return {str(r.serial): bool(r.relay_scrcpy_enabled) for r in result.all()}


async def set_relay_scrcpy_enabled(db: AsyncSession, serial: str, enabled: bool) -> None:
    await db.execute(
        update(Device).where(Device.serial == serial).values(relay_scrcpy_enabled=enabled)
    )
    await db.commit()


async def delete_device(db: AsyncSession, device_id: str) -> None:
    """
    Xoá device và mọi liên kết campaign-device của nó.
    """
    from db.crud.account import unassign_account_from_device
    from db.models.account import DeviceAccount

    # Remove from campaigns first
    await db.execute(delete(CampaignDevice).where(CampaignDevice.device_id == device_id))
    # Unlink accounts through the normal path so `unassigned` stays in step with
    # the link table — the FK cascade below would drop the rows silently.
    linked = (
        await db.execute(
            select(DeviceAccount.account_id).where(DeviceAccount.device_id == device_id)
        )
    ).scalars().all()
    for account_id in linked:
        await unassign_account_from_device(db, device_id, account_id)
    # Then delete the device
    await db.execute(delete(Device).where(Device.id == device_id))
