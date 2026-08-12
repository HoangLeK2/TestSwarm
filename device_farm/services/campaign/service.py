"""Org-scoped campaign business rules (DF-T-04-006)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud import campaign_entity as repo
from db.models.campaign import Campaign
from db.models.enums import CampaignStatus
from services.campaign.errors import (
    CampaignDuplicateNameError,
    CampaignError,
    CampaignNotFoundError,
    CampaignRunningError,
    CampaignValidationError,
)
from services.campaign.events import emit_campaign_domain_event
from services.campaign.override_resolver import (
    OverridePayloadTooLargeError,
    validate_per_device_overrides_size,
)
from services.campaign.scenario_ref_resolver import (
    CampaignScenarioRefError,
    ResolvedScenarioRef,
    resolve_scenario_refs,
)
from tenancy.context import tenant_context


@dataclass(frozen=True, slots=True)
class CampaignScenarioRefView:
    scenario_id: str
    scenario_version: int
    repeat_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "scenario_version": self.scenario_version,
            "repeat_count": self.repeat_count,
        }


@dataclass(frozen=True, slots=True)
class CampaignView:
    id: str
    organization_id: str
    name: str
    description: str
    status: str
    vars: dict[str, Any]
    per_device_overrides: dict[str, Any]
    recovery_policy: dict[str, Any]
    account_group_id: str | None
    scenario_account_id: str | None
    per_device_accounts: dict[str, str]
    tags: list[str]
    scenario_refs: list[CampaignScenarioRefView]
    created_by: str | None
    created_at: str
    updated_at: str
    started_at: str | None = None
    completed_at: str | None = None
    cancelled_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "vars": self.vars,
            "per_device_overrides": self.per_device_overrides,
            "recovery_policy": self.recovery_policy,
            "account_group_id": self.account_group_id,
            "scenario_account_id": self.scenario_account_id,
            "per_device_accounts": self.per_device_accounts,
            "tags": self.tags,
            "scenario_refs": [ref.to_dict() for ref in self.scenario_refs],
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "cancelled_at": self.cancelled_at,
        }


def _tags_from_row(row: Campaign) -> list[str]:
    loaded = row.__dict__.get("tags")
    if not loaded:
        return []
    return sorted({t.tag for t in loaded if t.tag})


def _refs_from_row(row: Campaign) -> list[CampaignScenarioRefView]:
    from db.crud.campaign_entity import loaded_org_scenario_refs

    loaded = loaded_org_scenario_refs(row)
    if not loaded:
        return []
    ordered = sorted(loaded, key=lambda r: int(r.order_index or 0))
    return [
        CampaignScenarioRefView(
            scenario_id=ref.org_scenario_id,
            scenario_version=int(ref.pinned_version or 1),
            repeat_count=int(getattr(ref, "repeat_count", 1) or 1),
        )
        for ref in ordered
    ]


def _view_from_row(
    row: Campaign,
    *,
    tags: list[str] | None = None,
    scenario_refs: list[CampaignScenarioRefView] | None = None,
) -> CampaignView:
    created_by = getattr(row, "created_by", None) or row.user_id
    if tags is None:
        tags = _tags_from_row(row)
    if scenario_refs is None:
        scenario_refs = _refs_from_row(row)
    return CampaignView(
        id=row.id,
        organization_id=row.org_id,
        name=row.name,
        description=row.description or "",
        status=row.status,
        vars=dict(row.variables or {}),
        per_device_overrides=dict(row.per_device_overrides or {}),
        recovery_policy=dict(getattr(row, "recovery_policy", None) or {}),
        account_group_id=getattr(row, "account_group_id", None),
        scenario_account_id=getattr(row, "scenario_account_id", None),
        per_device_accounts={
            str(k): str(v)
            for k, v in (getattr(row, "per_device_accounts", None) or {}).items()
            if v
        },
        tags=tags,
        scenario_refs=scenario_refs,
        created_by=created_by,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
        started_at=row.started_at.isoformat() if row.started_at else None,
        completed_at=row.completed_at.isoformat() if row.completed_at else None,
        cancelled_at=row.cancelled_at.isoformat() if row.cancelled_at else None,
    )


def _ref_views_from_resolved(resolved: list[ResolvedScenarioRef]) -> list[CampaignScenarioRefView]:
    return [
        CampaignScenarioRefView(
            scenario_id=ref.scenario_id,
            scenario_version=ref.scenario_version,
            repeat_count=ref.repeat_count,
        )
        for ref in resolved
    ]


def _normalize_tags(tags: list[str] | None) -> list[str]:
    if not tags:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in tags:
        label = (raw or "").strip()
        if not label:
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(label)
    return sorted(out)


async def create_campaign(
    db: AsyncSession,
    *,
    org_id: str,
    name: str,
    description: str = "",
    vars: dict[str, Any] | None = None,
    per_device_overrides: dict[str, Any] | None = None,
    recovery_policy: dict[str, Any] | None = None,
    account_group_id: str | None = None,
    scenario_account_id: str | None = None,
    per_device_accounts: dict[str, str] | None = None,
    tags: list[str] | None = None,
    scenario_refs: list[dict[str, Any]] | None = None,
    created_by: str | None = None,
) -> CampaignView:
    with tenant_context(org_id):
        return await _create_campaign_in_tenant(
            db,
            org_id=org_id,
            name=name,
            description=description,
            vars=vars,
            per_device_overrides=per_device_overrides,
            recovery_policy=recovery_policy,
            account_group_id=account_group_id,
            scenario_account_id=scenario_account_id,
            per_device_accounts=per_device_accounts,
            tags=tags,
            scenario_refs=scenario_refs,
            created_by=created_by,
        )


async def _create_campaign_in_tenant(
    db: AsyncSession,
    *,
    org_id: str,
    name: str,
    description: str = "",
    vars: dict[str, Any] | None = None,
    per_device_overrides: dict[str, Any] | None = None,
    recovery_policy: dict[str, Any] | None = None,
    account_group_id: str | None = None,
    scenario_account_id: str | None = None,
    per_device_accounts: dict[str, str] | None = None,
    tags: list[str] | None = None,
    scenario_refs: list[dict[str, Any]] | None = None,
    created_by: str | None = None,
) -> CampaignView:
    clean_name = (name or "").strip()
    if not clean_name:
        raise CampaignValidationError("name is required", code="INVALID_NAME")

    if per_device_overrides is not None:
        try:
            validate_per_device_overrides_size(per_device_overrides)
        except OverridePayloadTooLargeError as exc:
            raise CampaignValidationError(str(exc), code=exc.code) from exc

    existing = await repo.find_by_org_and_name_lower(db, org_id, clean_name.lower())
    if existing is not None:
        raise CampaignDuplicateNameError(clean_name)

    resolved = await resolve_scenario_refs(
        db,
        org_id=org_id,
        refs=scenario_refs or [],
    )
    if not resolved:
        raise CampaignValidationError(
            "At least one org scenario is required",
            code="SCENARIO_REQUIRED",
        )

    from services.execution.recovery_policy import (
        RecoveryPolicyError,
        validate_recovery_policy_references,
    )

    try:
        normalized_recovery_policy = await validate_recovery_policy_references(
            db,
            org_id=org_id,
            raw=recovery_policy or {},
        )
    except RecoveryPolicyError as exc:
        raise CampaignValidationError(str(exc), code=exc.code) from exc

    bind_accounts = bool(
        account_group_id or scenario_account_id or (per_device_accounts or {})
    )
    if bind_accounts:
        from services.campaign.account_resolver import validate_bind_payload
        from services.campaign.override_resolver import validate_per_device_accounts_size

        try:
            validate_per_device_accounts_size(per_device_accounts)
        except ValueError as exc:
            raise CampaignValidationError(str(exc), code=getattr(exc, "code", "INVALID_BIND_PAYLOAD")) from exc
        await validate_bind_payload(
            db,
            org_id=org_id,
            account_group_id=account_group_id,
            scenario_account_id=scenario_account_id,
            per_device_accounts=per_device_accounts,
        )

    try:
        row = await repo.create_campaign_entity(
            db,
            org_id=org_id,
            name=clean_name,
            description=description,
            variables=vars,
            per_device_overrides=per_device_overrides,
            recovery_policy=normalized_recovery_policy,
            account_group_id=account_group_id,
            scenario_account_id=scenario_account_id,
            per_device_accounts=per_device_accounts,
            created_by=created_by,
            tags=tags,
            status=CampaignStatus.DRAFT.value,
        )
        if resolved:
            await repo.replace_campaign_scenario_refs(
                db,
                row.id,
                [
                    (
                        r.scenario_id,
                        r.scenario_version,
                        r.order_index,
                        r.repeat_count,
                    )
                    for r in resolved
                ],
            )
    except IntegrityError as exc:
        raise CampaignDuplicateNameError(clean_name) from exc

    await emit_campaign_domain_event(
        db,
        event="campaign.created",
        org_id=org_id,
        campaign_id=row.id,
        user_id=created_by,
        details={"scenario_ref_count": len(resolved)},
    )

    return _view_from_row(
        row,
        tags=_normalize_tags(tags),
        scenario_refs=_ref_views_from_resolved(resolved),
    )


async def get_campaign_for_org(
    db: AsyncSession,
    campaign_id: str,
    org_id: str,
) -> CampaignView:
    with tenant_context(org_id):
        row = await repo.get_campaign_entity(db, campaign_id)
        if row is None or row.org_id != org_id or row.status == CampaignStatus.ARCHIVED.value:
            raise CampaignNotFoundError()
        return _view_from_row(row)


async def list_campaigns_for_org(
    db: AsyncSession,
    org_id: str,
    *,
    include_archived: bool = False,
    tag: str | None = None,
) -> list[CampaignView]:
    with tenant_context(org_id):
        rows = await repo.list_campaign_entities(
            db, org_id, include_archived=include_archived, tag=tag
        )
        return [_view_from_row(r) for r in rows]


async def update_campaign(
    db: AsyncSession,
    *,
    org_id: str,
    campaign_id: str,
    user_id: str | None,
    name: str | None = None,
    description: str | None = None,
    vars: dict[str, Any] | None = None,
    per_device_overrides: dict[str, Any] | None = None,
    recovery_policy: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    scenario_refs: list[dict[str, Any]] | None = None,
) -> CampaignView:
    with tenant_context(org_id):
        return await _update_campaign_in_tenant(
            db,
            org_id=org_id,
            campaign_id=campaign_id,
            user_id=user_id,
            name=name,
            description=description,
            vars=vars,
            per_device_overrides=per_device_overrides,
            recovery_policy=recovery_policy,
            tags=tags,
            scenario_refs=scenario_refs,
        )


async def _update_campaign_in_tenant(
    db: AsyncSession,
    *,
    org_id: str,
    campaign_id: str,
    user_id: str | None,
    name: str | None = None,
    description: str | None = None,
    vars: dict[str, Any] | None = None,
    per_device_overrides: dict[str, Any] | None = None,
    recovery_policy: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    scenario_refs: list[dict[str, Any]] | None = None,
) -> CampaignView:
    from services.campaign.lifecycle import assert_body_fields_mutable

    row = await repo.get_campaign_entity(db, campaign_id)
    if row is None or row.org_id != org_id:
        raise CampaignNotFoundError()
    if row.status == CampaignStatus.ARCHIVED.value:
        raise CampaignValidationError("Cannot update archived campaign", code="CAMPAIGN_ARCHIVED")

    assert_body_fields_mutable(
        row,
        scenario_refs=scenario_refs,
        vars=vars,
        per_device_overrides=per_device_overrides,
    )

    if per_device_overrides is not None:
        try:
            validate_per_device_overrides_size(per_device_overrides)
        except OverridePayloadTooLargeError as exc:
            raise CampaignValidationError(str(exc), code=exc.code) from exc

    normalized_recovery_policy = None
    if recovery_policy is not None:
        from services.execution.recovery_policy import (
            RecoveryPolicyError,
            validate_recovery_policy_references,
        )

        try:
            normalized_recovery_policy = await validate_recovery_policy_references(
                db,
                org_id=org_id,
                raw=recovery_policy,
            )
        except RecoveryPolicyError as exc:
            raise CampaignValidationError(str(exc), code=exc.code) from exc

    if name is not None:
        clean_name = name.strip()
        if not clean_name:
            raise CampaignValidationError("name is required", code="INVALID_NAME")
        if clean_name.lower() != row.name_lower:
            dup = await repo.find_by_org_and_name_lower(db, org_id, clean_name.lower())
            if dup is not None and dup.id != row.id:
                raise CampaignDuplicateNameError(clean_name)
        name = clean_name

    resolved = None
    if scenario_refs is not None:
        resolved = await resolve_scenario_refs(db, org_id=org_id, refs=scenario_refs)
        if not resolved:
            raise CampaignValidationError(
                "At least one org scenario is required",
                code="SCENARIO_REQUIRED",
            )

    updated = await repo.update_campaign_entity(
        db,
        row,
        name=name,
        description=description,
        variables=vars,
        per_device_overrides=per_device_overrides,
        recovery_policy=normalized_recovery_policy,
        tags=tags,
    )
    if resolved is not None:
        await repo.replace_campaign_scenario_refs(
            db,
            updated.id,
            [
                (r.scenario_id, r.scenario_version, r.order_index, r.repeat_count)
                for r in resolved
            ],
        )

    await emit_campaign_domain_event(
        db,
        event="campaign.updated",
        org_id=org_id,
        campaign_id=updated.id,
        user_id=user_id,
    )

    ref_views = _ref_views_from_resolved(resolved) if resolved is not None else None
    tag_views = _normalize_tags(tags) if tags is not None else None
    if ref_views is not None or tag_views is not None:
        return _view_from_row(
            updated,
            tags=tag_views,
            scenario_refs=ref_views,
        )
    return _view_from_row(updated)


async def archive_campaign(
    db: AsyncSession,
    *,
    org_id: str,
    campaign_id: str,
    user_id: str | None,
) -> CampaignView:
    with tenant_context(org_id):
        return await _archive_campaign_in_tenant(
            db,
            org_id=org_id,
            campaign_id=campaign_id,
            user_id=user_id,
        )


async def _archive_campaign_in_tenant(
    db: AsyncSession,
    *,
    org_id: str,
    campaign_id: str,
    user_id: str | None,
) -> CampaignView:
    from services.campaign.lifecycle import apply_campaign_transition

    row = await repo.get_campaign_entity(db, campaign_id)
    if row is None or row.org_id != org_id:
        raise CampaignNotFoundError()
    if row.status == CampaignStatus.ARCHIVED.value:
        return _view_from_row(row)
    if row.status == CampaignStatus.RUNNING.value:
        raise CampaignRunningError()

    await apply_campaign_transition(
        db,
        row,
        CampaignStatus.ARCHIVED,
        org_id=org_id,
        user_id=user_id,
        reason="archive",
    )
    await emit_campaign_domain_event(
        db,
        event="campaign.archived",
        org_id=org_id,
        campaign_id=row.id,
        user_id=user_id,
    )
    refreshed = await repo.get_campaign_entity(db, campaign_id)
    assert refreshed is not None
    return _view_from_row(refreshed)


def map_scenario_ref_error(exc: CampaignScenarioRefError) -> CampaignError:
    return CampaignError(str(exc), code=exc.code)
