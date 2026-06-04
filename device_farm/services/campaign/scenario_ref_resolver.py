"""Validate and pin org-scenario refs for campaigns (DF-T-04-006)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.crud import org_scenario as org_scenario_repo
from db.models.enums import OrgScenarioStatus
from tenancy.context import tenant_context


class CampaignScenarioRefError(Exception):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class ScenarioNotFoundForCampaignError(CampaignScenarioRefError):
    def __init__(self) -> None:
        super().__init__("Scenario not found", code="SCENARIO_NOT_FOUND")


class ScenarioVersionNotFoundForCampaignError(CampaignScenarioRefError):
    def __init__(self, scenario_id: str, version: int | Any) -> None:
        super().__init__(
            f"Scenario version {version} not found for scenario {scenario_id}",
            code="SCENARIO_VERSION_NOT_FOUND",
        )
        self.scenario_id = scenario_id
        self.version = version


@dataclass(frozen=True, slots=True)
class ResolvedScenarioRef:
    scenario_id: str
    scenario_version: int
    order_index: int


async def resolve_scenario_refs(
    db: AsyncSession,
    *,
    org_id: str,
    refs: list[dict[str, Any]],
) -> list[ResolvedScenarioRef]:
    """Batch-resolve scenario refs with org ownership and version pinning."""
    if not refs:
        return []

    with tenant_context(org_id):
        return await _resolve_scenario_refs_in_tenant(db, org_id=org_id, refs=refs)


async def _resolve_scenario_refs_in_tenant(
    db: AsyncSession,
    *,
    org_id: str,
    refs: list[dict[str, Any]],
) -> list[ResolvedScenarioRef]:
    unique_ids = sorted(
        {
            str(ref.get("scenario_id") or "").strip()
            for ref in refs
            if str(ref.get("scenario_id") or "").strip()
        }
    )
    if len(unique_ids) < len(refs):
        raise CampaignScenarioRefError("scenario_id is required", code="INVALID_SCENARIO_REF")

    rows = await org_scenario_repo.get_org_scenario_meta_by_ids(db, org_id, unique_ids)
    by_id: dict[str, tuple[str, int]] = {
        row_id: (status, version) for row_id, status, version in rows
    }

    resolved: list[ResolvedScenarioRef] = []
    for order_index, ref in enumerate(refs):
        scenario_id = str(ref.get("scenario_id") or "").strip()
        if not scenario_id:
            raise CampaignScenarioRefError("scenario_id is required", code="INVALID_SCENARIO_REF")
        row = by_id.get(scenario_id)
        if row is None:
            raise ScenarioNotFoundForCampaignError()
        status, current_version = row
        if status == OrgScenarioStatus.ARCHIVED.value:
            raise ScenarioNotFoundForCampaignError()

        raw_version = ref.get("scenario_version")
        if raw_version is None:
            pinned = int(current_version or 1)
        else:
            try:
                pinned = int(raw_version)
            except (TypeError, ValueError) as exc:
                raise ScenarioVersionNotFoundForCampaignError(scenario_id, raw_version) from exc
            if pinned < 1 or pinned > int(current_version or 1):
                raise ScenarioVersionNotFoundForCampaignError(scenario_id, pinned)

        resolved.append(
            ResolvedScenarioRef(
                scenario_id=scenario_id,
                scenario_version=pinned,
                order_index=order_index,
            )
        )
    return resolved
