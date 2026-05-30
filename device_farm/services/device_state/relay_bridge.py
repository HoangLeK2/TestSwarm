"""Map relay transport online/offline to control-plane device FSM (DF-T-02-002)."""
from __future__ import annotations

import logging
import time
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud.device_state import get_device_state
from db.database import AsyncSessionLocal
from db.models.enums import DeviceFsmEvent, DeviceFsmState
from services.device_state.fsm import normalize_state
from services.device_state.service import ApplyOutcome, DeviceStateService

log = logging.getLogger(__name__)


async def resolve_device_id_for_relay(
    db: AsyncSession,
    relay_serial: str,
    *,
    logical_serial: Optional[str] = None,
    hardware_serial: Optional[str] = None,
) -> Optional[str]:
    """Resolve a DB device id from relay/adb serial aliases."""
    keys: list[str] = []
    for raw in (logical_serial, relay_serial, hardware_serial):
        s = (raw or "").strip()
        if s and s not in keys:
            keys.append(s)

    if not keys:
        return None

    device_ip = relay_serial.rsplit(":", 1)[0] if ":" in relay_serial else None
    params: dict[str, object] = {
        "k0": keys[0],
        "k1": keys[1] if len(keys) > 1 else keys[0],
        "k2": keys[2] if len(keys) > 2 else keys[0],
        "ip": device_ip or "",
        "ip_prefix": f"{device_ip}:%" if device_ip else "",
    }
    row = (
        await db.execute(
            text(
                """
                SELECT id
                FROM devices
                WHERE serial IN (:k0, :k1, :k2)
                   OR adb_serial IN (:k0, :k1, :k2)
                   OR (:ip <> '' AND adb_ip = :ip)
                   OR (:ip_prefix <> '' AND adb_serial LIKE :ip_prefix)
                LIMIT 1
                """
            ),
            params,
        )
    ).scalar_one_or_none()
    return row


async def apply_relay_online(
    relay_serial: str,
    *,
    logical_serial: Optional[str] = None,
    hardware_serial: Optional[str] = None,
    db: Optional[AsyncSession] = None,
) -> bool:
    """Advance FSM when relay reports a device transport is up."""
    if db is not None:
        return await _apply_relay_online_db(
            db,
            relay_serial,
            logical_serial=logical_serial,
            hardware_serial=hardware_serial,
        )

    async with AsyncSessionLocal() as session:
        ok = await _apply_relay_online_db(
            session,
            relay_serial,
            logical_serial=logical_serial,
            hardware_serial=hardware_serial,
        )
        await session.commit()
        return ok


async def _apply_relay_online_db(
    db: AsyncSession,
    relay_serial: str,
    *,
    logical_serial: Optional[str] = None,
    hardware_serial: Optional[str] = None,
) -> bool:
    device_id = await resolve_device_id_for_relay(
        db,
        relay_serial,
        logical_serial=logical_serial,
        hardware_serial=hardware_serial,
    )
    if not device_id:
        log.debug(
            "relay FSM online: no DB device relay=%s logical=%s hw=%s",
            relay_serial,
            logical_serial,
            hardware_serial,
        )
        return False

    svc = DeviceStateService()
    current = await svc.get_state(db, device_id)
    if current in (DeviceFsmState.ONLINE, DeviceFsmState.BUSY):
        return True

    ts = int(time.time() * 1000)
    tag = device_id[:8]

    if current in (DeviceFsmState.UNKNOWN, DeviceFsmState.DEAD):
        attached = await svc.apply_event(
            db,
            device_id,
            event=DeviceFsmEvent.ATTACHED.value,
            source="agent",
            event_id=f"relay-{tag}-attached-{ts}",
            payload={"relay_serial": relay_serial},
        )
        if attached.outcome == ApplyOutcome.ILLEGAL:
            log.debug(
                "relay FSM attached ignored device=%s relay=%s state=%s",
                device_id,
                relay_serial,
                current.value,
            )
        current = attached.state

    if current in (DeviceFsmState.CONNECTING, DeviceFsmState.RECONNECTING):
        online = await svc.apply_event(
            db,
            device_id,
            event=DeviceFsmEvent.ONLINE.value,
            source="agent",
            event_id=f"relay-{tag}-online-{ts}",
            payload={"relay_serial": relay_serial},
        )
        if online.outcome == ApplyOutcome.ILLEGAL:
            log.debug(
                "relay FSM online ignored device=%s relay=%s state=%s",
                device_id,
                relay_serial,
                current.value,
            )
        current = online.state

    row = await get_device_state(db, device_id)
    final = normalize_state(row.state if row else current.value)
    log.info(
        "relay FSM online device=%s relay=%s → %s",
        device_id,
        relay_serial,
        final.value,
    )
    return final in (DeviceFsmState.ONLINE, DeviceFsmState.BUSY)


async def apply_relay_offline(
    relay_serial: str,
    *,
    logical_serial: Optional[str] = None,
    hardware_serial: Optional[str] = None,
    db: Optional[AsyncSession] = None,
) -> bool:
    """Mark FSM reconnecting when relay transport drops."""
    if db is not None:
        return await _apply_relay_offline_db(
            db,
            relay_serial,
            logical_serial=logical_serial,
            hardware_serial=hardware_serial,
        )

    async with AsyncSessionLocal() as session:
        ok = await _apply_relay_offline_db(
            session,
            relay_serial,
            logical_serial=logical_serial,
            hardware_serial=hardware_serial,
        )
        await session.commit()
        return ok


async def _apply_relay_offline_db(
    db: AsyncSession,
    relay_serial: str,
    *,
    logical_serial: Optional[str] = None,
    hardware_serial: Optional[str] = None,
) -> bool:
    device_id = await resolve_device_id_for_relay(
        db,
        relay_serial,
        logical_serial=logical_serial,
        hardware_serial=hardware_serial,
    )
    if not device_id:
        return False

    svc = DeviceStateService()
    current = await svc.get_state(db, device_id)
    if current not in (
        DeviceFsmState.CONNECTING,
        DeviceFsmState.ONLINE,
        DeviceFsmState.BUSY,
    ):
        return False

    ts = int(time.time() * 1000)
    tag = device_id[:8]
    result = await svc.apply_event(
        db,
        device_id,
        event=DeviceFsmEvent.RECONNECTING.value,
        source="agent",
        event_id=f"relay-{tag}-reconnecting-{ts}",
        payload={"relay_serial": relay_serial},
    )
    if result.outcome in (ApplyOutcome.APPLIED, ApplyOutcome.NO_OP):
        log.info(
            "relay FSM offline device=%s relay=%s → %s",
            device_id,
            relay_serial,
            result.state.value,
        )
        return True
    return False
