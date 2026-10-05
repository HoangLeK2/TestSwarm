"""Enforce immutable AI Device Lab identities and approved snapshots."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE OR REPLACE FUNCTION reject_ai_lab_immutable_update()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION '% rows are immutable', TG_TABLE_NAME
                    USING ERRCODE = 'integrity_constraint_violation';
            END;
            $$ LANGUAGE plpgsql
            """
        )
    )
    await conn.execute(
        text("DROP TRIGGER IF EXISTS app_builds_immutable ON app_builds")
    )
    await conn.execute(
        text(
            """
            CREATE TRIGGER app_builds_immutable
            BEFORE UPDATE OR DELETE ON app_builds
            FOR EACH ROW EXECUTE FUNCTION reject_ai_lab_immutable_update()
            """
        )
    )
    await conn.execute(
        text(
            "DROP TRIGGER IF EXISTS scenario_approvals_immutable ON scenario_approvals"
        )
    )
    await conn.execute(
        text(
            """
            CREATE TRIGGER scenario_approvals_immutable
            BEFORE UPDATE OR DELETE ON scenario_approvals
            FOR EACH ROW EXECUTE FUNCTION reject_ai_lab_immutable_update()
            """
        )
    )
