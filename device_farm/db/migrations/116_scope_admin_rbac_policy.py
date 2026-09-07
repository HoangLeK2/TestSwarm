"""116 — Scope admin RBAC to workspace administration.

Superadmin remains the only wildcard/full-access role. Admin is limited to
workspace administration capabilities used by the admin console.
"""

from __future__ import annotations

from sqlalchemy import text


_ADMIN_POLICY_ROWS = [
    ("admin", "*", "organizations", "(read|create|update|delete|manage)"),
    ("admin", "*", "devices", "(read|manage)"),
    ("admin", "*", "relay-agents", "(read|create|update|delete|manage)"),
    ("admin", "*", "analytics", "read"),
]


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            DELETE FROM casbin_rule
             WHERE ptype = 'p'
               AND v0 = 'admin'
               AND COALESCE(v1, '') = '*'
               AND COALESCE(v2, '') = '*'
            """
        )
    )

    for role, domain, obj, action in _ADMIN_POLICY_ROWS:
        await conn.execute(
            text(
                """
                INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, v4, v5)
                SELECT
                    'p',
                    CAST(:role AS VARCHAR(255)),
                    CAST(:domain AS VARCHAR(255)),
                    CAST(:obj AS VARCHAR(255)),
                    CAST(:action AS VARCHAR(255)),
                    NULL,
                    NULL
                WHERE NOT EXISTS (
                    SELECT 1 FROM casbin_rule
                     WHERE ptype = 'p'
                       AND COALESCE(v0, '') = COALESCE(CAST(:role AS VARCHAR(255)), '')
                       AND COALESCE(v1, '') = COALESCE(CAST(:domain AS VARCHAR(255)), '')
                       AND COALESCE(v2, '') = COALESCE(CAST(:obj AS VARCHAR(255)), '')
                       AND COALESCE(v3, '') = COALESCE(CAST(:action AS VARCHAR(255)), '')
                       AND COALESCE(v4, '') = ''
                       AND COALESCE(v5, '') = ''
                )
                """
            ),
            {
                "role": role,
                "domain": domain,
                "obj": obj,
                "action": action,
            },
        )

    await conn.execute(
        text(
            """
            UPDATE casbin_policy_revision
               SET revision = revision + 1,
                   updated_at = NOW()
             WHERE id = 1
            """
        )
    )
