"""Device registry pair/unpair (DF-T-02-001)."""
from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from typing import Optional

from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud.device import get_device, get_device_by_serial
from db.crud.device_state import ensure_device_state, get_device_state
from db.crud.device_reserve_session import get_active_session
from db.models.device import Device
from db.models.device_key import DeviceKey
from db.models.enums import DeviceFsmEvent, DeviceFsmState, DeviceRegistryStatus
from db.models.utils import _now
from services.device_reserve.exceptions import DeviceInSessionError
from services.device_state.service import DeviceStateService
from services.security_audit import emit_security_event

log = logging.getLogger(__name__)
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
_fsm = DeviceStateService()


@dataclass(frozen=True, slots=True)
class PairDeviceResult:
    device: Device
    created: bool
    device_key_plaintext: Optional[str]


def _normalize_serial(value: str) -> str:
    return (value or "").strip()


async def pair_device(
    db: AsyncSession,
    *,
    org_id: str,
    actor_user_id: str,
    device_serial: str,
    adb_serial: str,
    relay_serial: str,
    name: str = "",
    model: str = "",
    android_version: str = "",
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> PairDeviceResult:
    device_serial = _normalize_serial(device_serial)
    adb_serial = _normalize_serial(adb_serial)
    relay_serial = _normalize_serial(relay_serial)
    if not device_serial:
        raise ValueError("device_serial is required")

    existing = await get_device_by_serial(db, device_serial)
    if existing and existing.org_id != org_id:
        from services.device_state.exceptions import DeviceStateError

        raise DeviceStateError("device serial belongs to another organization", code="NOT_FOUND")

    created = False
    device_key_plain: str | None = None

    if existing is None:
        created = True
        device_key_plain = secrets.token_urlsafe(32)
        device = Device(
            serial=device_serial,
            device_serial=device_serial,
            adb_serial=adb_serial or None,
            relay_serial=relay_serial or None,
            name=name or device_serial,
            model=model or "",
            android_version=android_version or "",
            org_id=org_id,
            user_id=actor_user_id,
            device_key=device_key_plain,
            status=DeviceRegistryStatus.PAIRED.value,
            paired_at=_now(),
            updated_at=_now(),
        )
        db.add(device)
        await db.flush()
        await ensure_device_state(db, device.id)
        db.add(
            DeviceKey(
                device_id=device.id,
                key_hash=_pwd.hash(device_key_plain),
                version=1,
                status="active",
            )
        )
        await _fsm.apply_event(
            db,
            device.id,
            event=DeviceFsmEvent.ATTACHED.value,
            source="registry",
            event_id=f"pair-{device.id}",
        )
        await emit_security_event(
            db,
            action="device.paired",
            user_id=actor_user_id,
            org_id=org_id,
            entity_type="device",
            entity_id=device.id,
            ip_address=ip_address,
            user_agent=user_agent,
            details={
                "device_serial": device_serial,
                "adb_serial": adb_serial,
                "relay_serial": relay_serial,
            },
        )
        return PairDeviceResult(device=device, created=True, device_key_plaintext=device_key_plain)

    device = existing
    old_adb = device.adb_serial
    device.device_serial = device_serial
    device.serial = device_serial
    if adb_serial:
        device.adb_serial = adb_serial
    if relay_serial:
        device.relay_serial = relay_serial
    if name:
        device.name = name
    if model:
        device.model = model
    if android_version:
        device.android_version = android_version
    device.status = DeviceRegistryStatus.PAIRED.value
    device.unpaired_at = None
    device.updated_at = _now()
    if not device.paired_at:
        device.paired_at = _now()
    await db.flush()
    await emit_security_event(
        db,
        action="device.repaired",
        user_id=actor_user_id,
        org_id=org_id,
        entity_type="device",
        entity_id=device.id,
        ip_address=ip_address,
        user_agent=user_agent,
        details={
            "device_serial": device_serial,
            "old_adb_serial": old_adb,
            "new_adb_serial": adb_serial,
            "relay_serial": relay_serial,
        },
    )
    return PairDeviceResult(device=device, created=False, device_key_plaintext=None)


async def unpair_device(
    db: AsyncSession,
    *,
    device_id: str,
    org_id: str,
    actor_user_id: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> Device:
    device = await get_device(db, device_id)
    if not device or device.org_id != org_id:
        from services.device_state.exceptions import DeviceStateError

        raise DeviceStateError("device not found", code="NOT_FOUND")

    state_row = await get_device_state(db, device_id)
    active = await get_active_session(db, device_id)
    if state_row and state_row.state == DeviceFsmState.BUSY.value:
        raise DeviceInSessionError(
            f"device {device_id} has active session",
            session_id=active.id if active else state_row.session_id,
        )
    if active:
        raise DeviceInSessionError(
            f"device {device_id} has active reserve session {active.id}",
            session_id=active.id,
        )

    device.status = DeviceRegistryStatus.UNPAIRED.value
    device.unpaired_at = _now()
    device.updated_at = _now()
    await db.flush()

    await emit_security_event(
        db,
        action="device.unpaired",
        user_id=actor_user_id,
        org_id=org_id,
        entity_type="device",
        entity_id=device.id,
        ip_address=ip_address,
        user_agent=user_agent,
        details={"device_serial": device.device_serial or device.serial},
    )
    return device
