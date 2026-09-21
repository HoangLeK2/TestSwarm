"""136 - Restore MH1-MH19 names after relay auto-claim preservation."""
from __future__ import annotations

from importlib import import_module

from sqlalchemy import text

_rename_migration = import_module("db.migrations.135_rename_mh_group_devices")
EXPECTED_MH_DEVICES = _rename_migration.EXPECTED_MH_DEVICES
_mh_group_exists = _rename_migration._mh_group_exists
_table_exists = _rename_migration._table_exists
_validate_expected_members = _rename_migration._validate_expected_members


async def upgrade(conn) -> None:
    for table in ("devices", "device_groups", "device_group_members"):
        if not await _table_exists(conn, table):
            return

    if not await _mh_group_exists(conn):
        return

    await _validate_expected_members(conn)

    for device_id, serial, new_name in EXPECTED_MH_DEVICES:
        await conn.execute(
            text(
                """
                UPDATE devices
                   SET name = :new_name,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE id = :device_id
                   AND serial = :serial
                   AND COALESCE(name, '') <> :new_name
                """
            ),
            {"device_id": device_id, "serial": serial, "new_name": new_name},
        )
