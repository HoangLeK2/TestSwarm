"""Resolve run_scenario name dependencies during import (DF-T-04-005)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.crud import org_scenario as repo
from db.models.enums import ScenarioKind
from services.org_scenario_io.ref_utils import collect_run_scenario_names, rewrite_run_scenario_refs_for_import


def _names_lower(names: set[str]) -> list[str]:
    return sorted({n.strip().lower() for n in names if n.strip()})


async def resolve_dependency_names(
    db: AsyncSession,
    *,
    org_id: str,
    body: dict[str, Any],
    kind: str,
) -> tuple[list[str], dict[str, str]]:
    """Single batch lookup for import dependency names."""
    required = collect_run_scenario_names(body, kind)
    if not required:
        return [], {}
    rows = await repo.find_by_org_and_names_lower(db, org_id, _names_lower(required))
    mapping: dict[str, str] = {}
    for row in rows.values():
        mapping[row.name_lower] = row.id
        mapping[row.name] = row.id
    missing = [name for name in sorted(required) if name.strip().lower() not in rows]
    return missing, mapping


async def create_stub_scenarios(
    db: AsyncSession,
    *,
    org_id: str,
    names: list[str],
    created_by: str | None,
) -> dict[str, str]:
    """Create empty draft scenarios for missing dependency names."""
    if not names:
        return {}
    name_to_id: dict[str, str] = {}
    existing_rows = await repo.find_by_org_and_names_lower(db, org_id, _names_lower(set(names)))
    pending: list[str] = []
    for raw in names:
        name = raw.strip()
        if not name:
            continue
        row = existing_rows.get(name.lower())
        if row is not None:
            name_to_id[name.lower()] = row.id
            name_to_id[name] = row.id
            continue
        pending.append(name)
    for name in pending:
        row = await repo.create_org_scenario(
            db,
            org_id=org_id,
            name=name,
            kind=ScenarioKind.SEQUENCE.value,
            description="Auto-created stub for import dependency",
            body_json={"steps": []},
            created_by=created_by,
        )
        name_to_id[name.lower()] = row.id
        name_to_id[name] = row.id
    return name_to_id


def resolve_import_body(
    body: dict[str, Any],
    kind: str,
    *,
    name_to_id: dict[str, str],
) -> dict[str, Any]:
    return rewrite_run_scenario_refs_for_import(body, kind, name_to_id=name_to_id)
