"""Campaign account bind/unbind service (DF-T-04-009)."""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.crud import campaign_entity as repo
from db.models.campaign import Campaign
from db.models.enums import CampaignStatus
from services.campaign.account_resolver import (
    AccountBindingError,
    validate_bind_payload,
)
from services.campaign.override_resolver import validate_per_device_accounts_size
from services.campaign.events import emit_campaign_domain_event
from services.campaign.errors import CampaignNotFoundError


async def bind_campaign_accounts(
    db: AsyncSession,
    *,
    org_id: str,
    campaign_id: str,
    user_id: str | None,
    account_group_id: str | None = None,
    scenario_account_id: str | None = None,
    per_device_accounts: dict[str, str] | None = None,
) -> Campaign:
    row = await repo.get_campaign_entity(db, campaign_id)
    if row is None or row.org_id != org_id or row.status == CampaignStatus.ARCHIVED.value:
        raise CampaignNotFoundError()

    per_map = {str(k): str(v) for k, v in (per_device_accounts or {}).items() if v}
    try:
        validate_per_device_accounts_size(per_map)
    except ValueError as exc:
        raise AccountBindingError(str(exc), code=getattr(exc, "code", "INVALID_BIND_PAYLOAD")) from exc
    await validate_bind_payload(
        db,
        org_id=org_id,
        account_group_id=account_group_id,
        scenario_account_id=scenario_account_id,
        per_device_accounts=per_map or None,
    )

    row.account_group_id = account_group_id or None
    row.scenario_account_id = scenario_account_id or None
    row.per_device_accounts = per_map
    await db.flush()

    audit_targets: list[dict[str, Any]] = []
    if account_group_id:
        audit_targets.append({"kind": "account_group", "target_id": account_group_id})
    if scenario_account_id:
        audit_targets.append({"kind": "account", "target_account": scenario_account_id})
    if len(per_map) > 50:
        audit_targets.append(
            {
                "kind": "per_device_bulk",
                "device_count": len(per_map),
                "account_ids": sorted(set(per_map.values())),
            }
        )
    else:
        for device_id, account_id in per_map.items():
            audit_targets.append(
                {"kind": "per_device", "device_id": device_id, "target_account": account_id}
            )

    for target in audit_targets:
        await emit_campaign_domain_event(
            db,
            event="account.bound",
            org_id=org_id,
            campaign_id=row.id,
            user_id=user_id,
            details=target,
        )

    return row


async def clear_campaign_accounts(
    db: AsyncSession,
    *,
    org_id: str,
    campaign_id: str,
    user_id: str | None,
) -> Campaign:
    row = await repo.get_campaign_entity(db, campaign_id)
    if row is None or row.org_id != org_id or row.status == CampaignStatus.ARCHIVED.value:
        raise CampaignNotFoundError()

    row.account_group_id = None
    row.scenario_account_id = None
    row.per_device_accounts = {}
    await db.flush()

    await emit_campaign_domain_event(
        db,
        event="account.unbound",
        org_id=org_id,
        campaign_id=row.id,
        user_id=user_id,
    )
    return row
