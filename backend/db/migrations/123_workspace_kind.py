"""123 — Workspace kind: only a pool workspace may own a relay agent.

A relay agent inherits its workspace from the activation code that enrolled it,
and that workspace becomes `devices.managed_by_org_id` for every phone handed
out from the host. Enrol an agent with a tenant's code and that tenant silently
becomes the manager of phones allocated to other tenants. Nothing in the schema
could tell the two roles apart, so nothing could refuse it.
"""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            "ALTER TABLE organizations "
            "ADD COLUMN IF NOT EXISTS kind VARCHAR(20) NOT NULL DEFAULT 'tenant'"
        )
    )
    # Existing pools are self-evident: a workspace already managing phones on
    # behalf of a *different* workspace is the one running the relay host.
    # Everything else stays 'tenant' — an operator marks further pools by hand.
    await conn.execute(
        text(
            """
            UPDATE organizations
               SET kind = 'pool'
             WHERE id IN (
                 SELECT DISTINCT managed_by_org_id
                   FROM devices
                  WHERE managed_by_org_id IS NOT NULL
                    AND org_id IS NOT NULL
                    AND managed_by_org_id <> org_id
             )
            """
        )
    )
