"""Preview execution list API (DF-T-04-018)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import CurrentUser, DB, require_permission
from api.schemas.preview import PreviewListItem, PreviewListResponse
from db.crud.content import count_by_execution
from db.crud.execution import list_executions
from db.crud.execution import list_execution_devices
from db.models.enums import ExecutionKind

router = APIRouter(prefix="/preview", tags=["preview"])


def _parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_SINCE", "message": "since must be ISO-8601 datetime"},
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@router.get(
    "",
    response_model=PreviewListResponse,
    dependencies=[Depends(require_permission("scenarios", "read"))],
)
async def list_previews(
    db: DB,
    user: CurrentUser,
    org: str | None = Query(None, alias="org"),
    user_filter: str | None = Query(None, alias="user"),
    since: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    org_id = org or getattr(user, "org_id", None)
    if not org_id:
        raise HTTPException(status_code=404, detail={"code": "NO_ORGANIZATION"})

    since_dt = _parse_since(since)
    target_user = user_filter or user.id

    items, total = await list_executions(
        db,
        org_id=org_id,
        user_id=target_user,
        kind=ExecutionKind.PREVIEW.value,
        since=since_dt,
        limit=limit,
        offset=offset,
    )

    out: list[PreviewListItem] = []
    for execution in items:
        meta = execution.meta or {}
        devices = await list_execution_devices(db, execution.id)
        device_id = devices[0].id if devices else None
        artifact_count = await count_by_execution(db, execution.id)
        out.append(
            PreviewListItem(
                execution_id=execution.id,
                status=execution.status,
                org_scenario_id=meta.get("org_scenario_id"),
                org_scenario_name=meta.get("org_scenario_name"),
                device_id=device_id,
                created_at=execution.created_at,
                finished_at=execution.finished_at,
                artifact_count=artifact_count,
                artifacts_purged=bool(meta.get("artifacts_purged")),
                warnings=list(meta.get("preview_warnings") or []),
            )
        )

    return PreviewListResponse(total=total, items=out)
