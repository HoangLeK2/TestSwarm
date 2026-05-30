from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.campaign import Campaign
from db.models.device import Device
from db.models.execution import Execution
from db.models.execution_dlq import ExecutionDLQ
from services.device_liveness import list_stale_offline_devices
from tenancy.context import get_current_org_id, tenant_context


async def _pending_dlq_org_ids_for_user(
    db: AsyncSession,
    *,
    user_id: str,
    campaign_id: str | None,
) -> list[str]:
    dlq = ExecutionDLQ.__table__
    execution = Execution.__table__
    device = Device.__table__
    q = (
        select(device.c.org_id)
        .select_from(
            dlq.join(execution, execution.c.id == dlq.c.execution_id)
            .join(device, device.c.serial == dlq.c.device_serial)
        )
        .where(
            execution.c.user_id == user_id,
            device.c.user_id == user_id,
            dlq.c.status == "pending",
            device.c.org_id.isnot(None),
        )
        .distinct()
    )
    if campaign_id is not None:
        q = q.where(execution.c.campaign_id == campaign_id)

    rows = (await db.execute(q)).all()
    return [row[0] for row in rows if row[0]]


async def dismiss_stale_offline_dlq_entries_for_user(
    db: AsyncSession,
    *,
    user_id: str,
    offline_after_minutes: int,
    campaign_id: str | None = None,
    manager=None,
) -> int:
    if get_current_org_id() is None:
        total = 0
        for org_id in await _pending_dlq_org_ids_for_user(
            db,
            user_id=user_id,
            campaign_id=campaign_id,
        ):
            with tenant_context(org_id):
                total += await dismiss_stale_offline_dlq_entries_for_user(
                    db,
                    user_id=user_id,
                    offline_after_minutes=offline_after_minutes,
                    campaign_id=campaign_id,
                    manager=manager,
                )
        return total

    org_id = get_current_org_id()
    q = (
        select(ExecutionDLQ.id, Device)
        .join(Execution, Execution.id == ExecutionDLQ.execution_id)
        .join(Device, Device.serial == ExecutionDLQ.device_serial)
        .where(ExecutionDLQ.status == "pending")
    )
    if org_id:
        q = q.where(Device.org_id == org_id).join(
            Campaign, Execution.campaign_id == Campaign.id
        ).where(Campaign.org_id == org_id)
    else:
        q = q.where(Execution.user_id == user_id, Device.user_id == user_id)
    if campaign_id is not None:
        q = q.where(Execution.campaign_id == campaign_id)

    rows = (await db.execute(q)).all()
    if not rows:
        return 0

    device_by_dlq_id = {dlq_id: device for dlq_id, device in rows}
    stale_devices = await list_stale_offline_devices(
        db,
        device_by_dlq_id.values(),
        offline_after_minutes=offline_after_minutes,
        manager=manager,
    )
    stale_serials = {device.serial for device in stale_devices}
    stale_ids = [
        dlq_id
        for dlq_id, device in device_by_dlq_id.items()
        if device.serial in stale_serials
    ]
    if not stale_ids:
        return 0

    await db.execute(
        update(ExecutionDLQ)
        .where(ExecutionDLQ.id.in_(stale_ids))
        .values(status="dismissed")
    )
    await db.flush()
    return len(stale_ids)


async def dismiss_stale_offline_dlq_all_users(
    db: AsyncSession,
    *,
    offline_after_minutes: int,
    manager=None,
) -> int:
    """Dismiss pending DLQ rows for stale offline devices across all tenants."""
    result = await db.execute(
        select(Execution.user_id)
        .join(ExecutionDLQ, ExecutionDLQ.execution_id == Execution.id)
        .where(ExecutionDLQ.status == "pending", Execution.user_id.isnot(None))
        .distinct()
    )
    user_ids = [row[0] for row in result.all() if row[0]]
    total = 0
    for user_id in user_ids:
        total += await dismiss_stale_offline_dlq_entries_for_user(
            db,
            user_id=user_id,
            offline_after_minutes=offline_after_minutes,
            manager=manager,
        )
    if total:
        await db.commit()
    return total
