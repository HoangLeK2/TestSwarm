"""120 - Allow workspace admins to operate assigned workspaces.

Workspace admins still do not receive platform-wide ``users`` access. These
permissions apply inside the effective organization domain selected by the UI.
"""

from __future__ import annotations

from sqlalchemy import text


_ADMIN_OPERATIONAL_POLICY_ROWS = [
    ("admin", "*", "devices", "(read|create|update|delete|execute|manage)"),
    ("admin", "*", "campaigns", "(read|create|update|delete|execute|manage)"),
    ("admin", "*", "executions", "(read|create|update|delete|execute|manage)"),
    ("admin", "*", "scenario-templates", "(read|create|update|delete|manage)"),
    ("admin", "*", "scenarios", "(read|create|update|delete|manage)"),
    ("admin", "*", "accounts", "(read|create|update|delete|execute|manage)"),
    ("admin", "*", "account-groups", "(read|create|update|delete|execute|manage)"),
    ("admin", "*", "device-groups", "(read|create|update|delete|manage)"),
    ("admin", "*", "schedules", "(read|create|update|delete|execute|manage)"),
    ("admin", "*", "relay-agents", "(read|create|update|delete|manage)"),
    ("admin", "*", "notifications", "(read|create|update|delete|execute|manage)"),
    ("admin", "*", "content", "(read|create|update|delete|manage)"),
    ("admin", "*", "analytics", "read"),
    ("admin", "*", "mcp", "(read|manage)"),
]


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            DELETE FROM casbin_rule
             WHERE ptype = 'p'
               AND v0 = 'admin'
               AND COALESCE(v1, '') = '*'
               AND COALESCE(v2, '') IN (
                   'devices',
                   'campaigns',
                   'executions',
                   'scenario-templates',
                   'scenarios',
                   'accounts',
                   'account-groups',
                   'device-groups',
                   'schedules',
                   'relay-agents',
                   'notifications',
                   'content',
                   'analytics',
                   'mcp'
               )
            """
        )
    )

    for role, domain, obj, action in _ADMIN_OPERATIONAL_POLICY_ROWS:
        await conn.execute(
            text(
                """
                INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, v4, v5)
                VALUES (
                    'p',
                    CAST(:role AS VARCHAR(255)),
                    CAST(:domain AS VARCHAR(255)),
                    CAST(:obj AS VARCHAR(255)),
                    CAST(:action AS VARCHAR(255)),
                    NULL,
                    NULL
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
