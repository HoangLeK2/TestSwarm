"""Default scenario per campaign: lowest `order` row in `scenarios`.

Embedded dict shape matches legacy `campaign.scenario` for API clients.
`device_context` is stored under `Scenario.variables` as ``__device_context__``
so it does not collide with template variables.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Scenario

DEVICE_CONTEXT_KEY = "__device_context__"


def scenario_row_to_embedded_dict(s: Scenario) -> dict[str, Any]:
    """{instructions, steps, variables, device_context?} for CampaignOut.scenario."""
    variables = dict(s.variables or {})
    device_context = variables.pop(DEVICE_CONTEXT_KEY, None)
    out: dict[str, Any] = {
        "instructions": s.instructions or "",
        "steps": list(s.steps or []),
        "variables": variables,
        "requirements": dict(getattr(s, "requirements", None) or {}),
    }
    if device_context is not None:
        out["device_context"] = device_context
    return out


def variables_with_device_context(
    variables: dict | None, device_context: Any | None
) -> dict[str, Any]:
    merged = dict(variables or {})
    if device_context is not None:
        merged[DEVICE_CONTEXT_KEY] = device_context
    else:
        merged.pop(DEVICE_CONTEXT_KEY, None)
    return merged


def merge_scenario_variables_for_row(
    existing: dict | None,
    patch_variables: dict | None,
    device_context: Any | None,
) -> dict[str, Any]:
    base = dict(existing or {})
    base.pop(DEVICE_CONTEXT_KEY, None)
    base.update(patch_variables or {})
    return variables_with_device_context(base, device_context)


async def get_default_scenario(db: AsyncSession, campaign_id: str) -> Scenario | None:
    from db.crud.campaign import list_scenarios

    rows = await list_scenarios(db, campaign_id)
    return rows[0] if rows else None


async def ensure_default_scenario(
    db: AsyncSession,
    campaign_id: str,
    *,
    name: str = "Scenario",
) -> Scenario:
    from db.crud.campaign import create_scenario, list_scenarios

    rows = await list_scenarios(db, campaign_id)
    if rows:
        return rows[0]
    return await create_scenario(db, campaign_id, name=name, order=0)
