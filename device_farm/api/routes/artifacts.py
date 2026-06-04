"""Artifact signed URL routes (DF-T-06-012)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from api.deps import CurrentUser, DB, require_permission
from services.content.artifact_service import presigned_artifact_url

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


class ArtifactUrlOut(BaseModel):
    url: str | None
    expires_at: str
    content_type: str
    size_bytes: int | None = None
    proxy_required: bool = False


@router.get(
    "/{artifact_id}/content",
    dependencies=[Depends(require_permission("executions", "read"))],
)
async def get_artifact_content(
    artifact_id: str,
    db: DB,
    user: CurrentUser,
):
    """Stream artifact bytes through the API (browser-safe; avoids internal MinIO hosts)."""
    from db.models.content import ExecutionArtifact
    from db.models.execution import Execution
    from services import minio_store
    from tenancy.enforce import enforce_tenant

    row = await db.get(ExecutionArtifact, artifact_id)
    if row is None:
        raise HTTPException(404, "Artifact not found")
    if row.object_deleted:
        raise HTTPException(410, "Artifact object deleted")

    execution = await db.get(Execution, row.execution_id)
    if execution is None:
        raise HTTPException(404, "Execution not found")
    enforce_tenant(execution, user)

    payload = minio_store.get_object_bytes(row.object_key)
    if payload is None:
        raise HTTPException(410, "Artifact expired or unavailable")
    return Response(content=payload, media_type=row.content_type_mime)


@router.get(
    "/{artifact_id}/url",
    response_model=ArtifactUrlOut,
    dependencies=[Depends(require_permission("executions", "read"))],
)
async def get_artifact_signed_url(
    artifact_id: str,
    db: DB,
    user: CurrentUser,
    ttl_seconds: int = 3600,
):
    from db.models.content import ExecutionArtifact
    from sqlalchemy import select
    from tenancy.enforce import enforce_tenant

    row = await db.get(ExecutionArtifact, artifact_id)
    if row is None:
        raise HTTPException(404, "Artifact not found")
    if row.object_deleted:
        raise HTTPException(410, "Artifact object deleted")

    from db.models.execution import Execution

    execution = await db.get(Execution, row.execution_id)
    if execution is None:
        raise HTTPException(404, "Execution not found")
    enforce_tenant(execution, user)

    signed = presigned_artifact_url(
        row.object_key,
        ttl_seconds=ttl_seconds,
        content_type=row.content_type_mime,
    )
    return ArtifactUrlOut(
        url=signed["url"],
        expires_at=signed["expires_at"],
        content_type=row.content_type_mime,
        size_bytes=row.size_bytes,
        proxy_required=signed.get("proxy_required", False),
    )
