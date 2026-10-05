"""Resolve campaign scenarios for dispatch/runtime (org library + legacy fallback)."""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.campaign import Campaign


def org_scenario_refs_from_campaign(campaign: Campaign) -> list[dict[str, Any]]:
    """Pinned org-scenario refs on the campaign entity (Epic 04 library path)."""
    from db.crud.campaign_entity import loaded_org_scenario_refs

    refs = loaded_org_scenario_refs(campaign)
    ordered = sorted(refs, key=lambda r: int(r.order_index or 0))
    return [
        {
            "scenario_id": ref.org_scenario_id,
            "scenario_version": int(ref.pinned_version or 1),
            "repeat_count": int(getattr(ref, "repeat_count", 1) or 1),
            "source": "org_library",
        }
        for ref in ordered
    ]


async def resolve_campaign_scenario_refs(
    db: AsyncSession,
    campaign: Campaign,
) -> list[dict[str, Any]]:
    """Org library refs first; fall back to legacy ``scenarios`` rows on the campaign."""
    refs = org_scenario_refs_from_campaign(campaign)
    if refs:
        return refs

    from db.crud import campaign as campaign_repo
    from db.crud.scenario_template import list_templates

    scenarios = await campaign_repo.list_scenarios(db, campaign.id)
    if not scenarios:
        return []

    templates = await list_templates(db)
    by_template_name = {t.name: t for t in templates}
    out: list[dict[str, Any]] = []
    for scen in scenarios:
        has_steps = bool(scen.steps)
        has_template = bool(scen.name and scen.name in by_template_name)
        if not has_steps and not has_template:
            continue
        out.append(
            {
                "scenario_id": scen.id,
                "scenario_version": 1,
                "source": "legacy",
            }
        )
    return out


async def build_campaign_scenario_registry(
    db: AsyncSession,
    *,
    campaign: Campaign,
    org_id: str,
    scenario_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build scenario_registry for Temporal / fallback runtime."""
    if not scenario_refs:
        return {"by_id": {}, "by_campaign_name": {}, "by_template_name": {}}

    if org_scenario_refs_from_campaign(campaign):
        from services.campaign.execution_runtime import build_org_scenario_registry

        return await build_org_scenario_registry(db, org_id, scenario_refs)

    from db.crud import campaign as campaign_repo
    from db.crud.scenario_template import list_templates
    from services.campaign_dispatch import _build_scenario_registry

    scenarios = await campaign_repo.list_scenarios(db, campaign.id)
    ref_ids = {str(r["scenario_id"]) for r in scenario_refs}
    selected = [s for s in scenarios if s.id in ref_ids]
    templates = await list_templates(db)
    return _build_scenario_registry(selected, templates)


# Back-compat alias used across dispatcher / DLQ.
_scenario_refs_from_campaign = org_scenario_refs_from_campaign
