from __future__ import annotations

import inspect
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.scenario_device_variable import (
    CampaignOrgScenarioDeviceVariable,
    ScenarioDeviceVariable,
)


async def get_scenario_device_variables_bulk(
    db: AsyncSession,
    scenario_ids: list[str],
    device_ids: list[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Load all (scenario_id, device_id) variable maps in one query."""
    if not scenario_ids or not device_ids:
        return {}
    result = await db.execute(
        select(ScenarioDeviceVariable).where(
            ScenarioDeviceVariable.scenario_id.in_(scenario_ids),
            ScenarioDeviceVariable.device_id.in_(device_ids),
        )
    )
    scalars = result.scalars()
    if inspect.isawaitable(scalars):
        scalars = await scalars
    rows = scalars.all()
    if inspect.isawaitable(rows):
        rows = await rows
    return {
        (row.scenario_id, row.device_id): dict(row.vars or {})
        for row in rows
    }


async def get_scenario_device_variables(
    db: AsyncSession,
    scenario_id: str,
    device_id: str,
) -> dict[str, Any]:
    row = await db.get(
        ScenarioDeviceVariable,
        {"scenario_id": scenario_id, "device_id": device_id},
    )
    if row is None or not isinstance(row, ScenarioDeviceVariable):
        return {}
    return dict(row.vars or {})


async def replace_scenario_device_variables(
    db: AsyncSession,
    scenario_id: str,
    device_id: str,
    vars_map: dict[str, Any],
) -> dict[str, Any]:
    row = await db.get(
        ScenarioDeviceVariable,
        {"scenario_id": scenario_id, "device_id": device_id},
    )
    if row is None:
        row = ScenarioDeviceVariable(
            scenario_id=scenario_id,
            device_id=device_id,
            vars=dict(vars_map or {}),
        )
        db.add(row)
        await db.flush()
        return dict(row.vars)
    row.vars = dict(vars_map or {})
    await db.flush()
    return dict(row.vars)


async def merge_scenario_device_variables(
    db: AsyncSession,
    scenario_id: str,
    device_id: str,
    partial_vars: dict[str, Any],
) -> dict[str, Any]:
    row = await db.get(
        ScenarioDeviceVariable,
        {"scenario_id": scenario_id, "device_id": device_id},
    )
    if row is None:
        row = ScenarioDeviceVariable(
            scenario_id=scenario_id,
            device_id=device_id,
            vars={},
        )
        db.add(row)
        await db.flush()
    merged = dict(row.vars or {})
    merged.update(partial_vars or {})
    row.vars = merged
    await db.flush()
    return dict(row.vars)


async def delete_scenario_device_variable_key(
    db: AsyncSession,
    scenario_id: str,
    device_id: str,
    key: str,
) -> bool:
    row = await db.get(
        ScenarioDeviceVariable,
        {"scenario_id": scenario_id, "device_id": device_id},
    )
    if row is None:
        return False
    vars_map = dict(row.vars or {})
    if key not in vars_map:
        return False
    vars_map.pop(key, None)
    if vars_map:
        row.vars = vars_map
        await db.flush()
    else:
        await db.execute(
            delete(ScenarioDeviceVariable).where(
                ScenarioDeviceVariable.scenario_id == scenario_id,
                ScenarioDeviceVariable.device_id == device_id,
            )
        )
    return True


async def get_campaign_org_scenario_device_variables_bulk(
    db: AsyncSession,
    campaign_id: str,
    org_scenario_ids: list[str],
    device_ids: list[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Load all campaign-scoped org-scenario variable maps.

    Returns ``{(org_scenario_id, device_id): vars}`` for one campaign.
    """
    if not campaign_id or not org_scenario_ids or not device_ids:
        return {}
    result = await db.execute(
        select(CampaignOrgScenarioDeviceVariable).where(
            CampaignOrgScenarioDeviceVariable.campaign_id == campaign_id,
            CampaignOrgScenarioDeviceVariable.org_scenario_id.in_(org_scenario_ids),
            CampaignOrgScenarioDeviceVariable.device_id.in_(device_ids),
        )
    )
    rows = result.scalars().all()
    return {
        (row.org_scenario_id, row.device_id): dict(row.vars or {})
        for row in rows
    }


async def get_campaign_org_scenario_device_variables(
    db: AsyncSession,
    campaign_id: str,
    org_scenario_id: str,
    device_id: str,
) -> dict[str, Any]:
    row = await db.get(
        CampaignOrgScenarioDeviceVariable,
        {
            "campaign_id": campaign_id,
            "org_scenario_id": org_scenario_id,
            "device_id": device_id,
        },
    )
    if row is None or not isinstance(row, CampaignOrgScenarioDeviceVariable):
        return {}
    return dict(row.vars or {})


async def replace_campaign_org_scenario_device_variables(
    db: AsyncSession,
    campaign_id: str,
    org_scenario_id: str,
    device_id: str,
    vars_map: dict[str, Any],
) -> dict[str, Any]:
    row = await db.get(
        CampaignOrgScenarioDeviceVariable,
        {
            "campaign_id": campaign_id,
            "org_scenario_id": org_scenario_id,
            "device_id": device_id,
        },
    )
    if row is None:
        row = CampaignOrgScenarioDeviceVariable(
            campaign_id=campaign_id,
            org_scenario_id=org_scenario_id,
            device_id=device_id,
            vars=dict(vars_map or {}),
        )
        db.add(row)
        await db.flush()
        return dict(row.vars)
    row.vars = dict(vars_map or {})
    await db.flush()
    return dict(row.vars)


async def merge_campaign_org_scenario_device_variables(
    db: AsyncSession,
    campaign_id: str,
    org_scenario_id: str,
    device_id: str,
    partial_vars: dict[str, Any],
) -> dict[str, Any]:
    row = await db.get(
        CampaignOrgScenarioDeviceVariable,
        {
            "campaign_id": campaign_id,
            "org_scenario_id": org_scenario_id,
            "device_id": device_id,
        },
    )
    if row is None:
        row = CampaignOrgScenarioDeviceVariable(
            campaign_id=campaign_id,
            org_scenario_id=org_scenario_id,
            device_id=device_id,
            vars={},
        )
        db.add(row)
        await db.flush()
    merged = dict(row.vars or {})
    merged.update(partial_vars or {})
    row.vars = merged
    await db.flush()
    return dict(row.vars)


async def delete_campaign_org_scenario_device_variable_key(
    db: AsyncSession,
    campaign_id: str,
    org_scenario_id: str,
    device_id: str,
    key: str,
) -> bool:
    row = await db.get(
        CampaignOrgScenarioDeviceVariable,
        {
            "campaign_id": campaign_id,
            "org_scenario_id": org_scenario_id,
            "device_id": device_id,
        },
    )
    if row is None:
        return False
    vars_map = dict(row.vars or {})
    if key not in vars_map:
        return False
    vars_map.pop(key, None)
    if vars_map:
        row.vars = vars_map
        await db.flush()
    else:
        await db.execute(
            delete(CampaignOrgScenarioDeviceVariable).where(
                CampaignOrgScenarioDeviceVariable.campaign_id == campaign_id,
                CampaignOrgScenarioDeviceVariable.org_scenario_id == org_scenario_id,
                CampaignOrgScenarioDeviceVariable.device_id == device_id,
            )
        )
    return True
