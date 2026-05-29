from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.device import Device, DeviceSession


def _serial_candidates(device) -> list[str]:
    out: list[str] = []

    def add(value) -> None:
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text)

    add(getattr(device, "serial", None))
    add(getattr(device, "adb_serial", None))
    adb_ip = str(getattr(device, "adb_ip", "") or "").strip()
    if adb_ip:
        add(f"{adb_ip}:{getattr(device, 'adb_port', 5555)}")
        add(adb_ip)
    return out


def relay_has_device(device) -> bool:
    try:
        from runtime.transports.adb_relay_server import get_relay_manager

        relay = get_relay_manager()
    except Exception:
        relay = None
    if relay is None:
        return False
    for serial in _serial_candidates(device):
        try:
            if relay.relay_for_serial(serial):
                return True
        except Exception:
            continue
    return False


def manager_has_live_device(manager, device) -> bool:
    if manager is None:
        return False
    for serial in _serial_candidates(device):
        runtime_device = manager.get_device(serial)
        if runtime_device is None:
            continue
        try:
            status = runtime_device.status_dict()
        except Exception:
            continue
        state = str(status.get("state") or "").upper()
        if state in {"DISCONNECTED", "DEAD"}:
            continue
        if status.get("agent_connected") or status.get("u2_ready") or relay_has_device(device):
            return True
    return False


async def db_has_open_session(db: AsyncSession, device_id: str | None) -> bool:
    if not device_id:
        return False
    result = await db.execute(
        select(DeviceSession.id)
        .where(DeviceSession.device_id == device_id, DeviceSession.disconnected_at.is_(None))
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


def db_last_seen_recent(device, *, offline_after_minutes: int) -> bool:
    last_seen = getattr(device, "last_seen", None)
    if last_seen is None:
        # Tests and non-DB stand-ins often omit last_seen. Treat them as live;
        # real ORM Device rows always expose the attribute.
        return not hasattr(device, "last_seen")
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(1, int(offline_after_minutes)))
    return last_seen >= cutoff


async def is_device_dispatchable(
    db: AsyncSession,
    device,
    *,
    offline_after_minutes: int,
    manager=None,
) -> bool:
    if relay_has_device(device) or manager_has_live_device(manager, device):
        return True
    if not hasattr(device, "last_seen"):
        # Unit-test stand-ins and non-ORM callers do not carry persisted health.
        return True
    last_seen = getattr(device, "last_seen", None)
    if last_seen is not None and not isinstance(last_seen, datetime):
        return True
    if await db_has_open_session(db, getattr(device, "id", None)):
        return True
    return db_last_seen_recent(device, offline_after_minutes=offline_after_minutes)


async def filter_live_devices_for_dispatch(
    db: AsyncSession,
    devices: Sequence,
    *,
    offline_after_minutes: int,
    manager=None,
) -> tuple[list, list]:
    live: list = []
    skipped: list = []
    for device in devices:
        if await is_device_dispatchable(
            db,
            device,
            offline_after_minutes=offline_after_minutes,
            manager=manager,
        ):
            live.append(device)
        else:
            skipped.append(device)
    return live, skipped


async def list_stale_offline_devices(
    db: AsyncSession,
    devices: Iterable[Device],
    *,
    offline_after_minutes: int,
    manager=None,
) -> list[Device]:
    stale: list[Device] = []
    for device in devices:
        if not await is_device_dispatchable(
            db,
            device,
            offline_after_minutes=offline_after_minutes,
            manager=manager,
        ):
            stale.append(device)
    return stale
