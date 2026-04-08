from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from api.deps import CurrentUser, DB
from api.schemas.device import DeviceOut
from api.schemas.device_group import (
    AddDevicesToGroupBody,
    DeviceGroupCreate,
    DeviceGroupDetailOut,
    DeviceGroupOut,
    DeviceGroupUpdate,
)
from db.crud.device_group import (
    add_devices_to_group,
    count_group_members,
    create_group,
    delete_group,
    get_group,
    list_group_devices,
    list_groups,
    remove_device_from_group,
    update_group,
)
from db import crud as repo

router = APIRouter(prefix="/device-groups", tags=["device-groups"])


def _device_to_out(d) -> DeviceOut:
    return DeviceOut(
        id=d.id, serial=d.serial, name=d.name,
        device_key=d.device_key, user_id=d.user_id,
        brand=d.brand, model=d.model,
        android_version=d.android_version, sdk_version=d.sdk_version,
        screen_width=d.screen_width, screen_height=d.screen_height,
        last_seen=d.last_seen, created_at=d.created_at,
        adb_ip=getattr(d, "adb_ip", None),
        adb_port=getattr(d, "adb_port", 5555),
        tags=getattr(d, "tags", "") or "",
    )


async def _group_to_out(db, group) -> DeviceGroupOut:
    cnt = await count_group_members(db, group.id)
    return DeviceGroupOut(
        id=group.id,
        name=group.name,
        description=group.description or "",
        color=group.color or "#6366f1",
        user_id=group.user_id,
        device_count=cnt,
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


async def _group_to_detail_out(db, group) -> DeviceGroupDetailOut:
    devices = await list_group_devices(db, group.id)
    return DeviceGroupDetailOut(
        id=group.id,
        name=group.name,
        description=group.description or "",
        color=group.color or "#6366f1",
        user_id=group.user_id,
        device_count=len(devices),
        created_at=group.created_at,
        updated_at=group.updated_at,
        devices=[_device_to_out(d) for d in devices],
    )


async def _get_group_or_404(group_id: str, user_id: str, db):
    group = await get_group(db, group_id)
    if not group or group.user_id != user_id:
        raise HTTPException(status_code=404, detail="Device group not found")
    return group


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("", response_model=list[DeviceGroupOut])
async def list_device_groups(db: DB, user: CurrentUser):
    """List all device groups for the authenticated user (includes device count)."""
    groups = await list_groups(db, user_id=user.id)
    return [await _group_to_out(db, g) for g in groups]


@router.post("", response_model=DeviceGroupOut, status_code=status.HTTP_201_CREATED)
async def create_device_group(body: DeviceGroupCreate, db: DB, user: CurrentUser):
    group = await create_group(
        db,
        name=body.name,
        description=body.description,
        color=body.color,
        user_id=user.id,
    )
    await db.commit()
    return await _group_to_out(db, group)


@router.get("/{group_id}", response_model=DeviceGroupDetailOut)
async def get_device_group(group_id: str, db: DB, user: CurrentUser):
    """Get group with full device list."""
    group = await _get_group_or_404(group_id, user.id, db)
    return await _group_to_detail_out(db, group)


@router.patch("/{group_id}", response_model=DeviceGroupOut)
async def update_device_group(
    group_id: str, body: DeviceGroupUpdate, db: DB, user: CurrentUser
):
    group = await _get_group_or_404(group_id, user.id, db)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if updates:
        await update_group(db, group_id, **updates)
    await db.commit()
    group = await get_group(db, group_id)
    return await _group_to_out(db, group)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device_group(group_id: str, db: DB, user: CurrentUser):
    """Delete group and all its memberships. Devices themselves are NOT deleted."""
    await _get_group_or_404(group_id, user.id, db)
    await delete_group(db, group_id)
    await db.commit()


@router.post("/{group_id}/devices", status_code=status.HTTP_200_OK)
async def add_devices(
    group_id: str, body: AddDevicesToGroupBody, db: DB, user: CurrentUser
):
    """Add one or more devices to the group. Already-present devices are ignored."""
    await _get_group_or_404(group_id, user.id, db)
    # Verify each device belongs to the requesting user
    valid_ids: list[str] = []
    for did in body.device_ids:
        device = await repo.get_device(db, did)
        if device and device.user_id == user.id:
            valid_ids.append(did)
    inserted = await add_devices_to_group(db, group_id, valid_ids)
    await db.commit()
    return {"group_id": group_id, "added": inserted, "requested": len(body.device_ids)}


@router.delete("/{group_id}/devices/{device_id}", status_code=status.HTTP_200_OK)
async def remove_device(
    group_id: str, device_id: str, db: DB, user: CurrentUser
):
    """Remove a device from the group. The device itself is NOT deleted."""
    await _get_group_or_404(group_id, user.id, db)
    await remove_device_from_group(db, group_id, device_id)
    await db.commit()
    return {"ok": True, "group_id": group_id, "device_id": device_id}
