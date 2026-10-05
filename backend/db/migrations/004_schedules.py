"""DF-008: Scheduler & Cron System — schedules + schedule_runs tables."""
from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schedules (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                description TEXT DEFAULT '',
                target_type VARCHAR(20) NOT NULL,
                target_id VARCHAR(36),
                inline_steps JSON,
                inline_variables JSON DEFAULT '{}',
                device_group_id VARCHAR(36) REFERENCES device_groups(id) ON DELETE SET NULL,
                filter_state VARCHAR(20) DEFAULT 'READY',
                filter_model VARCHAR(100),
                max_devices INTEGER,
                cron_expression VARCHAR(100) NOT NULL,
                timezone VARCHAR(50) DEFAULT 'Asia/Ho_Chi_Minh',
                random_delay_min INTEGER DEFAULT 0,
                random_delay_max INTEGER DEFAULT 0,
                stagger_devices BOOLEAN DEFAULT FALSE,
                stagger_interval_seconds INTEGER DEFAULT 60,
                is_enabled BOOLEAN DEFAULT TRUE,
                last_run_at TIMESTAMPTZ,
                next_run_at TIMESTAMPTZ,
                run_count INTEGER DEFAULT 0,
                user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_schedules_enabled ON schedules(is_enabled)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_schedules_next_run ON schedules(next_run_at)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_schedules_user ON schedules(user_id)"
        )
    )
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schedule_runs (
                id VARCHAR(36) PRIMARY KEY,
                schedule_id VARCHAR(36) NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
                status VARCHAR(20) DEFAULT 'pending',
                started_at TIMESTAMPTZ DEFAULT NOW(),
                finished_at TIMESTAMPTZ,
                devices_dispatched INTEGER DEFAULT 0,
                devices_succeeded INTEGER DEFAULT 0,
                devices_failed INTEGER DEFAULT 0,
                task_ids JSON DEFAULT '[]',
                error_message TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_schedule_runs_schedule ON schedule_runs(schedule_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_schedule_runs_status ON schedule_runs(status)"
        )
    )
