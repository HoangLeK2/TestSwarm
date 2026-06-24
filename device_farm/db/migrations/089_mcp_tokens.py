from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS mcp_tokens (
            id              VARCHAR(24)  PRIMARY KEY,
            name            VARCHAR(120) NOT NULL,
            hashed_value    VARCHAR(64)  NOT NULL UNIQUE,
            scope_type      VARCHAR(16)  NOT NULL,
            scope_ref       VARCHAR(200),
            owner_user_id   VARCHAR(36)  REFERENCES users(id) ON DELETE SET NULL,
            org_id          VARCHAR(36)  REFERENCES organizations(id) ON DELETE SET NULL,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            revoked_at      TIMESTAMPTZ
        )
    """))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_mcp_tokens_hashed_value "
        "ON mcp_tokens (hashed_value)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_mcp_tokens_org_active "
        "ON mcp_tokens (org_id) WHERE revoked_at IS NULL"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_mcp_tokens_owner_active "
        "ON mcp_tokens (owner_user_id) WHERE revoked_at IS NULL"
    ))

    legacy_path = _legacy_json_path()
    if legacy_path is None:
        return

    try:
        raw = json.loads(legacy_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(raw, list):
        return

    for item in raw:
        if not isinstance(item, dict):
            continue
        token_id = str(item.get("id") or "").strip()
        hashed_value = str(item.get("hashed_value") or "").strip()
        if not token_id or not hashed_value:
            continue
        created_at = _epoch_to_timestamptz(item.get("created_at"))
        revoked_at = _epoch_to_timestamptz(item.get("revoked_at"))
        await conn.execute(
            text("""
                INSERT INTO mcp_tokens (
                    id, name, hashed_value, scope_type, scope_ref,
                    owner_user_id, org_id, created_at, revoked_at
                ) VALUES (
                    :id, :name, :hashed_value, :scope_type, :scope_ref,
                    :owner_user_id, :org_id, :created_at, :revoked_at
                )
                ON CONFLICT (id) DO NOTHING
            """),
            {
                "id": token_id,
                "name": str(item.get("name") or "MCP token")[:120],
                "hashed_value": hashed_value,
                "scope_type": str(item.get("scope_type") or "user")[:16],
                "scope_ref": item.get("scope_ref"),
                "owner_user_id": item.get("owner_user_id"),
                "org_id": item.get("org_id"),
                "created_at": created_at,
                "revoked_at": revoked_at,
            },
        )


def _legacy_json_path() -> Path | None:
    configured = (os.environ.get("DEVICE_FARM_MCP_TOKEN_STORE") or "").strip()
    if configured:
        path = Path(configured)
        return path if path.exists() else None
    for candidate in (
        Path("/app/mcp/mcp_tokens.json"),
        Path(__file__).resolve().parents[2] / "mcp" / "mcp_tokens.json",
    ):
        if candidate.exists():
            return candidate
    return None


def _epoch_to_timestamptz(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except Exception:
        return None
