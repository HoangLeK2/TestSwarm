"""Org-scoped scenario library business rules (DF-T-04-001)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud import org_scenario as repo
from db.models.enums import OrgScenarioStatus, ScenarioKind
from db.models.org_scenario import OrgScenario
from services.org_scenario.errors import (
    OrgScenarioBodyValidationError,
    OrgScenarioDuplicateNameError,
    OrgScenarioError,
    OrgScenarioInUseError,
    OrgScenarioNotFoundError,
    OrgScenarioValidationError,
)
from services.org_scenario.events import emit_scenario_domain_event
from services.org_scenario_io.constants import SYSTEM_ORG_ID


def _validate_kind(kind: str) -> str:
    try:
        return ScenarioKind(kind).value
    except ValueError as exc:
        raise OrgScenarioValidationError(
            f"Invalid kind: {kind}", code="INVALID_KIND"
        ) from exc


def is_system_template_org(org_id: str) -> bool:
    return org_id == SYSTEM_ORG_ID


def _assert_scenario_read_access(row: OrgScenario, caller_org_id: str) -> None:
    if row.org_id == caller_org_id or row.org_id == SYSTEM_ORG_ID:
        return
    raise OrgScenarioNotFoundError()


def _assert_scenario_write_access(
    row: OrgScenario, caller_org_id: str, *, is_superadmin: bool
) -> None:
    if row.org_id == SYSTEM_ORG_ID:
        if not is_superadmin:
            raise OrgScenarioValidationError(
                "System templates are read-only",
                code="SYSTEM_TEMPLATE_READ_ONLY",
            )
        return
    if row.org_id != caller_org_id:
        raise OrgScenarioNotFoundError()


def _validate_status(status: str) -> str:
    try:
        return OrgScenarioStatus(status).value
    except ValueError as exc:
        raise OrgScenarioValidationError(
            f"Invalid status: {status}", code="INVALID_STATUS"
        ) from exc


@dataclass(frozen=True, slots=True)
class OrgScenarioView:
    id: str
    organization_id: str
    name: str
    description: str
    kind: str
    status: str
    scenario_version: int
    body_json: dict | None
    tags: list[str]
    created_by: str | None
    created_at: str
    updated_at: str
    is_runnable: bool = False
    last_validation_summary: dict[str, Any] | None = None
    last_validated_at: str | None = None

    def to_dict(self, *, include_body: bool = True) -> dict[str, Any]:
        data = {
            "id": self.id,
            "organization_id": self.organization_id,
            "name": self.name,
            "description": self.description,
            "kind": self.kind,
            "status": self.status,
            "scenario_version": self.scenario_version,
            "tags": self.tags,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if include_body:
            data["body_json"] = self.body_json
        data["is_runnable"] = self.is_runnable
        if self.last_validation_summary is not None:
            data["last_validation_summary"] = self.last_validation_summary
        if self.last_validated_at is not None:
            data["last_validated_at"] = self.last_validated_at
        return data


def _tags_from_row(row: OrgScenario) -> list[str]:
    loaded = row.__dict__.get("tags")
    if not loaded:
        return []
    return sorted({t.tag for t in loaded if t.tag})


def _is_body_runnable(body_json: dict | None, kind: str) -> bool:
    if not isinstance(body_json, dict):
        return False
    if kind == "sequence":
        steps = body_json.get("steps")
        return isinstance(steps, list) and len(steps) > 0
    if kind == "graph":
        nodes = body_json.get("nodes")
        edges = body_json.get("edges")
        return isinstance(nodes, list) and len(nodes) > 0 and isinstance(edges, list)
    return False


def _view_from_row(row: OrgScenario, *, include_body: bool = True) -> OrgScenarioView:
    tags = _tags_from_row(row)
    body = row.body_json if isinstance(row.body_json, dict) else None
    is_runnable = _is_body_runnable(body, row.kind)
    return OrgScenarioView(
        id=row.id,
        organization_id=row.org_id,
        name=row.name,
        description=row.description or "",
        kind=row.kind,
        status=row.status,
        scenario_version=int(row.scenario_version or 1),
        body_json=body if include_body else None,
        tags=tags,
        created_by=row.created_by,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
        is_runnable=is_runnable,
        last_validation_summary=getattr(row, "last_validation_summary", None),
        last_validated_at=(
            row.last_validated_at.isoformat() if getattr(row, "last_validated_at", None) else None
        ),
    )


async def create_scenario(
    db: AsyncSession,
    *,
    org_id: str,
    name: str,
    kind: str,
    description: str = "",
    body_json: dict | None = None,
    tags: list[str] | None = None,
    created_by: str | None = None,
) -> OrgScenarioView:
    from contextlib import nullcontext

    from tenancy.context import tenant_context

    tenant_ctx = (
        tenant_context(SYSTEM_ORG_ID) if is_system_template_org(org_id) else nullcontext()
    )
    with tenant_ctx:
        return await _create_scenario_in_tenant(
            db,
            org_id=org_id,
            name=name,
            kind=kind,
            description=description,
            body_json=body_json,
            tags=tags,
            created_by=created_by,
        )


async def _create_scenario_in_tenant(
    db: AsyncSession,
    *,
    org_id: str,
    name: str,
    kind: str,
    description: str = "",
    body_json: dict | None = None,
    tags: list[str] | None = None,
    created_by: str | None = None,
) -> OrgScenarioView:
    clean_name = (name or "").strip()
    if not clean_name:
        raise OrgScenarioValidationError("name is required", code="INVALID_NAME")
    kind_value = _validate_kind(kind)
    existing = await repo.find_by_org_and_name_lower(db, org_id, clean_name.lower())
    if existing is not None:
        raise OrgScenarioDuplicateNameError(clean_name)
    try:
        row = await repo.create_org_scenario(
            db,
            org_id=org_id,
            name=clean_name,
            kind=kind_value,
            description=description,
            body_json=body_json,
            created_by=created_by,
            tags=tags,
        )
    except IntegrityError as exc:
        raise OrgScenarioDuplicateNameError(clean_name) from exc
    await emit_scenario_domain_event(
        db,
        event="scenario.created",
        org_id=org_id,
        scenario_id=row.id,
        user_id=created_by,
        details={"scenario_version": row.scenario_version, "kind": row.kind},
    )
    if tags:
        refreshed = await repo.get_org_scenario(db, row.id)
        return _view_from_row(refreshed or row)
    return _view_from_row(row)


async def get_scenario_for_org(
    db: AsyncSession,
    scenario_id: str,
    org_id: str,
) -> OrgScenarioView:
    from tenancy.context import tenant_context

    row = None
    for scope_org in (org_id, SYSTEM_ORG_ID) if org_id != SYSTEM_ORG_ID else (org_id,):
        with tenant_context(scope_org):
            row = await repo.get_org_scenario(db, scenario_id)
            if row is not None:
                break
    if row is None:
        raise OrgScenarioNotFoundError()
    _assert_scenario_read_access(row, org_id)
    return _view_from_row(row)


async def list_scenarios_for_org(
    db: AsyncSession,
    org_id: str,
    *,
    include_archived: bool = False,
    tag: str | None = None,
) -> list[OrgScenarioView]:
    from tenancy.context import tenant_context

    with tenant_context(org_id):
        rows = await repo.list_org_scenarios(
            db, org_id, include_archived=include_archived, tag=tag
        )
        return [_view_from_row(r, include_body=False) for r in rows]


async def list_system_template_views(db: AsyncSession) -> list[OrgScenarioView]:
    from tenancy.context import tenant_context

    with tenant_context(SYSTEM_ORG_ID):
        return await list_scenarios_for_org(db, SYSTEM_ORG_ID)


async def update_scenario(
    db: AsyncSession,
    *,
    org_id: str,
    scenario_id: str,
    user_id: str | None,
    name: str | None = None,
    description: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    body_json: dict | None = None,
    tags: list[str] | None = None,
    is_superadmin: bool = False,
) -> OrgScenarioView:
    row = await repo.get_org_scenario(db, scenario_id)
    if row is None:
        raise OrgScenarioNotFoundError()
    _assert_scenario_write_access(row, org_id, is_superadmin=is_superadmin)
    effective_org_id = row.org_id
    if row.status == OrgScenarioStatus.ARCHIVED.value:
        raise OrgScenarioValidationError("Cannot update archived scenario", code="SCENARIO_ARCHIVED")

    bump_version = False
    if name is not None:
        clean_name = name.strip()
        if not clean_name:
            raise OrgScenarioValidationError("name is required", code="INVALID_NAME")
        if clean_name.lower() != row.name_lower:
            dup = await repo.find_by_org_and_name_lower(
                db, effective_org_id, clean_name.lower()
            )
            if dup is not None and dup.id != row.id:
                raise OrgScenarioDuplicateNameError(clean_name)
        name = clean_name

    kind_value = _validate_kind(kind) if kind is not None else None
    status_value = _validate_status(status) if status is not None else None

    if body_json is not None:
        raise OrgScenarioValidationError(
            "Update scenario body via POST /api/scenarios/{id}/body",
            code="USE_BODY_ENDPOINT",
        )

    updated = await repo.update_org_scenario(
        db,
        row,
        name=name,
        description=description,
        kind=kind_value,
        status=status_value,
        bump_version=bump_version,
        tags=tags,
    )
    await emit_scenario_domain_event(
        db,
        event="scenario.updated",
        org_id=effective_org_id,
        scenario_id=updated.id,
        user_id=user_id,
        details={"scenario_version": updated.scenario_version},
    )
    if tags is not None:
        refreshed = await repo.get_org_scenario(db, updated.id)
        return _view_from_row(refreshed or updated)
    return _view_from_row(updated)


async def archive_scenario(
    db: AsyncSession,
    *,
    org_id: str,
    scenario_id: str,
    user_id: str | None,
    is_superadmin: bool = False,
) -> OrgScenarioView:
    row = await repo.get_org_scenario(db, scenario_id)
    if row is None:
        raise OrgScenarioNotFoundError()
    _assert_scenario_write_access(row, org_id, is_superadmin=is_superadmin)
    if row.status == OrgScenarioStatus.ARCHIVED.value:
        return _view_from_row(row)

    refs = await repo.list_running_campaign_refs(db, scenario_id)
    if refs:
        raise OrgScenarioInUseError(refs)

    archived = await repo.archive_org_scenario(db, row)
    await emit_scenario_domain_event(
        db,
        event="scenario.archived",
        org_id=row.org_id,
        scenario_id=archived.id,
        user_id=user_id,
    )
    return _view_from_row(archived)


async def restore_scenario(
    db: AsyncSession,
    *,
    org_id: str,
    scenario_id: str,
    user_id: str | None,
    is_superadmin: bool = False,
) -> OrgScenarioView:
    row = await repo.get_org_scenario(db, scenario_id)
    if row is None:
        raise OrgScenarioNotFoundError()
    _assert_scenario_write_access(row, org_id, is_superadmin=is_superadmin)
    if row.status != OrgScenarioStatus.ARCHIVED.value:
        return _view_from_row(row)

    restored = await repo.restore_org_scenario(db, row)
    await emit_scenario_domain_event(
        db,
        event="scenario.restored",
        org_id=row.org_id,
        scenario_id=restored.id,
        user_id=user_id,
    )
    return _view_from_row(restored)


async def get_scenario_body(
    db: AsyncSession,
    *,
    org_id: str,
    scenario_id: str,
) -> OrgScenarioView:
    row = await repo.get_org_scenario(db, scenario_id)
    if row is None:
        raise OrgScenarioNotFoundError()
    _assert_scenario_read_access(row, org_id)
    return _view_from_row(row)


async def save_scenario_body(
    db: AsyncSession,
    *,
    org_id: str,
    scenario_id: str,
    body: dict[str, Any],
    user_id: str | None,
    force: bool = False,
    campaign_variables: dict[str, Any] | None = None,
    is_superadmin: bool = False,
) -> OrgScenarioView:
    from datetime import datetime, timezone

    from services.org_scenario_validation.validator import validate_org_scenario

    row = await repo.get_org_scenario(db, scenario_id)
    if row is None:
        raise OrgScenarioNotFoundError()
    _assert_scenario_write_access(row, org_id, is_superadmin=is_superadmin)
    if row.status == OrgScenarioStatus.ARCHIVED.value:
        raise OrgScenarioValidationError("Cannot update archived scenario", code="SCENARIO_ARCHIVED")

    result, normalized = await validate_org_scenario(
        db,
        row,
        body=body,
        campaign_variables=campaign_variables,
    )
    now = datetime.now(timezone.utc)
    body_to_save: dict[str, Any] | None = None
    if normalized is not None and (not result.has_errors or force):
        body_to_save = normalized

    updated = await repo.update_org_scenario(
        db,
        row,
        body_json=body_to_save,
        last_validation_summary=result.to_summary_dict(),
        last_validated_at=now,
    )

    if normalized is None:
        primary = result.errors[0].code if result.errors else "SCENARIO_BODY_INVALID"
        raise OrgScenarioBodyValidationError(result, primary_code=primary)
    if result.has_errors and not force:
        primary = result.errors[0].code if result.errors else "SCENARIO_VALIDATION_FAILED"
        raise OrgScenarioBodyValidationError(result, primary_code=primary)
    await emit_scenario_domain_event(
        db,
        event="scenario.updated",
        org_id=org_id,
        scenario_id=updated.id,
        user_id=user_id,
        details={"scenario_version": updated.scenario_version, "body_updated": True},
    )
    view = _view_from_row(updated)
    return OrgScenarioView(
        id=view.id,
        organization_id=view.organization_id,
        name=view.name,
        description=view.description,
        kind=view.kind,
        status=view.status,
        scenario_version=view.scenario_version,
        body_json=view.body_json,
        tags=view.tags,
        created_by=view.created_by,
        created_at=view.created_at,
        updated_at=view.updated_at,
        is_runnable=result.status == "valid",
        last_validation_summary=updated.last_validation_summary,
        last_validated_at=(
            updated.last_validated_at.isoformat()
            if updated.last_validated_at
            else None
        ),
    )


async def validate_scenario_for_org(
    db: AsyncSession,
    *,
    org_id: str,
    scenario_id: str,
    body: dict[str, Any] | None = None,
    campaign_variables: dict[str, Any] | None = None,
):
    from services.org_scenario_validation.validator import (
        persist_org_validation_summary,
        validate_org_scenario,
    )

    row = await repo.get_org_scenario(db, scenario_id)
    if row is None:
        raise OrgScenarioNotFoundError()
    _assert_scenario_read_access(row, org_id)

    result, _normalized = await validate_org_scenario(
        db,
        row,
        body=body,
        campaign_variables=campaign_variables,
    )
    updated = await persist_org_validation_summary(db, row, result)
    return result, updated
