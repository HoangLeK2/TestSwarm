"""Agent identity is server-owned: one machine = one row, named by the admin.

The four regressions this pins down all shipped together and all fail silently:
the agent minting its own id, the hostname (a Docker container ID) being treated
as identity, register overwriting the admin's rename, and a made-up relay_id
being able to create a row.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.crud.relay_agent import (
    RELAY_ID_PREFIX,
    generate_relay_agent_token,
    hash_relay_agent_token,
    lookup_relay_token_enrollment,
    mark_relay_offline,
    relay_agent_is_disabled,
    resolve_relay_agent_token,
    resolve_relay_identity,
    upsert_relay_agent,
)
from db.database import Base
from db.models import Organization, User
from db.models.relay_agent import RelayAgent, RelayAgentToken
from tenancy.context import tenant_context

ORG_ID = "org-agent-identity"
USER_ID = "user-agent-identity"
TOKEN_ID = "tok-agent-identity"
TOKEN_NAME = "Máy test 1"
NOW = datetime.now(timezone.utc)


@pytest_asyncio.fixture
async def session_factory():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await eng.dispose()


@pytest_asyncio.fixture
async def raw_token(session_factory):
    token = generate_relay_agent_token()
    async with session_factory() as db:
        with tenant_context(ORG_ID):
            db.add(
                Organization(
                    id=ORG_ID,
                    business_name="Identity Org",
                    business_email="identity@example.com",
                    status="active",
                    plan="standard",
                    created_at=NOW,
                )
            )
            db.add(
                User(
                    id=USER_ID,
                    email="identity@example.com",
                    name="Identity User",
                    hashed_password="x",
                    org_id=ORG_ID,
                    created_at=NOW,
                )
            )
            db.add(
                RelayAgentToken(
                    id=TOKEN_ID,
                    org_id=ORG_ID,
                    user_id=USER_ID,
                    name=TOKEN_NAME,
                    token_hash=hash_relay_agent_token(token),
                    prefix=token[:13],
                    status="active",
                    created_at=NOW,
                )
            )
            await db.commit()
    return token


async def _register(session_factory, raw_token: str, *, hostname: str, relay_id: str) -> str:
    """Mirror _on_ctrl_register: authenticate, resolve identity, upsert."""
    async with session_factory() as db:
        identity = await lookup_relay_token_enrollment(db, raw_token)
        assert identity is not None
        org_id, user_id, token_id = identity
        with tenant_context(org_id):
            token_row = await resolve_relay_agent_token(db, raw_token)
            resolved = await resolve_relay_identity(
                db, org_id=org_id, token_id=token_id, proposed_relay_id=relay_id
            )
            if not resolved:
                await db.rollback()
                return ""
            await upsert_relay_agent(
                db,
                org_id=org_id,
                relay_id=resolved,
                name=(token_row.name if token_row else "") or "",
                hostname=hostname,
                ip="10.0.0.9",
                version="test",
                serials=[],
                user_id=user_id,
                enrollment_token_id=token_id,
            )
            await db.commit()
        return resolved


async def _rows(session_factory) -> list[RelayAgent]:
    async with session_factory() as db:
        with tenant_context(ORG_ID):
            result = await db.execute(select(RelayAgent))
            return list(result.scalars().all())


@pytest.mark.asyncio
async def test_first_register_mints_id_and_inherits_activation_code_name(
    session_factory, raw_token
):
    relay_id = await _register(
        session_factory, raw_token, hostname="a0afd41bcdf4", relay_id=""
    )
    assert relay_id.startswith(RELAY_ID_PREFIX)

    rows = await _rows(session_factory)
    assert len(rows) == 1
    assert rows[0].name == TOKEN_NAME


@pytest.mark.asyncio
async def test_new_container_reclaims_the_same_row(session_factory, raw_token):
    """A recreated container reports a new hostname and has lost its state file."""
    first = await _register(
        session_factory, raw_token, hostname="a0afd41bcdf4", relay_id=""
    )
    async with session_factory() as db:
        with tenant_context(ORG_ID):
            row = (await db.execute(select(RelayAgent))).scalar_one()
            row.status = "offline"
            await db.commit()

    second = await _register(
        session_factory, raw_token, hostname="1dab525bc8af", relay_id=""
    )
    assert second == first
    assert len(await _rows(session_factory)) == 1


@pytest.mark.asyncio
async def test_register_never_overwrites_an_admin_rename(session_factory, raw_token):
    await _register(session_factory, raw_token, hostname="a0afd41bcdf4", relay_id="")
    async with session_factory() as db:
        with tenant_context(ORG_ID):
            row = (await db.execute(select(RelayAgent))).scalar_one()
            row.name = "Máy phòng kế toán"
            row.status = "offline"
            await db.commit()

    await _register(session_factory, raw_token, hostname="1dab525bc8af", relay_id="")

    rows = await _rows(session_factory)
    assert len(rows) == 1
    assert rows[0].name == "Máy phòng kế toán"


@pytest.mark.asyncio
async def test_invented_relay_id_creates_no_row(session_factory, raw_token):
    relay_id = await _register(
        session_factory, raw_token, hostname="host", relay_id="i-made-this-up"
    )
    assert relay_id.startswith(RELAY_ID_PREFIX)

    rows = await _rows(session_factory)
    assert len(rows) == 1
    assert rows[0].relay_id != "i-made-this-up"


@pytest.mark.asyncio
async def test_second_machine_on_the_same_code_is_refused(session_factory, raw_token):
    """One activation code enrols one machine; the first stays online."""
    first = await _register(
        session_factory, raw_token, hostname="a0afd41bcdf4", relay_id=""
    )
    assert first

    refused = await _register(session_factory, raw_token, hostname="other", relay_id="")
    assert refused == ""
    assert len(await _rows(session_factory)) == 1


async def _set_status(session_factory, relay_id: str, status: str) -> None:
    async with session_factory() as db:
        with tenant_context(ORG_ID):
            row = (
                await db.execute(
                    select(RelayAgent).where(RelayAgent.relay_id == relay_id)
                )
            ).scalar_one()
            row.status = status
            await db.commit()


@pytest.mark.asyncio
async def test_disabled_agent_is_not_resurrected_by_its_own_reconnect(
    session_factory, raw_token
):
    """Admin turns an agent off; the agent's retry loop must not undo that."""
    relay_id = await _register(session_factory, raw_token, hostname="host", relay_id="")
    await _set_status(session_factory, relay_id, "disabled")

    assert await _register(
        session_factory, raw_token, hostname="host", relay_id=relay_id
    )
    rows = await _rows(session_factory)
    assert [row.status for row in rows] == ["disabled"]


@pytest.mark.asyncio
async def test_disconnect_keeps_the_serial_map(session_factory, raw_token):
    """Liveness comes from the transports; the row keeps the last phone list."""
    relay_id = await _register(session_factory, raw_token, hostname="host", relay_id="")
    async with session_factory() as db:
        with tenant_context(ORG_ID):
            row = (
                await db.execute(
                    select(RelayAgent).where(RelayAgent.relay_id == relay_id)
                )
            ).scalar_one()
            row.serials = ["SN001"]
            await db.commit()
            await mark_relay_offline(db, relay_id)
            await db.commit()

    rows = await _rows(session_factory)
    assert rows[0].status == "offline"
    assert list(rows[0].serials) == ["SN001"]


@pytest.mark.asyncio
async def test_startup_reconciliation_keeps_the_serial_map():
    """Deploy/startup must not make assigned pool phones disappear from admin views."""
    from web.server import _reconcile_relay_agents_after_startup

    class CaptureDb:
        def __init__(self) -> None:
            self.statements: list[str] = []

        async def execute(self, statement) -> None:
            self.statements.append(str(statement))

    db = CaptureDb()

    await _reconcile_relay_agents_after_startup(db)

    assert len(db.statements) == 1
    sql = db.statements[0].lower()
    assert "status='offline'" in sql
    assert "where status='online'" in sql
    assert "serials" not in sql


@pytest.mark.asyncio
async def test_disconnect_does_not_clear_disabled(session_factory, raw_token):
    relay_id = await _register(session_factory, raw_token, hostname="host", relay_id="")

    async with session_factory() as db:
        with tenant_context(ORG_ID):
            await mark_relay_offline(db, relay_id)
            await db.commit()
    assert [row.status for row in await _rows(session_factory)] == ["offline"]

    await _set_status(session_factory, relay_id, "disabled")
    async with session_factory() as db:
        with tenant_context(ORG_ID):
            await mark_relay_offline(db, relay_id)
            await db.commit()
    assert [row.status for row in await _rows(session_factory)] == ["disabled"]


@pytest.mark.asyncio
async def test_register_path_can_see_the_disabled_flag(session_factory, raw_token):
    """The gRPC register callback has no tenant context — the check must not need one."""
    relay_id = await _register(session_factory, raw_token, hostname="host", relay_id="")

    async with session_factory() as db:
        assert await relay_agent_is_disabled(db, relay_id) is False

    await _set_status(session_factory, relay_id, "disabled")
    async with session_factory() as db:
        assert await relay_agent_is_disabled(db, relay_id) is True
        assert await relay_agent_is_disabled(db, "agt_unknown") is False


@pytest.mark.asyncio
async def test_transport_parks_a_disabled_agent_and_resumes_without_reconnect():
    """Video/ADB must honour disable — and give it back without a reconnect."""
    from runtime.transports import adb_relay_server
    from runtime.transports.agent_suspension import get_agent_suspension_registry

    class _Conn:
        relay_id = "agt_disabled"
        serials = {"SN001"}

    registry = get_agent_suspension_registry()
    registry.replace([("agt_disabled", ["SN001"])])
    try:
        manager = adb_relay_server.AdbRelayManager()
        conn = _Conn()

        # Parked: accepted (so the agent stays connected and does not reconnect
        # in a loop) but invisible to every routing lookup.
        assert await manager.register(conn) is True
        assert "agt_disabled" not in manager._relays
        assert manager._suspended["agt_disabled"] is conn
        assert manager.relay_for_serial("SN001") is None

        # Re-enabling is a map move, not a reconnect.
        registry.resume("agt_disabled", ["SN001"])
        assert await manager.resume_relay("agt_disabled") is True
        assert manager._relays["agt_disabled"] is conn
        assert manager.relay_for_serial("SN001") is conn
    finally:
        registry.replace([])


@pytest.mark.asyncio
async def test_disabled_agent_serials_are_discoverable_for_the_media_plane(
    session_factory, raw_token
):
    """The media adapter knows serials, not relay ids — the map must survive."""
    from db.crud.relay_agent import disabled_relay_serials

    relay_id = await _register(session_factory, raw_token, hostname="host", relay_id="")
    async with session_factory() as db:
        with tenant_context(ORG_ID):
            row = (
                await db.execute(
                    select(RelayAgent).where(RelayAgent.relay_id == relay_id)
                )
            ).scalar_one()
            row.serials = ["SN001", "pending-xyz"]
            await db.commit()

    async with session_factory() as db:
        assert await disabled_relay_serials(db) == set()

    await _set_status(session_factory, relay_id, "disabled")
    async with session_factory() as db:
        # 'pending-' placeholders are not real phones and must not block anyone.
        assert await disabled_relay_serials(db) == {"SN001"}
