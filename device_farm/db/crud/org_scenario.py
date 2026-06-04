"""CRUD for org-scoped scenario library (DF-T-04-001)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models.campaign import Campaign
from db.models.enums import CampaignStatus, OrgScenarioStatus, ScenarioKind
from db.models.org_scenario import CampaignOrgScenarioRef, OrgScenario, OrgScenarioTag


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def lookup_org_scenario_org_id(db: AsyncSession, scenario_id: str) -> str | None:
    """Resolve scenario org without tenant context (background / lookup paths)."""
    table = OrgScenario.__table__
    result = await db.execute(
        select(table.c.org_id).where(table.c.id == scenario_id).limit(1)
    )
    return result.scalar_one_or_none()


async def get_org_scenario(
    db: AsyncSession,
    scenario_id: str,
    *,
    include_tags: bool = True,
    org_id: str | None = None,
) -> OrgScenario | None:
    from tenancy.context import get_current_org_id, use_tenant_scope

    scope_org = get_current_org_id() or org_id
    if not scope_org:
        scope_org = await lookup_org_scenario_org_id(db, scenario_id)
    with use_tenant_scope(scope_org):
        stmt = select(OrgScenario).where(OrgScenario.id == scenario_id)
        if include_tags:
            stmt = stmt.options(selectinload(OrgScenario.tags))
        result = await db.execute(stmt)
        return result.scalar_one_or_none()


async def find_by_org_and_name_lower(
    db: AsyncSession,
    org_id: str,
    name_lower: str,
    *,
    exclude_archived: bool = True,
) -> OrgScenario | None:
    from tenancy.context import use_tenant_scope

    with use_tenant_scope(org_id):
        stmt = select(OrgScenario).where(
            OrgScenario.org_id == org_id,
            OrgScenario.name_lower == name_lower,
            OrgScenario.deleted_at.is_(None),
        )
        if exclude_archived:
            stmt = stmt.where(OrgScenario.status != OrgScenarioStatus.ARCHIVED.value)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()


async def list_org_scenarios(
    db: AsyncSession,
    org_id: str,
    *,
    include_archived: bool = False,
    tag: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[OrgScenario]:
    from tenancy.context import use_tenant_scope

    with use_tenant_scope(org_id):
        stmt = (
            select(OrgScenario)
            .where(OrgScenario.org_id == org_id)
            .options(selectinload(OrgScenario.tags))
            .order_by(OrgScenario.updated_at.desc(), OrgScenario.name.asc())
            .limit(limit)
            .offset(offset)
        )
        if include_archived:
            stmt = stmt.where(
                (OrgScenario.deleted_at.is_(None))
                | (OrgScenario.status == OrgScenarioStatus.ARCHIVED.value)
            )
        else:
            stmt = stmt.where(
                OrgScenario.deleted_at.is_(None),
                OrgScenario.status != OrgScenarioStatus.ARCHIVED.value,
            )
        if tag:
            stmt = stmt.join(OrgScenarioTag).where(
                func.lower(OrgScenarioTag.tag) == tag.strip().lower()
            )
        result = await db.execute(stmt)
        return list(result.scalars().unique().all())


async def get_org_scenario_bodies_by_ids(
    db: AsyncSession,
    org_id: str,
    scenario_ids: list[str],
) -> list[tuple[str, str, dict | None]]:
    """Batch-load kind + body_json for nested run_scenario validation."""
    from tenancy.context import use_tenant_scope

    if not scenario_ids:
        return []
    with use_tenant_scope(org_id):
        stmt = select(OrgScenario.id, OrgScenario.kind, OrgScenario.body_json).where(
            OrgScenario.org_id == org_id,
            OrgScenario.id.in_(scenario_ids),
        )
        result = await db.execute(stmt)
        return [(row.id, row.kind, row.body_json) for row in result.all()]


async def get_org_scenario_refs_by_ids(
    db: AsyncSession,
    org_id: str,
    scenario_ids: list[str],
) -> list[tuple[str, str, dict | None, str, int]]:
    """Batch-load ref metadata for org scenario validation."""
    from tenancy.context import use_tenant_scope

    if not scenario_ids:
        return []
    with use_tenant_scope(org_id):
        stmt = select(
            OrgScenario.id,
            OrgScenario.kind,
            OrgScenario.body_json,
            OrgScenario.status,
            OrgScenario.scenario_version,
        ).where(
            OrgScenario.org_id == org_id,
            OrgScenario.id.in_(scenario_ids),
        )
        result = await db.execute(stmt)
        return [
            (
                row.id,
                row.kind,
                row.body_json if isinstance(row.body_json, dict) else None,
                row.status,
                int(row.scenario_version or 1),
            )
            for row in result.all()
        ]


async def get_org_scenario_names_by_ids(
    db: AsyncSession,
    org_id: str,
    scenario_ids: list[str],
) -> dict[str, str]:
    """Batch map scenario id -> name for export portability."""
    from tenancy.context import use_tenant_scope

    if not scenario_ids:
        return {}
    with use_tenant_scope(org_id):
        stmt = select(OrgScenario.id, OrgScenario.name).where(
            OrgScenario.org_id == org_id,
            OrgScenario.id.in_(scenario_ids),
        )
        result = await db.execute(stmt)
        return {row.id: row.name for row in result.all()}


async def find_by_org_and_names_lower(
    db: AsyncSession,
    org_id: str,
    names_lower: list[str],
) -> dict[str, OrgScenario]:
    """Batch lookup scenarios by lowercased name within an org."""
    from tenancy.context import use_tenant_scope

    if not names_lower:
        return {}
    with use_tenant_scope(org_id):
        stmt = select(OrgScenario).where(
            OrgScenario.org_id == org_id,
            OrgScenario.name_lower.in_(names_lower),
            OrgScenario.deleted_at.is_(None),
            OrgScenario.status != OrgScenarioStatus.ARCHIVED.value,
        )
        result = await db.execute(stmt)
        return {row.name_lower: row for row in result.scalars().all()}


async def get_org_scenario_meta_by_ids(
    db: AsyncSession,
    org_id: str,
    scenario_ids: list[str],
) -> list[tuple[str, str, int]]:
    """Batch-load id, status, scenario_version without body_json (ref pinning)."""
    from tenancy.context import use_tenant_scope

    if not scenario_ids:
        return []
    with use_tenant_scope(org_id):
        stmt = select(
            OrgScenario.id,
            OrgScenario.status,
            OrgScenario.scenario_version,
        ).where(
            OrgScenario.org_id == org_id,
            OrgScenario.id.in_(scenario_ids),
        )
        result = await db.execute(stmt)
        return [
            (row.id, row.status, int(row.scenario_version or 1))
            for row in result.all()
        ]


async def create_org_scenario(
    db: AsyncSession,
    *,
    org_id: str,
    name: str,
    kind: str,
    description: str = "",
    body_json: dict | None = None,
    created_by: str | None = None,
    tags: list[str] | None = None,
    last_validation_summary: dict | None = None,
    last_validated_at: datetime | None = None,
) -> OrgScenario:
    row = OrgScenario(
        org_id=org_id,
        name=name.strip(),
        name_lower=name.strip().lower(),
        description=description or "",
        kind=kind,
        status=OrgScenarioStatus.DRAFT.value,
        scenario_version=1,
        body_json=body_json,
        created_by=created_by,
        last_validation_summary=last_validation_summary,
        last_validated_at=last_validated_at,
    )
    db.add(row)
    await db.flush()
    if tags:
        await replace_tags(db, row.id, tags)
    return row


async def replace_tags(
    db: AsyncSession,
    org_scenario_id: str,
    tags: list[str],
) -> None:
    await db.execute(
        delete(OrgScenarioTag).where(OrgScenarioTag.org_scenario_id == org_scenario_id)
    )
    seen: set[str] = set()
    for raw in tags:
        label = (raw or "").strip()
        if not label:
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        db.add(OrgScenarioTag(org_scenario_id=org_scenario_id, tag=label))


async def update_org_scenario(
    db: AsyncSession,
    row: OrgScenario,
    *,
    name: str | None = None,
    description: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    body_json: dict | None = None,
    bump_version: bool = False,
    tags: list[str] | None = None,
    last_validation_summary: dict | None = None,
    last_validated_at: datetime | None = None,
) -> OrgScenario:
    if name is not None:
        row.name = name.strip()
        row.name_lower = name.strip().lower()
    if description is not None:
        row.description = description
    if kind is not None:
        row.kind = kind
    if status is not None:
        row.status = status
    if body_json is not None:
        row.body_json = body_json
        bump_version = True
    if bump_version:
        row.scenario_version = int(row.scenario_version or 0) + 1
    if last_validation_summary is not None:
        row.last_validation_summary = last_validation_summary
    if last_validated_at is not None:
        row.last_validated_at = last_validated_at
    row.updated_at = _now()
    if tags is not None:
        await replace_tags(db, row.id, tags)
    await db.flush()
    return row


async def archive_org_scenario(db: AsyncSession, row: OrgScenario) -> OrgScenario:
    row.status = OrgScenarioStatus.ARCHIVED.value
    row.deleted_at = _now()
    row.updated_at = _now()
    await db.flush()
    return row


async def restore_org_scenario(db: AsyncSession, row: OrgScenario) -> OrgScenario:
    row.deleted_at = None
    if row.status == OrgScenarioStatus.ARCHIVED.value:
        body = row.body_json if isinstance(row.body_json, dict) else {}
        kind = row.kind or ScenarioKind.SEQUENCE.value
        has_body = False
        if kind == ScenarioKind.SEQUENCE.value:
            steps = body.get("steps")
            has_body = isinstance(steps, list) and len(steps) > 0
        else:
            nodes = body.get("nodes")
            has_body = isinstance(nodes, list) and len(nodes) > 0
        row.status = (
            OrgScenarioStatus.ACTIVE.value
            if has_body
            else OrgScenarioStatus.DRAFT.value
        )
    row.updated_at = _now()
    await db.flush()
    return row


async def list_running_campaign_refs(
    db: AsyncSession,
    org_scenario_id: str,
) -> list[dict[str, Any]]:
    stmt = (
        select(Campaign.id, Campaign.name, Campaign.status)
        .join(CampaignOrgScenarioRef, CampaignOrgScenarioRef.campaign_id == Campaign.id)
        .where(
            CampaignOrgScenarioRef.org_scenario_id == org_scenario_id,
            Campaign.status == CampaignStatus.RUNNING.value,
        )
    )
    result = await db.execute(stmt)
    return [
        {"campaign_id": row.id, "name": row.name, "status": row.status}
        for row in result.all()
    ]


async def add_campaign_scenario_ref(
    db: AsyncSession,
    *,
    campaign_id: str,
    org_scenario_id: str,
    pinned_version: int | None = None,
    order_index: int = 0,
) -> CampaignOrgScenarioRef:
    ref = CampaignOrgScenarioRef(
        campaign_id=campaign_id,
        org_scenario_id=org_scenario_id,
        pinned_version=pinned_version,
        order_index=order_index,
    )
    db.add(ref)
    await db.flush()
    return ref
