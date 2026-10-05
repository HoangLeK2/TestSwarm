"""024 — Prevent duplicate open DLQ entries per execution/device.

Adds a partial unique index for open entries only:
  (execution_id, device_serial) WHERE status IN ('pending','retrying')
"""

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_dlq_open_execution_device
            ON execution_dlq (execution_id, device_serial)
            WHERE status IN ('pending','retrying');
            """
        )
    )


async def downgrade(conn) -> None:
    await conn.execute(text("DROP INDEX IF EXISTS uq_dlq_open_execution_device;"))
