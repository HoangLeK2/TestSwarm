from __future__ import annotations

from importlib import import_module

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

migration = import_module("db.migrations.135_rename_mh_group_devices")


async def _create_tables(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE device_groups (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(255)
            )
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE TABLE devices (
                id VARCHAR(36) PRIMARY KEY,
                serial VARCHAR(128) NOT NULL,
                name VARCHAR(255),
                updated_at TIMESTAMP
            )
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE TABLE device_group_members (
                id VARCHAR(36) PRIMARY KEY,
                group_id VARCHAR(36) NOT NULL,
                device_id VARCHAR(36) NOT NULL
            )
            """
        )
    )


async def _seed_expected_group(conn) -> None:
    await conn.execute(
        text("INSERT INTO device_groups (id, name) VALUES (:id, 'Mh')"),
        {"id": migration.MH_GROUP_ID},
    )
    for index, (device_id, serial, _) in enumerate(migration.EXPECTED_MH_DEVICES, start=1):
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
                "group_id": migration.MH_GROUP_ID,
                "device_id": device_id,
            },
        )


@pytest.mark.asyncio
async def test_renames_exact_mh_group_members_to_mh_sequence() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await _create_tables(conn)
        await _seed_expected_group(conn)

        await migration.upgrade(conn)

        rows = (
            await conn.execute(text("SELECT id, name FROM devices ORDER BY name"))
        ).fetchall()
        names_by_id = {str(row.id): str(row.name) for row in rows}
        assert names_by_id == {
            device_id: new_name
            for device_id, _, new_name in migration.EXPECTED_MH_DEVICES
        }

        await migration.upgrade(conn)
        rows_after_second_run = (
            await conn.execute(text("SELECT id, name FROM devices ORDER BY name"))
        ).fetchall()
        assert rows_after_second_run == rows

    await engine.dispose()


@pytest.mark.asyncio
async def test_noops_when_mh_group_is_absent() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await _create_tables(conn)
        await migration.upgrade(conn)
        count = (await conn.execute(text("SELECT COUNT(*) FROM devices"))).scalar_one()
        assert count == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_fails_when_mh_group_membership_does_not_match_expected_phones() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await _create_tables(conn)
        await _seed_expected_group(conn)
        await conn.execute(
            text("DELETE FROM device_group_members WHERE device_id = :device_id"),
            {"device_id": migration.EXPECTED_MH_DEVICES[-1][0]},
        )

        with pytest.raises(RuntimeError, match="exactly 19 known phones"):
            await migration.upgrade(conn)

    await engine.dispose()
