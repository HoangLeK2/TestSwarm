"""Relay agent persistence must work without HTTP tenant context (gRPC register path)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db import crud as relay_repo
from db.crud.relay_agent import generate_relay_agent_token, hash_relay_agent_token
from db.database import Base
from db.models import Device, Organization, User
from db.models.relay_agent import RelayAgentToken
from tenancy.background import lookup_device_by_serial
from tenancy.context import tenant_context


ORG_ID = "org-relay-tenancy"
USER_ID = "user-relay-tenancy"
NOW = datetime.now(timezone.utc)


@pytest_asyncio.fixture
async def session_factory():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        session.add(
            Organization(
                id=ORG_ID,
                business_name="Relay Org",
                business_email="relay@example.com",
                status="active",
                plan="standard",
                created_at=NOW,
            )
        )
        session.add(
            User(
                id=USER_ID,
                email="relay@example.com",
                name="Relay User",
                hashed_password="x",
                org_id=ORG_ID,
                created_at=NOW,
            )
        )
        await session.commit()
    yield factory
    await eng.dispose()


@pytest.mark.asyncio
async def test_lookup_enrollment_and_upsert_without_request_tenant_context(session_factory):
  """gRPC register resolves org via token hash, then runs ORM writes in tenant_context."""
  raw_token = generate_relay_agent_token()
  async with session_factory() as db:
    with tenant_context(ORG_ID):
      db.add(
        RelayAgentToken(
          id="tok-1",
          org_id=ORG_ID,
          user_id=USER_ID,
          name="agent-boot",
          token_hash=hash_relay_agent_token(raw_token),
          prefix=raw_token[:13],
          status="active",
          created_at=NOW,
        )
      )
      await db.commit()

  async with session_factory() as db:
    identity = await relay_repo.lookup_relay_token_enrollment(db, raw_token)
    assert identity == (ORG_ID, USER_ID, "tok-1")

    org_id, user_id, token_id = identity
    with tenant_context(org_id):
      row = await relay_repo.resolve_relay_agent_token(db, raw_token)
      assert row is not None
      assert row.id == token_id
      agent = await relay_repo.upsert_relay_agent(
        db,
        org_id=org_id,
        relay_id="relay-mac.local",
        hostname="mac.local",
        ip="172.16.0.182",
        version="1.0",
        serials=["dev-1"],
        user_id=user_id,
        enrollment_token_id=token_id,
      )
      await db.commit()

    assert agent.org_id == ORG_ID
    assert agent.relay_id == "relay-mac.local"


@pytest.mark.asyncio
async def test_relay_scrcpy_preference_resolves_tenant_before_orm_read(
    session_factory,
    monkeypatch,
):
    monkeypatch.setenv("TENANCY_STRICT_MODE", "true")
    async with session_factory() as db:
        with tenant_context(ORG_ID):
            db.add(
                Device(
                    id="dev-relay-scrcpy",
                    serial="serial-relay-scrcpy",
                    name="Relay Scrcpy",
                    user_id=USER_ID,
                    org_id=ORG_ID,
                    relay_scrcpy_enabled=False,
                )
            )
            await db.commit()

    async with session_factory() as db:
        with tenant_context(None):
            device_ref = await lookup_device_by_serial(db, "serial-relay-scrcpy")
        assert device_ref is not None
        assert device_ref.org_id == ORG_ID

        with tenant_context(device_ref.org_id):
            allowed = await relay_repo.relay_scrcpy_auto_attach_allowed(
                db,
                "serial-relay-scrcpy",
            )

    assert allowed is False
