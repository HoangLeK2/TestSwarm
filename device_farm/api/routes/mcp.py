from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.deps import CurrentUser, require_permission
from api.auth.rbac import is_superadmin
from mcp import server as mcp_server
from mcp import token_store

router = APIRouter(prefix="/mcp", tags=["mcp"])


def _user_org_id(user: CurrentUser) -> str | None:
    raw = getattr(user, "org_id", None)
    return str(raw) if raw else None


class McpTokenCreate(BaseModel):
    name: str = Field(default="MCP agent token", max_length=120)
    scope_type: Literal["device", "user"]
    scope_ref: str | None = Field(default=None, max_length=200)
    preview_consent: bool = False


@router.get(
    "/tools",
    dependencies=[Depends(require_permission("mcp", "read"))],
)
async def list_mcp_tools():
    return {
        "preview": True,
        "contract_version": mcp_server.CONTRACT_VERSION,
        "warning": mcp_server.PREVIEW_WARNING,
        "tools": [
            mcp_server._tool_descriptor(name, meta)
            for name, meta in mcp_server.TOOL_DEFS.items()
        ],
        "error_catalog": mcp_server.ERROR_CATALOG,
    }


@router.get(
    "/audit-log",
    dependencies=[Depends(require_permission("mcp", "read"))],
)
async def list_mcp_audit_log(
    user: CurrentUser,
    tool_name: str | None = None,
    session_id: str | None = None,
    agent_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    entries: list[dict[str, Any]] = []
    user_org_id = _user_org_id(user)
    superadmin = is_superadmin(user)
    path = mcp_server._audit_log_path()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if not superadmin and (not user_org_id or entry.get("org_id") != user_org_id):
                continue
            if tool_name and entry.get("tool_name") != tool_name:
                continue
            if session_id and entry.get("session_id") != session_id:
                continue
            if agent_id and entry.get("agent_id") != agent_id:
                continue
            entries.append(entry)
    entries.sort(key=lambda item: item.get("started_at") or 0, reverse=True)
    total = len(entries)
    sliced = entries[offset : offset + limit]
    return {
        "preview": True,
        "contract_version": mcp_server.CONTRACT_VERSION,
        "total": total,
        "offset": offset,
        "limit": limit,
        "entries": sliced,
    }


@router.get(
    "/tokens",
    dependencies=[Depends(require_permission("mcp", "read"))],
)
async def list_mcp_tokens(user: CurrentUser, include_revoked: bool = False):
    superadmin = is_superadmin(user)
    user_org_id = _user_org_id(user)
    if superadmin:
        records = token_store.list_tokens(include_revoked=include_revoked)
    elif user_org_id:
        records = token_store.list_tokens(
            include_revoked=include_revoked,
            org_id=user_org_id,
        )
    else:
        records = []
    return {
        "preview": True,
        "contract_version": mcp_server.CONTRACT_VERSION,
        "tokens": [
            record.public_dict(include_internal=superadmin)
            for record in records
        ],
    }


@router.post(
    "/tokens",
    dependencies=[Depends(require_permission("mcp", "manage"))],
    status_code=status.HTTP_201_CREATED,
)
async def create_mcp_token(body: McpTokenCreate, user: CurrentUser):
    if not body.preview_consent:
        raise HTTPException(
            status_code=400,
            detail={"code": "MCP_PREVIEW_CONSENT_REQUIRED"},
        )
    org_id = _user_org_id(user)
    if not is_superadmin(user) and not org_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "MCP_ORG_CONTEXT_REQUIRED"},
        )
    record, plaintext = token_store.create_token(
        name=body.name,
        scope_type=body.scope_type,
        scope_ref=body.scope_ref,
        owner_user_id=str(user.id),
        org_id=org_id,
    )
    return {
        "preview": True,
        "contract_version": mcp_server.CONTRACT_VERSION,
        "token": plaintext,
        "record": record.public_dict(),
        "warning": "Store this token now; Device Farm only keeps its hash.",
    }


@router.post(
    "/tokens/{token_id}/revoke",
    dependencies=[Depends(require_permission("mcp", "manage"))],
)
async def revoke_mcp_token(token_id: str, user: CurrentUser):
    superadmin = is_superadmin(user)
    org_id = None if superadmin else _user_org_id(user)
    if org_id is None and not superadmin:
        raise HTTPException(status_code=404, detail={"code": "MCP_TOKEN_NOT_FOUND"})
    if not token_store.revoke_token(token_id, org_id=org_id):
        raise HTTPException(status_code=404, detail={"code": "MCP_TOKEN_NOT_FOUND"})
    return {"ok": True, "token_id": token_id}
