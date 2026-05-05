from __future__ import annotations

from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.scenario_device_variable import ScenarioDeviceVariable


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

