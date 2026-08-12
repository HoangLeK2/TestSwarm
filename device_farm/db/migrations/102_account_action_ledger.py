"""Add the tenant-scoped, append-only account action ledger."""
from sqlalchemy import text


async def upgrade(conn) -> None:
    postgresql = conn.dialect.name == "postgresql"
    json_type = "JSONB" if postgresql else "JSON"
    empty_object = "'{}'::jsonb" if postgresql else "'{}'"
    empty_array = "'[]'::jsonb" if postgresql else "'[]'"
    timestamp_type = "TIMESTAMPTZ" if postgresql else "DATETIME"
    transition_id = "BIGSERIAL PRIMARY KEY" if postgresql else "INTEGER PRIMARY KEY AUTOINCREMENT"

    await conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS account_actions (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            account_id VARCHAR(36) NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            execution_id VARCHAR(36) NULL REFERENCES executions(id) ON DELETE SET NULL,
            step_id VARCHAR(128) NULL,
            action_key VARCHAR(64) NOT NULL,
            action_type VARCHAR(64) NOT NULL,
            platform VARCHAR(50) NOT NULL,
            status VARCHAR(24) NOT NULL,
            status_rank INTEGER NOT NULL,
            target {json_type} NOT NULL DEFAULT {empty_object},
            result {json_type} NOT NULL DEFAULT {empty_object},
            artifact_refs {json_type} NOT NULL DEFAULT {empty_array},
            started_at {timestamp_type} NULL,
            completed_at {timestamp_type} NULL,
            last_transition_at {timestamp_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_at {timestamp_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {timestamp_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_account_actions_org_key UNIQUE (org_id, action_key)
        )
    """))
    await conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS account_action_transitions (
            id {transition_id},
            action_id VARCHAR(36) NOT NULL REFERENCES account_actions(id) ON DELETE CASCADE,
            org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            from_status VARCHAR(24) NULL,
            to_status VARCHAR(24) NOT NULL,
            status_rank INTEGER NOT NULL,
            reason VARCHAR(255) NULL,
            details {json_type} NOT NULL DEFAULT {empty_object},
            occurred_at {timestamp_type} NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    await conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS account_action_attempts (
            id {transition_id},
            action_id VARCHAR(36) NOT NULL REFERENCES account_actions(id) ON DELETE CASCADE,
            org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            attempt_no INTEGER NOT NULL,
            outcome VARCHAR(32) NOT NULL,
            error_code VARCHAR(64) NULL,
            details {json_type} NOT NULL DEFAULT {empty_object},
            artifact_refs {json_type} NOT NULL DEFAULT {empty_array},
            started_at {timestamp_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            ended_at {timestamp_type} NULL,
            CONSTRAINT uq_account_action_attempt UNIQUE (org_id, action_id, attempt_no)
        )
    """))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_account_actions_account_time ON account_actions (org_id, account_id, created_at DESC, id DESC)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_account_actions_active ON account_actions (status, last_transition_at, id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_account_action_transitions_action ON account_action_transitions (action_id, id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_account_action_attempts_action ON account_action_attempts (action_id, attempt_no)"))
