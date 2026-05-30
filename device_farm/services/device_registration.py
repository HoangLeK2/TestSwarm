"""Claim or create a device row by serial (relay / agent flows)."""
from __future__ import annotations

from fastapi import HTTPException

from db import crud as repo
from db.models.device import Device
from sqlalchemy.ext.asyncio import AsyncSession

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
) -> Device:
    """Find device by serial globally, claim unowned rows, or create in ``org_id``."""
    serial = (serial or "").strip()
    ref = await lookup_device_by_serial(db, serial)
    if ref:
        if ref.user_id and ref.user_id != user_id:
            raise DeviceRegistrationError(409, "serial already registered by another user")
        if ref.org_id and org_id and ref.org_id != org_id:
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
        if existing.user_id is None:
            await repo.assign_device_to_user(db, serial, user_id)
        if display_name and display_name != existing.name:
            await repo.update_device_name(db, existing.id, display_name)
        return existing

    if not org_id:
        raise DeviceRegistrationError(400, "organization required")
    return await repo.create_device(db, serial, display_name, user_id, org_id=org_id)


def http_exception_from_registration(err: DeviceRegistrationError) -> HTTPException:
    return HTTPException(status_code=err.status_code, detail=err.detail)
