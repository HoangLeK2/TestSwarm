"""Device pool allocation lifecycle helpers."""
from __future__ import annotations

import hashlib
import hmac
import secrets

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from core.env import secret_key_optional
from db.crud.session import close_active_sessions_for_device
from db.models import (
    Account,
    Campaign,
    CampaignDevice,
    CampaignOrgScenarioDeviceVariable,
    DeviceAccount,
    DeviceGroupMember,
    DeviceTargetGroup,
    Scenario,
    ScenarioDeviceVariable,
)
from db.models.device import Device
from db.models.device_key import DeviceKey
from db.models.enums import DeviceRegistryStatus
from db.models.utils import _now
from services.security_audit import emit_security_event
from tenancy.context import tenant_context


def _key_history_hash(raw_key: str) -> str:
    secret = secret_key_optional()
    if secret:
        digest = hmac.new(
            secret.encode("utf-8"),
            raw_key.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"hmac-sha256:{digest}"
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


async def rotate_device_key(db: AsyncSession, device: Device) -> str:
    """Rotate the connect key and revoke previous key records for this device."""
    raw_key = secrets.token_urlsafe(32)
    now = _now()
    await db.execute(
        update(DeviceKey)
        .where(DeviceKey.device_id == device.id)
        .where(DeviceKey.status == "active")
        .values(status="revoked", revoked_at=now)
    )
    device.device_key = raw_key
    next_version = int(
        (
            await db.execute(
                select(func.coalesce(func.max(DeviceKey.version), 0)).where(
                    DeviceKey.device_id == device.id
                )
            )
        ).scalar_one()
        or 0
    ) + 1
    db.add(
        DeviceKey(
            device_id=device.id,
            key_hash=_key_history_hash(raw_key),
            version=next_version,
            status="active",
            created_at=now,
        )
    )
    device.updated_at = now
    return raw_key


def _without_device_key(value: dict | None, device_id: str) -> tuple[dict | None, bool]:
    if not isinstance(value, dict) or device_id not in value:
        return value, False
    next_value = dict(value)
    next_value.pop(device_id, None)
    return next_value, True


async def cleanup_device_workspace_bindings(
    db: AsyncSession,
    *,
    device_id: str,
    workspace_id: str | None,
) -> dict[str, int]:
    """Remove workspace-scoped operational links before a pool phone leaves it."""
    if not workspace_id:
        return {}

    campaign_ids = select(Campaign.id).where(Campaign.org_id == workspace_id)
    scenario_ids = select(Scenario.id).where(Scenario.campaign_id.in_(campaign_ids))
    account_ids = select(Account.id).where(Account.org_id == workspace_id)

    counts: dict[str, int] = {}
    statements = (
        (
            "campaign_devices",
            delete(CampaignDevice)
            .where(CampaignDevice.device_id == device_id)
            .where(CampaignDevice.campaign_id.in_(campaign_ids)),
        ),
        (
            "device_group_members",
            delete(DeviceGroupMember)
            .where(DeviceGroupMember.org_id == workspace_id)
            .where(DeviceGroupMember.device_id == device_id),
        ),
        (
            "device_accounts",
            delete(DeviceAccount)
            .where(DeviceAccount.device_id == device_id)
            .where(DeviceAccount.account_id.in_(account_ids)),
        ),
        (
            "device_target_groups",
            delete(DeviceTargetGroup)
            .where(DeviceTargetGroup.org_id == workspace_id)
            .where(DeviceTargetGroup.device_id == device_id),
        ),
        (
            "scenario_device_variables",
            delete(ScenarioDeviceVariable)
            .where(ScenarioDeviceVariable.device_id == device_id)
            .where(ScenarioDeviceVariable.scenario_id.in_(scenario_ids)),
        ),
        (
            "campaign_org_scenario_device_variables",
            delete(CampaignOrgScenarioDeviceVariable)
            .where(CampaignOrgScenarioDeviceVariable.device_id == device_id)
            .where(CampaignOrgScenarioDeviceVariable.campaign_id.in_(campaign_ids)),
        ),
    )
    for key, stmt in statements:
        result = await db.execute(stmt)
        counts[key] = int(result.rowcount or 0)

    with tenant_context(workspace_id):
        campaigns = (
            await db.execute(
                select(Campaign).where(Campaign.org_id == workspace_id)
            )
        ).scalars().all()
    cleaned_json = 0
    now = _now()
    for campaign in campaigns:
        changed = False
        per_device_overrides, removed = _without_device_key(
            campaign.per_device_overrides,
            device_id,
        )
        if removed:
            campaign.per_device_overrides = per_device_overrides or {}
            flag_modified(campaign, "per_device_overrides")
            changed = True
        per_device_accounts, removed = _without_device_key(
            campaign.per_device_accounts,
            device_id,
        )
        if removed:
            campaign.per_device_accounts = per_device_accounts or {}
            flag_modified(campaign, "per_device_accounts")
            changed = True
        if changed:
            campaign.updated_at = now
            cleaned_json += 1
    counts["campaign_device_settings"] = cleaned_json
    return counts


async def mark_allocated_unclaimed(
    db: AsyncSession,
    device: Device,
    *,
    target_org_id: str,
    manager_org_id: str,
    relay_id: str,
    flush: bool = True,
) -> Device:
    """Assign pool visibility to a workspace.

    The first hand-off of a pool phone still needs a workspace user to claim it
    so the phone gets an initial connect key. Once a phone has been paired at
    least once, later returns to the same allocation flow should not make the
    operator register it again; the managed agent can push a fresh key when the
    user clicks Connect.
    """
    old_org_id = device.org_id
    was_previously_paired = bool(device.paired_at)
    should_cleanup = bool(device.user_id) or bool(
        old_org_id and old_org_id != target_org_id
    )
    if should_cleanup:
        await close_active_sessions_for_device(db, device.id)
        await cleanup_device_workspace_bindings(
            db,
            device_id=device.id,
            workspace_id=old_org_id,
        )
    device.org_id = target_org_id
    device.user_id = None
    device.managed_by_org_id = manager_org_id
    device.managed_by_relay_id = relay_id
    device.relay_serial = device.relay_serial or device.serial
    if was_previously_paired:
        device.status = DeviceRegistryStatus.PAIRED.value
        device.unpaired_at = None
    else:
        device.status = DeviceRegistryStatus.UNPAIRED.value
        device.unpaired_at = _now()
    await rotate_device_key(db, device)
    if flush:
        await db.flush()
    return device


async def claim_allocated_device(
    db: AsyncSession,
    device: Device,
    *,
    actor_user_id: str,
    org_id: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> Device:
    """Register an allocated device for the current workspace user."""
    if device.org_id != org_id:
        raise ValueError("DEVICE_NOT_IN_WORKSPACE")
    if device.user_id and device.user_id != actor_user_id:
        raise ValueError("DEVICE_ALREADY_REGISTERED")
    device.user_id = actor_user_id
    device.status = DeviceRegistryStatus.PAIRED.value
    device.unpaired_at = None
    if not device.paired_at:
        device.paired_at = _now()
    await rotate_device_key(db, device)
    await db.flush()
    await emit_security_event(
        db,
        action="device.claimed",
        user_id=actor_user_id,
        org_id=org_id,
        entity_type="device",
        entity_id=device.id,
        ip_address=ip_address,
        user_agent=user_agent,
        details={
            "device_serial": device.device_serial or device.serial,
            "managed_by_workspace_id": device.managed_by_org_id,
            "managed_by_relay_id": device.managed_by_relay_id,
        },
    )
    return device


async def release_allocated_device(
    db: AsyncSession,
    device: Device,
    *,
    actor_user_id: str,
    return_org_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    action: str = "device.released",
) -> Device:
    """Remove workspace-user rights without deleting the physical phone pool row."""
    old_org_id = device.org_id
    await close_active_sessions_for_device(db, device.id)
    cleanup_counts = await cleanup_device_workspace_bindings(
        db,
        device_id=device.id,
        workspace_id=old_org_id,
    )
    device.user_id = None
    device.status = DeviceRegistryStatus.UNPAIRED.value
    device.unpaired_at = _now()
    if return_org_id:
        device.org_id = return_org_id
    await rotate_device_key(db, device)
    await db.flush()
    await emit_security_event(
        db,
        action=action,
        user_id=actor_user_id,
        org_id=device.org_id or old_org_id,
        entity_type="device",
        entity_id=device.id,
        ip_address=ip_address,
        user_agent=user_agent,
        details={
            "from_workspace_id": old_org_id,
            "to_workspace_id": device.org_id,
            "managed_by_workspace_id": device.managed_by_org_id,
            "managed_by_relay_id": device.managed_by_relay_id,
            "cleanup": cleanup_counts,
        },
    )
    return device


async def move_device_to_workspace(
    db: AsyncSession,
    device: Device,
    *,
    target_org_id: str,
    clear_user: bool = True,
) -> dict[str, int]:
    """Move a device between workspaces and invalidate old workspace access."""
    old_org_id = device.org_id
    if old_org_id == target_org_id and not clear_user:
        return {}

    cleanup_counts: dict[str, int] = {}
    if old_org_id and old_org_id != target_org_id:
        await close_active_sessions_for_device(db, device.id)
        cleanup_counts = await cleanup_device_workspace_bindings(
            db,
            device_id=device.id,
            workspace_id=old_org_id,
        )
    device.org_id = target_org_id
    if clear_user:
        device.user_id = None
        device.status = DeviceRegistryStatus.UNPAIRED.value
        device.unpaired_at = _now()
    await rotate_device_key(db, device)
    await db.flush()
    return cleanup_counts
