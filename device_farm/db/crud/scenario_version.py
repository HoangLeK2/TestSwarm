"""CRUD helpers for ScenarioVersion — immutable scenario snapshots."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.campaign import Scenario
from db.models.scenario_version import ScenarioVersion


async def create_scenario_version(
    db: AsyncSession, scenario_id: str
) -> ScenarioVersion:
    """Snapshot the current state of a Scenario into a new version row."""
    # Serialize version generation per scenario to avoid max(version)+1 races.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:scenario_id))"),
        {"scenario_id": scenario_id},
    )

    result = await db.execute(
        select(Scenario).where(Scenario.id == scenario_id)
    )
    scenario = result.scalar_one()

    # Determine next version number
    latest = await db.execute(
        select(func.coalesce(func.max(ScenarioVersion.version), 0)).where(
            ScenarioVersion.scenario_id == scenario_id
        )
    )
    next_ver = latest.scalar_one() + 1

    version = ScenarioVersion(
        scenario_id=scenario_id,
        version=next_ver,
        steps=scenario.steps,
        nodes=scenario.nodes,
        edges=scenario.edges,
        variables=scenario.variables,
        instructions=scenario.instructions,
    )
    db.add(version)
    await db.flush()
    return version


async def get_scenario_version(
    db: AsyncSession, version_id: str
) -> Optional[ScenarioVersion]:
    result = await db.execute(
        select(ScenarioVersion).where(ScenarioVersion.id == version_id)
    )
    return result.scalar_one_or_none()


async def list_scenario_versions(
    db: AsyncSession, scenario_id: str
) -> list[ScenarioVersion]:
    result = await db.execute(
        select(ScenarioVersion)
        .where(ScenarioVersion.scenario_id == scenario_id)
        .order_by(ScenarioVersion.version.desc())
    )
    return list(result.scalars().all())
