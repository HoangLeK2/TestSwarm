from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from api.deps import CurrentUser, DB, require_permission
from api.org_scope import data_owner_user_id, device_visible_to_user, resource_visible_to_user
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
    count_group_members_map,
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


async def _group_to_out(db, group, member_count: int | None = None) -> DeviceGroupOut:
    cnt = (
        member_count
        if member_count is not None
        else await count_group_members(db, group.id)
    )
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


async def _get_group_or_404(db, group_id: str, user: CurrentUser):
    group = await get_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Device group not found")
    if not await resource_visible_to_user(
        db,
        user,
        owner_user_id=group.user_id,
        org_id=group.org_id,
    ):
        raise HTTPException(status_code=404, detail="Device group not found")
    return group


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=list[DeviceGroupOut],
    dependencies=[Depends(require_permission("device-groups", "read"))],
)
async def list_device_groups(db: DB, user: CurrentUser):
    """List all device groups for the authenticated user (includes device count)."""
    groups = await list_groups(db, user_id=data_owner_user_id(user))
    counts = await count_group_members_map(db, [g.id for g in groups])
    return [await _group_to_out(db, g, counts.get(g.id, 0)) for g in groups]


@router.post(
    "",
    response_model=DeviceGroupOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("device-groups", "create"))],
)
async def create_device_group(body: DeviceGroupCreate, db: DB, user: CurrentUser):
    group = await create_group(
        db,
        name=body.name,
        description=body.description,
        color=body.color,
        user_id=user.id,
        org_id=getattr(user, "org_id", None),
    )
    await db.commit()
    return await _group_to_out(db, group)


@router.get(
    "/{group_id}",
    response_model=DeviceGroupDetailOut,
    dependencies=[Depends(require_permission("device-groups", "read"))],
)
async def get_device_group(group_id: str, db: DB, user: CurrentUser):
    """Get group with full device list."""
    group = await _get_group_or_404(db, group_id, user)
    return await _group_to_detail_out(db, group)


@router.patch(
    "/{group_id}",
    response_model=DeviceGroupOut,
    dependencies=[Depends(require_permission("device-groups", "update"))],
)
async def update_device_group(
    group_id: str, body: DeviceGroupUpdate, db: DB, user: CurrentUser
):
    group = await _get_group_or_404(db, group_id, user)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if updates:
        await update_group(db, group_id, **updates)
    await db.commit()
    group = await get_group(db, group_id)
    return await _group_to_out(db, group)


@router.delete(
    "/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("device-groups", "delete"))],
)
async def delete_device_group(group_id: str, db: DB, user: CurrentUser):
    """Delete group and all its memberships. Devices themselves are NOT deleted."""
    group = await _get_group_or_404(db, group_id, user)
    await delete_group(db, group_id)
    await db.commit()


@router.post(
    "/{group_id}/devices",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_permission("device-groups", "update"))],
)
async def add_devices(
    group_id: str, body: AddDevicesToGroupBody, db: DB, user: CurrentUser
):
    """Add one or more devices to the group. Already-present devices are ignored."""
    group = await _get_group_or_404(db, group_id, user)
    # Verify each device belongs to the requesting user
    valid_ids: list[str] = []
    for did in body.device_ids:
        device = await repo.get_device(db, did)
        if await device_visible_to_user(db, user, device):
            valid_ids.append(did)
    inserted = await add_devices_to_group(db, group_id, valid_ids, org_id=group.org_id)
    await db.commit()
    return {"group_id": group_id, "added": inserted, "requested": len(body.device_ids)}


@router.delete(
    "/{group_id}/devices/{device_id}",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_permission("device-groups", "update"))],
)
async def remove_device(
    group_id: str, device_id: str, db: DB, user: CurrentUser
):
    """Remove a device from the group. The device itself is NOT deleted."""
    await _get_group_or_404(db, group_id, user)
    await remove_device_from_group(db, group_id, device_id)
    await db.commit()
    return {"ok": True, "group_id": group_id, "device_id": device_id}
