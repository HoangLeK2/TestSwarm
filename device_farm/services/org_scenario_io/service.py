"""Template clone and export orchestration (DF-T-04-005)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.crud import org_scenario as repo
from db.crud.scenario_template import get_template as get_scenario_template_row
from db.models.enums import ScenarioKind
from services.org_scenario.errors import OrgScenarioDuplicateNameError, OrgScenarioNotFoundError
from services.org_scenario.service import _assert_scenario_read_access, create_scenario
from services.org_scenario_io.importer import ImportResult
from services.org_scenario_io.serializer import ScenarioSerializer, serialize_payload


def _tags_from_row(row) -> list[str]:
    loaded = row.__dict__.get("tags")
    if not loaded:
        return []
    return sorted({t.tag for t in loaded if t.tag})


@dataclass(frozen=True, slots=True)
class ExportBundle:
    payload: dict[str, Any]
    content: bytes
    media_type: str
    filename: str


async def export_scenario_for_org(
    db: AsyncSession,
    *,
    org_id: str,
    scenario_id: str,
    export_format: str = "yaml",
    version: int | None = None,
) -> ExportBundle:
    row = await repo.get_org_scenario(db, scenario_id)
    if row is None:
        raise OrgScenarioNotFoundError()
    _assert_scenario_read_access(row, org_id)
    tags = _tags_from_row(row)
    serializer = ScenarioSerializer(db, org_id=row.org_id)
    payload = await serializer.build_payload(row, tags=tags, version=version)
    content, media_type = serialize_payload(payload, fmt=export_format)
    ext = "json" if export_format == "json" else "yaml"
    safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in row.name)[:80]
    return ExportBundle(
        payload=payload,
        content=content,
        media_type=media_type,
        filename=f"{safe_name}.{ext}",
    )


async def list_system_templates(db: AsyncSession):
    from services.org_scenario.service import list_system_template_views

    return await list_system_template_views(db)


def _template_body_json(template) -> dict[str, Any]:
    steps = template.steps if isinstance(template.steps, list) else []
    nodes = template.nodes if isinstance(template.nodes, list) else []
    edges = template.edges if isinstance(template.edges, list) else []
    variables = template.variables if isinstance(template.variables, dict) else {}
    body: dict[str, Any] = {"variables": variables}
    # Runtime / org library: sequence only. Template graph mirror (nodes/edges) is
    # stored on scenario_templates for a future flow editor — not cloned to org.
    if steps:
        body["steps"] = steps
        return body
    if nodes or edges:
        body["nodes"] = nodes
        body["edges"] = edges
    return body


def _template_kind(template) -> str:
    steps = template.steps if isinstance(template.steps, list) else []
    if steps:
        return ScenarioKind.SEQUENCE.value
    nodes = template.nodes if isinstance(template.nodes, list) else []
    edges = template.edges if isinstance(template.edges, list) else []
    if nodes or edges:
        return ScenarioKind.GRAPH.value
    return ScenarioKind.SEQUENCE.value


def _template_tags(template) -> list[str]:
    raw = str(getattr(template, "tags", "") or "")
    return [part.strip() for part in raw.split(",") if part.strip()]


async def clone_scenario_template_to_org(
    db: AsyncSession,
    *,
    template_id: str,
    target_org_id: str,
    name_override: str | None,
    created_by: str | None,
) -> ImportResult:
    """Clone a row from scenario_templates into the target org scenario library."""
    template = await get_scenario_template_row(db, template_id)
    if template is None:
        raise OrgScenarioNotFoundError()

    display = str(getattr(template, "display_name", "") or "").strip()
    clone_name = (name_override or display or template.name or "").strip()
    if not clone_name:
        raise OrgScenarioDuplicateNameError(template.name)

    view = await create_scenario(
        db,
        org_id=target_org_id,
        name=clone_name,
        kind=_template_kind(template),
        description=str(template.description or ""),
        body_json=_template_body_json(template),
        tags=_template_tags(template),
        created_by=created_by,
    )
    return ImportResult(
        scenario_id=view.id,
        name=view.name,
        kind=view.kind,
        status=view.status,
        scenario_version=view.scenario_version,
        warnings=[],
        created_stub_names=[],
    )


async def clone_system_template(
    db: AsyncSession,
    *,
    template_id: str,
    target_org_id: str,
    name_override: str | None,
    created_by: str | None,
) -> ImportResult:
    """Backward-compatible alias — clones from scenario_templates, not __system org."""
    return await clone_scenario_template_to_org(
        db,
        template_id=template_id,
        target_org_id=target_org_id,
        name_override=name_override,
        created_by=created_by,
    )
