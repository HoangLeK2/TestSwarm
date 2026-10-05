"""Claim or create a device row by serial (relay / agent flows)."""
from __future__ import annotations

from fastapi import HTTPException

from db import crud as repo
from db.models.device import Device
from db.models.enums import DeviceRegistryStatus
from db.models.utils import _now
from sqlalchemy.ext.asyncio import AsyncSession

from services.device_allocation import move_device_to_workspace
from tenancy.background import ensure_device_org_id, lookup_device_by_serial
from tenancy.context import tenant_context


class DeviceRegistrationError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


async def get_or_claim_device_for_user(
    db: AsyncSession,
    *,
    serial: str,
    display_name: str,
    user_id: str,
    org_id: str | None,
    allow_relay_reclaim: bool = False,
    preserve_existing_name: bool = False,
) -> Device:
    """Find device by serial globally, claim unowned rows, or create in ``org_id``."""
    serial = (serial or "").strip()
    ref = await lookup_device_by_serial(db, serial)
    if ref:
        managed_by_current_org = bool(org_id and ref.managed_by_org_id == org_id)
        reclaiming_via_relay = bool(allow_relay_reclaim and org_id)
        if (
            ref.user_id
            and ref.user_id != user_id
            and not managed_by_current_org
            and not reclaiming_via_relay
        ):
            raise DeviceRegistrationError(409, "serial already registered by another user")
        if (
            ref.org_id
            and org_id
            and ref.org_id != org_id
            and not managed_by_current_org
            and not reclaiming_via_relay
        ):
            raise DeviceRegistrationError(
                409, "serial already registered by another organization"
            )
        work_org = ref.org_id or org_id
        if not work_org:
            raise DeviceRegistrationError(400, "organization required")
        if ref.org_id is None:
            await ensure_device_org_id(db, ref.device_id, work_org)
            await db.flush()
        with tenant_context(work_org):
            existing = await repo.get_device(db, ref.device_id)
            if existing is None:
                existing = await repo.get_device_by_serial(db, serial)
        if existing is None:
            raise DeviceRegistrationError(500, "device lookup failed")
        if (managed_by_current_org or reclaiming_via_relay) and org_id and existing.org_id != org_id:
            await move_device_to_workspace(
                db,
                existing,
                target_org_id=org_id,
                clear_user=True,
            )
        if org_id and (existing.managed_by_org_id is None or reclaiming_via_relay):
            existing.managed_by_org_id = org_id
        if existing.user_id is None or (
            (managed_by_current_org or reclaiming_via_relay)
            and existing.user_id != user_id
        ):
            existing.user_id = user_id
        existing.status = DeviceRegistryStatus.PAIRED.value
        existing.unpaired_at = None
        if not existing.paired_at:
            existing.paired_at = _now()
        current_name = str(existing.name or "").strip()
        should_update_name = bool(display_name and display_name != existing.name)
        if preserve_existing_name and current_name:
            should_update_name = False
        if should_update_name:
            await repo.update_device_name(db, existing.id, display_name)
        return existing

    if not org_id:
        raise DeviceRegistrationError(400, "organization required")
    device = await repo.create_device(db, serial, display_name, user_id, org_id=org_id)
    device.managed_by_org_id = org_id
    return device


def http_exception_from_registration(err: DeviceRegistrationError) -> HTTPException:
    return HTTPException(status_code=err.status_code, detail=err.detail)


async def claim_relay_reported_serials(
    db: AsyncSession,
    *,
    serials: list[str],
    user_id: str,
    org_id: str,
    relay_id: str,
) -> list[str]:
    """Claim every physical serial reported by an authenticated relay token."""
    claimed: list[str] = []
    seen: set[str] = set()
    for raw_serial in serials or []:
        serial = str(raw_serial or "").strip()
        if not serial or serial.startswith("pending-") or serial in seen:
            continue
        seen.add(serial)
        ref = await lookup_device_by_serial(db, serial)
        allocated_by_current_manager = bool(
            ref
            and ref.managed_by_org_id == org_id
            and ref.org_id
            and ref.org_id != org_id
        )
        if allocated_by_current_manager:
            with tenant_context(ref.org_id):
                device = await repo.get_device(db, ref.device_id)
            if device is None:
                raise DeviceRegistrationError(500, "device lookup failed")
        else:
            device = await get_or_claim_device_for_user(
                db,
                serial=serial,
                display_name=serial,
                user_id=user_id,
                org_id=org_id,
                allow_relay_reclaim=True,
                preserve_existing_name=True,
            )
        device.managed_by_org_id = org_id
        device.managed_by_relay_id = relay_id
        device.relay_serial = serial
        claimed.append(str(getattr(device, "serial", "") or serial))
    return claimed
