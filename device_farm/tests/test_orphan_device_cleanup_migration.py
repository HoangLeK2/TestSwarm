"""Migration 133 frees a serial held by an archived agent — and only that.

The case it fixes: workspace A's agent gets archived, its unclaimed phone row
stays, and workspace B's agent can no longer register the same physical phone
(``serial already registered by another organization``). The cases it must not
touch: a claimed phone, and a phone whose agent is merely offline.
"""
from __future__ import annotations

from importlib import import_module

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from db.database import Base

migration = import_module("db.migrations.133_orphan_unclaimed_devices")

_AGENT_SQL = text(
    "INSERT INTO relay_agents (id, relay_id, name, hostname, ip, version, serials, "
    "status, connected_at, created_at, org_id) VALUES "
    "(:relay_id, :relay_id, '', '', '', '', '[]', :status, CURRENT_TIMESTAMP, "
    "CURRENT_TIMESTAMP, 'org-pool')"
)

_DEVICE_SQL = text(
    "INSERT INTO devices (id, serial, device_serial, name, status, notes, device_key, "
    "brand, model, android_version, sdk_version, screen_width, screen_height, "
    "adb_port, tags, relay_scrcpy_enabled, created_at, org_id, user_id, "
    "managed_by_relay_id) VALUES "
    "(:id, :serial, :serial, :serial, :status, '', :key, '', '', '', 0, 0, 0, 0, '', "
    "0, CURRENT_TIMESTAMP, 'org-pool', :user_id, :relay_id)"
)


async def _seed_agent(conn, relay_id: str, status: str) -> None:
    await conn.execute(_AGENT_SQL, {"relay_id": relay_id, "status": status})


async def _seed_device(
    conn,
    device_id: str,
    serial: str,
    *,
    status: str,
    user_id: str | None,
    relay_id: str | None,
) -> None:
    await conn.execute(
        _DEVICE_SQL,
        {
            "id": device_id,
            "serial": serial,
            "status": status,
            "key": f"key-{device_id}",
            "user_id": user_id,
            "relay_id": relay_id,
        },
    )


async def _serials(conn) -> set[str]:
    rows = (await conn.execute(text("SELECT serial FROM devices"))).fetchall()
    return {row.serial for row in rows}


@pytest.mark.asyncio
async def test_removes_only_orphans_of_archived_agents():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _seed_agent(conn, "agent-archived", "archived")
        await _seed_agent(conn, "agent-offline", "offline")

        # Freed: unclaimed, managing agent archived.
        await _seed_device(
            conn,
            "dev-orphan",
            "SN-ORPHAN",
            status="unpaired",
            user_id=None,
            relay_id="agent-archived",
        )
        # Kept: a user claimed it, archived agent or not.
        await _seed_device(
            conn,
            "dev-claimed",
            "SN-CLAIMED",
            status="paired",
            user_id="user-1",
            relay_id="agent-archived",
        )
        # Kept: the agent is offline, not archived — it may come back.
        await _seed_device(
            conn,
            "dev-offline",
            "SN-OFFLINE",
            status="unpaired",
            user_id=None,
            relay_id="agent-offline",
        )
        # Kept: no managing agent recorded, so nothing says it is orphaned.
        await _seed_device(
            conn,
            "dev-unmanaged",
            "SN-UNMANAGED",
            status="unpaired",
            user_id=None,
            relay_id=None,
        )

        await migration.upgrade(conn)
        remaining = await _serials(conn)
        assert remaining == {"SN-CLAIMED", "SN-OFFLINE", "SN-UNMANAGED"}

        # Idempotent: a second run is a no-op.
        await migration.upgrade(conn)
        assert await _serials(conn) == remaining

    await engine.dispose()


@pytest.mark.asyncio
async def test_keeps_orphan_row_that_still_carries_a_binding():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _seed_agent(conn, "agent-archived", "archived")
        await _seed_device(
            conn,
            "dev-bound",
            "SN-BOUND",
            status="unpaired",
            user_id=None,
            relay_id="agent-archived",
        )
        await conn.execute(
            text(
                "INSERT INTO campaign_devices (id, campaign_id, device_id) "
                "VALUES ('cd-1', 'camp-1', 'dev-bound')"
            )
        )

        await migration.upgrade(conn)
        assert await _serials(conn) == {"SN-BOUND"}

    await engine.dispose()
