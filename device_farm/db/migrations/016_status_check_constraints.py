"""016 — Add CHECK constraints for all status/enum string fields."""
from __future__ import annotations


_CHECKS = [
    ("users", "check_user_role", "role IN ('admin', 'operator')"),
    (
        "campaigns",
        "check_campaign_status",
        "status IN ('idle', 'running', 'paused', 'completed', 'failed')",
    ),
    (
        "executions",
        "check_execution_status",
        "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
    ),
    (
        "execution_results",
        "check_exec_result_status",
        "status IN ('pending', 'running', 'passed', 'failed', 'error')",
    ),
    (
        "accounts",
        "check_account_status",
        "status IN ('active', 'cooldown', 'banned', 'disabled')",
    ),
    (
        "execution_dlq",
        "check_dlq_status",
        "status IN ('pending', 'retrying', 'resolved', 'dismissed')",
    ),
    (
        "schedule_runs",
        "check_schedule_run_status",
        "status IN ('pending', 'running', 'completed', 'failed', 'partial')",
    ),
    (
        "schedules",
        "check_schedule_target_type",
        "target_type IN ('campaign', 'template', 'fleet')",
    ),
    (
        "mcp_sessions",
        "check_mcp_status",
        "status IN ('active', 'ended')",
    ),
    (
        "content_exports",
        "check_content_export_status",
        "status IN ('pending', 'running', 'completed', 'failed', 'ready')",
    ),
]


async def upgrade(conn) -> None:
    for table, name, expr in _CHECKS:
        await conn.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = '{table}'
                ) AND NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = '{name}'
                ) THEN
                    ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expr});
                END IF;
            END $$;
            """
        )
