"""076 — Epic 05 scheduling completion fields."""
from sqlalchemy import text


async def upgrade(conn) -> None:
    schedule_columns = [
        "ALTER TABLE schedules ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'enabled'",
        "ALTER TABLE schedules ADD COLUMN IF NOT EXISTS schedule_kind VARCHAR(20) DEFAULT 'cron'",
        "ALTER TABLE schedules ADD COLUMN IF NOT EXISTS run_at TIMESTAMPTZ",
        "ALTER TABLE schedules ADD COLUMN IF NOT EXISTS skip_dates JSON DEFAULT '[]'",
        "ALTER TABLE schedules ADD COLUMN IF NOT EXISTS skip_windows JSON DEFAULT '[]'",
        "ALTER TABLE schedules ADD COLUMN IF NOT EXISTS misfire_policy VARCHAR(20) DEFAULT 'skip'",
        "ALTER TABLE schedules ADD COLUMN IF NOT EXISTS priority VARCHAR(20) DEFAULT 'normal'",
        "ALTER TABLE schedules ADD COLUMN IF NOT EXISTS max_concurrent_per_device INTEGER DEFAULT 1",
        "ALTER TABLE schedules ADD COLUMN IF NOT EXISTS account_rate_limit_per_hour INTEGER",
        "ALTER TABLE schedules ADD COLUMN IF NOT EXISTS quota_policy JSON DEFAULT '{}'",
        "ALTER TABLE schedules ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ",
        "ALTER TABLE schedules ALTER COLUMN cron_expression DROP NOT NULL",
    ]
    for statement in schedule_columns:
        await conn.execute(text(statement))

    run_columns = [
        "ALTER TABLE schedule_runs ADD COLUMN IF NOT EXISTS trigger_source VARCHAR(20) DEFAULT 'cron'",
        "ALTER TABLE schedule_runs ADD COLUMN IF NOT EXISTS scheduled_at TIMESTAMPTZ",
        "ALTER TABLE schedule_runs ADD COLUMN IF NOT EXISTS deferred_until TIMESTAMPTZ",
        "ALTER TABLE schedule_runs ADD COLUMN IF NOT EXISTS was_catch_up BOOLEAN DEFAULT FALSE",
        "ALTER TABLE schedule_runs ADD COLUMN IF NOT EXISTS execution_id VARCHAR(36)",
        "ALTER TABLE schedule_runs ADD COLUMN IF NOT EXISTS workflow_ids JSON DEFAULT '[]'",
        "ALTER TABLE schedule_runs ADD COLUMN IF NOT EXISTS error_code VARCHAR(80)",
    ]
    for statement in run_columns:
        await conn.execute(text(statement))

    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_schedules_status ON schedules(status)",
        "CREATE INDEX IF NOT EXISTS idx_schedule_runs_execution ON schedule_runs(execution_id)",
        "CREATE INDEX IF NOT EXISTS idx_schedule_runs_source ON schedule_runs(trigger_source)",
        "CREATE INDEX IF NOT EXISTS idx_schedule_runs_scheduled_at ON schedule_runs(scheduled_at)",
    ]
    for statement in indexes:
        await conn.execute(text(statement))
