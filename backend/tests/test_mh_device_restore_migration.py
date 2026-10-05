from __future__ import annotations

from importlib import import_module

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

rename_migration = import_module("db.migrations.135_rename_mh_group_devices")
restore_migration = import_module("db.migrations.136_restore_mh_group_device_names")


async def _create_tables(conn) -> None:
    await conn.execute(
        text("CREATE TABLE device_groups (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255))")
    )
    await conn.execute(
        text(
            "CREATE TABLE devices ("
            "id VARCHAR(36) PRIMARY KEY, serial VARCHAR(128) NOT NULL, "
            "name VARCHAR(255), updated_at TIMESTAMP)"
        )
    )
    await conn.execute(
        text(
            "CREATE TABLE device_group_members ("
            "id VARCHAR(36) PRIMARY KEY, group_id VARCHAR(36) NOT NULL, "
            "device_id VARCHAR(36) NOT NULL)"
        )
    )


async def _seed_expected_group_with_serial_names(conn) -> None:
    await conn.execute(
        text("INSERT INTO device_groups (id, name) VALUES (:id, 'Mh')"),
        {"id": rename_migration.MH_GROUP_ID},
    )
    for index, (device_id, serial, _) in enumerate(
        rename_migration.EXPECTED_MH_DEVICES,
        start=1,
    ):
        await conn.execute(
            text("INSERT INTO devices (id, serial, name) VALUES (:id, :serial, :name)"),
            {"id": device_id, "serial": serial, "name": serial},
        )
        await conn.execute(
            text(
                "INSERT INTO device_group_members (id, group_id, device_id) "
                "VALUES (:id, :group_id, :device_id)"
            ),
            {
                "id": f"member-{index}",
                "group_id": rename_migration.MH_GROUP_ID,
                "device_id": device_id,
            },
        )


@pytest.mark.asyncio
async def test_restores_mh_names_after_serial_overwrite() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await _create_tables(conn)
        await _seed_expected_group_with_serial_names(conn)

        await restore_migration.upgrade(conn)

        rows = (await conn.execute(text("SELECT id, name FROM devices"))).fetchall()
        names_by_id = {str(row.id): str(row.name) for row in rows}
        assert names_by_id == {
            device_id: new_name
            for device_id, _, new_name in rename_migration.EXPECTED_MH_DEVICES
        }

    await engine.dispose()
