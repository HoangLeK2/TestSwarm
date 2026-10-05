"""DF-011: Execution coordinator tables.

Creates:
  - executions        — central coordinator (run_type, status, device_config, loop_config, error_config)
  - execution_devices — n-n join between executions and devices
  - execution_results — per-device result tracking (passed_steps, failed_steps, run_time_sec)

Adds:
  - content_items.execution_id FK → executions.id
"""
from sqlalchemy import text


async def upgrade(conn) -> None:
    # ── 1. executions ──────────────────────────────────────────────────────────
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS executions (
            id            VARCHAR(36)  PRIMARY KEY,
            run_type      VARCHAR(50)  NOT NULL,
            status        VARCHAR(20)  NOT NULL DEFAULT 'pending',
            campaign_id   VARCHAR(36)  REFERENCES campaigns(id)  ON DELETE SET NULL,
            scenario_id   VARCHAR(36)  REFERENCES scenarios(id)  ON DELETE SET NULL,
            device_config JSONB        NOT NULL DEFAULT '{}',
            loop_config   JSONB        NOT NULL DEFAULT '{}',
            error_config  JSONB        NOT NULL DEFAULT '{}',
            meta          JSONB        NOT NULL DEFAULT '{}',
            user_id       VARCHAR(36)  REFERENCES users(id)      ON DELETE SET NULL,
            created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            started_at    TIMESTAMPTZ,
            finished_at   TIMESTAMPTZ
        )
    """))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_executions_run_type ON executions(run_type)"))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_executions_status   ON executions(status)"))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_executions_campaign ON executions(campaign_id)"))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_executions_scenario ON executions(scenario_id)"))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_executions_user     ON executions(user_id)"))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_executions_created  ON executions(created_at)"))

    # ── 2. execution_devices (n-n join) ────────────────────────────────────────
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS execution_devices (
            id           VARCHAR(36) PRIMARY KEY,
            execution_id VARCHAR(36) NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
            device_id    VARCHAR(36) NOT NULL REFERENCES devices(id)    ON DELETE CASCADE,
            CONSTRAINT uq_execution_device UNIQUE (execution_id, device_id)
        )
    """))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_exec_devices_exec   ON execution_devices(execution_id)"))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_exec_devices_device ON execution_devices(device_id)"))

    # ── 3. execution_results (per-device results) ──────────────────────────────
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS execution_results (
            id           VARCHAR(36)  PRIMARY KEY,
            execution_id VARCHAR(36)  NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
            device_id    VARCHAR(36)  NOT NULL REFERENCES devices(id)    ON DELETE CASCADE,
            status       VARCHAR(20)  NOT NULL DEFAULT 'pending',
            run_time_sec FLOAT,
            passed_steps JSONB        NOT NULL DEFAULT '[]',
            failed_steps JSONB        NOT NULL DEFAULT '[]',
            error_detail TEXT,
            started_at   TIMESTAMPTZ,
            finished_at  TIMESTAMPTZ,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_execution_result_exec_device UNIQUE (execution_id, device_id)
        )
    """))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_exec_results_execution "
        "ON execution_results(execution_id)"))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_exec_results_device "
        "ON execution_results(device_id)"))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_exec_results_status "
        "ON execution_results(status)"))

    # ── 4. content_items.execution_id FK ──────────────────────────────────────
    await conn.execute(text("""
        ALTER TABLE content_items
        ADD COLUMN IF NOT EXISTS execution_id VARCHAR(36)
            REFERENCES executions(id) ON DELETE SET NULL
    """))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_ci_execution_id ON content_items(execution_id)"))
