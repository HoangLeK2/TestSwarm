"""CRUD for Epic 04 org-scoped campaign entity (DF-T-04-006)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models.campaign import Campaign, CampaignTag
from db.models.enums import CampaignStatus
from db.models.org_scenario import CampaignOrgScenarioRef


def _now() -> datetime:
    return datetime.now(timezone.utc)


def loaded_org_scenario_refs(campaign: Campaign) -> list[CampaignOrgScenarioRef]:
    """Return pinned org-scenario refs without async lazy-load (MissingGreenlet-safe)."""
    if "org_scenario_refs" not in campaign.__dict__:
        return []
    raw = campaign.__dict__["org_scenario_refs"]
    return list(raw) if raw else []


async def lookup_campaign_org_id(db: AsyncSession, campaign_id: str) -> str | None:
    """Resolve campaign org without tenant context (Temporal/background paths)."""
    from sqlalchemy import text

    result = await db.execute(
        text("SELECT org_id FROM campaigns WHERE id = :campaign_id LIMIT 1"),
        {"campaign_id": campaign_id},
    )
    row = result.first()
    return str(row[0]) if row and row[0] else None


async def get_campaign_entity(
    db: AsyncSession,
    campaign_id: str,
    *,
    include_tags: bool = True,
    include_refs: bool = True,
    for_update: bool = False,
    org_id: str | None = None,
) -> Campaign | None:
    from tenancy.context import get_current_org_id, use_tenant_scope

    scope_org = get_current_org_id() or org_id
    if not scope_org:
        scope_org = await lookup_campaign_org_id(db, campaign_id)
    with use_tenant_scope(scope_org):
        stmt = select(Campaign).where(Campaign.id == campaign_id)
        if include_tags:
            stmt = stmt.options(selectinload(Campaign.tags))
        if include_refs:
            stmt = stmt.options(selectinload(Campaign.org_scenario_refs))
        if for_update:
            stmt = stmt.with_for_update()
        result = await db.execute(stmt)
        return result.scalar_one_or_none()


async def find_by_org_and_name_lower(
    db: AsyncSession,
    org_id: str,
    name_lower: str,
    *,
    exclude_archived: bool = True,
) -> Campaign | None:
    from tenancy.context import use_tenant_scope

    with use_tenant_scope(org_id):
        stmt = select(Campaign).where(
            Campaign.org_id == org_id,
            Campaign.name_lower == name_lower,
            Campaign.deleted_at.is_(None),
        )
        if exclude_archived:
            stmt = stmt.where(Campaign.status != CampaignStatus.ARCHIVED.value)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()


async def list_campaign_entities(
    db: AsyncSession,
    org_id: str,
    *,
    include_archived: bool = False,
    tag: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[Campaign]:
    from tenancy.context import use_tenant_scope

    with use_tenant_scope(org_id):
        stmt = (
            select(Campaign)
            .where(Campaign.org_id == org_id)
            .options(selectinload(Campaign.tags), selectinload(Campaign.org_scenario_refs))
            .order_by(Campaign.updated_at.desc(), Campaign.name.asc())
            .limit(limit)
            .offset(offset)
        )
        if include_archived:
            stmt = stmt.where(
                (Campaign.deleted_at.is_(None))
                | (Campaign.status == CampaignStatus.ARCHIVED.value)
            )
        else:
            stmt = stmt.where(
                Campaign.deleted_at.is_(None),
                Campaign.status != CampaignStatus.ARCHIVED.value,
            )
        if tag:
            stmt = stmt.join(CampaignTag).where(
                func.lower(CampaignTag.tag) == tag.strip().lower()
            )
        result = await db.execute(stmt)
        return list(result.scalars().unique().all())


async def create_campaign_entity(
    db: AsyncSession,
    *,
    org_id: str,
    name: str,
    description: str = "",
    variables: dict | None = None,
    per_device_overrides: dict | None = None,
    recovery_policy: dict | None = None,
    account_group_id: str | None = None,
    scenario_account_id: str | None = None,
    per_device_accounts: dict | None = None,
    created_by: str | None = None,
    tags: list[str] | None = None,
    status: str = CampaignStatus.DRAFT.value,
) -> Campaign:
    clean = name.strip()
    row = Campaign(
        org_id=org_id,
        name=clean,
        name_lower=clean.lower(),
        description=description or "",
        variables=variables or {},
        per_device_overrides=per_device_overrides or {},
        recovery_policy=recovery_policy or {},
        account_group_id=account_group_id or None,
        scenario_account_id=scenario_account_id or None,
        per_device_accounts=per_device_accounts or {},
        status=status,
        user_id=created_by,
        created_by=created_by,
    )
    db.add(row)
    await db.flush()
    if tags:
        await replace_campaign_tags(db, row.id, tags)
    return row


async def replace_campaign_tags(
    db: AsyncSession,
    campaign_id: str,
    tags: list[str],
) -> None:
    await db.execute(delete(CampaignTag).where(CampaignTag.campaign_id == campaign_id))
    seen: set[str] = set()
    for raw in tags:
        label = (raw or "").strip()
        if not label:
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        db.add(CampaignTag(campaign_id=campaign_id, tag=label))


async def replace_campaign_scenario_refs(
    db: AsyncSession,
    campaign_id: str,
    refs: list[tuple[str, int, int, int]],
) -> None:
    """Replace all org-scenario refs.

    Tuples are (org_scenario_id, pinned_version, order_index, repeat_count).
    """
    await db.execute(
        delete(CampaignOrgScenarioRef).where(CampaignOrgScenarioRef.campaign_id == campaign_id)
    )
    for scenario_id, pinned_version, order_index, repeat_count in refs:
        db.add(
            CampaignOrgScenarioRef(
                campaign_id=campaign_id,
                org_scenario_id=scenario_id,
                pinned_version=pinned_version,
                order_index=order_index,
                repeat_count=repeat_count,
            )
        )
    await db.flush()


async def update_campaign_entity(
    db: AsyncSession,
    row: Campaign,
    *,
    name: str | None = None,
    description: str | None = None,
    variables: dict | None = None,
    per_device_overrides: dict | None = None,
    recovery_policy: dict | None = None,
    tags: list[str] | None = None,
) -> Campaign:
    if name is not None:
        clean = name.strip()
        row.name = clean
        row.name_lower = clean.lower()
    if description is not None:
        row.description = description
    if variables is not None:
        row.variables = variables
    if per_device_overrides is not None:
        row.per_device_overrides = per_device_overrides
    if recovery_policy is not None:
        row.recovery_policy = recovery_policy
    row.updated_at = _now()
    if tags is not None:
        await replace_campaign_tags(db, row.id, tags)
    await db.flush()
    return row


async def archive_campaign_entity(db: AsyncSession, row: Campaign) -> Campaign:
    row.status = CampaignStatus.ARCHIVED.value
    row.deleted_at = _now()
    row.updated_at = _now()
    await db.flush()
    return row
