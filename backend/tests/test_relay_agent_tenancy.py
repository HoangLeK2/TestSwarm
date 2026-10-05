"""Relay agent persistence must work without HTTP tenant context (gRPC register path)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db import crud as relay_repo
from db.crud import device as device_repo
from db.crud.relay_agent import generate_relay_agent_token, hash_relay_agent_token
from db.database import Base
from db.models import Device, Organization, User
from db.models.relay_agent import RelayAgentToken
from services.device_registration import DeviceRegistrationError, claim_relay_reported_serials, get_or_claim_device_for_user
from tenancy.background import lookup_device_by_serial
from tenancy.context import tenant_context


ORG_ID = "org-relay-tenancy"
USER_ID = "user-relay-tenancy"
MANAGER_ORG_ID = "org-relay-manager"
MANAGER_USER_ID = "user-relay-manager"
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
        session.add(
            Organization(
                id=MANAGER_ORG_ID,
                business_name="Relay Manager",
                business_email="relay-manager@example.com",
                status="active",
                plan="standard",
                created_at=NOW,
            )
        )
        session.add(
            User(
                id=MANAGER_USER_ID,
                email="relay-manager@example.com",
                name="Relay Manager User",
                hashed_password="x",
                org_id=MANAGER_ORG_ID,
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


@pytest.mark.asyncio
async def test_manager_token_reclaim_moves_allocated_device_out_of_old_workspace(
    session_factory,
):
    serial = "serial-managed-reclaim"
    async with session_factory() as db:
        with tenant_context(ORG_ID):
            db.add(
                Device(
                    id="dev-managed-reclaim",
                    serial=serial,
                    device_serial=serial,
                    name="Hoang Le Phone",
                    user_id=USER_ID,
                    org_id=ORG_ID,
                    managed_by_org_id=MANAGER_ORG_ID,
                    managed_by_relay_id="relay-manager",
                    relay_serial=serial,
                )
            )
            await db.commit()

    async with session_factory() as db:
        device = await get_or_claim_device_for_user(
            db,
            serial=serial,
            display_name="Admin Phone",
            user_id=MANAGER_USER_ID,
            org_id=MANAGER_ORG_ID,
        )
        await db.commit()

        assert device.org_id == MANAGER_ORG_ID
        assert device.user_id == MANAGER_USER_ID
        assert device.managed_by_org_id == MANAGER_ORG_ID

    async with session_factory() as db:
        old_workspace_devices = await device_repo.list_devices(db, org_id=ORG_ID)
        manager_workspace_devices = await device_repo.list_devices(
            db, org_id=MANAGER_ORG_ID
        )

    assert serial not in {device.serial for device in old_workspace_devices}
    assert serial in {device.serial for device in manager_workspace_devices}


@pytest.mark.asyncio
async def test_relay_reclaim_moves_device_even_when_old_workspace_managed_it(
    session_factory,
):
    serial = "serial-relay-reclaim-old-managed"
    async with session_factory() as db:
        with tenant_context(ORG_ID):
            db.add(
                Device(
                    id="dev-relay-reclaim-old-managed",
                    serial=serial,
                    device_serial=serial,
                    name="Hoang Le Phone",
                    user_id=USER_ID,
                    org_id=ORG_ID,
                    managed_by_org_id=ORG_ID,
                    managed_by_relay_id="relay-old",
                    relay_serial=serial,
                )
            )
            await db.commit()

    async with session_factory() as db:
        with pytest.raises(DeviceRegistrationError, match="serial already registered"):
            await get_or_claim_device_for_user(
                db,
                serial=serial,
                display_name="Admin Phone",
                user_id=MANAGER_USER_ID,
                org_id=MANAGER_ORG_ID,
            )
        await db.rollback()

    async with session_factory() as db:
        device = await get_or_claim_device_for_user(
            db,
            serial=serial,
            display_name="Admin Phone",
            user_id=MANAGER_USER_ID,
            org_id=MANAGER_ORG_ID,
            allow_relay_reclaim=True,
        )
        await db.commit()

        assert device.org_id == MANAGER_ORG_ID
        assert device.user_id == MANAGER_USER_ID
        assert device.managed_by_org_id == MANAGER_ORG_ID

    async with session_factory() as db:
        old_workspace_devices = await device_repo.list_devices(db, org_id=ORG_ID)
        manager_workspace_devices = await device_repo.list_devices(
            db, org_id=MANAGER_ORG_ID
        )

    assert serial not in {device.serial for device in old_workspace_devices}
    assert serial in {device.serial for device in manager_workspace_devices}


@pytest.mark.asyncio
async def test_relay_register_auto_claim_moves_reported_device_to_token_workspace(
    session_factory,
):
    serial = "serial-relay-register-auto-claim"
    async with session_factory() as db:
        with tenant_context(ORG_ID):
            db.add(
                Device(
                    id="dev-relay-register-auto-claim",
                    serial=serial,
                    device_serial=serial,
                    name="Hoang Le Phone",
                    user_id=USER_ID,
                    org_id=ORG_ID,
                    managed_by_org_id=ORG_ID,
                    managed_by_relay_id="relay-old",
                    relay_serial=serial,
                )
            )
            await db.commit()

    async with session_factory() as db:
        claimed = await claim_relay_reported_serials(
            db,
            serials=[serial],
            user_id=MANAGER_USER_ID,
            org_id=MANAGER_ORG_ID,
            relay_id="relay-manager",
        )
        await db.commit()

    assert claimed == [serial]

    async with session_factory() as db:
        old_workspace_devices = await device_repo.list_devices(db, org_id=ORG_ID)
        manager_workspace_devices = await device_repo.list_devices(
            db, org_id=MANAGER_ORG_ID
        )

    assert serial not in {device.serial for device in old_workspace_devices}
    manager_device = next(
        device for device in manager_workspace_devices if device.serial == serial
    )
    assert manager_device.user_id == MANAGER_USER_ID
    assert manager_device.managed_by_org_id == MANAGER_ORG_ID
    assert manager_device.managed_by_relay_id == "relay-manager"


@pytest.mark.asyncio
async def test_relay_register_auto_claim_preserves_pool_workspace_allocation(
    session_factory,
):
    serial = "serial-relay-register-allocated"
    async with session_factory() as db:
        with tenant_context(ORG_ID):
            db.add(
                Device(
                    id="dev-relay-register-allocated",
                    serial=serial,
                    device_serial=serial,
                    name="Allocated Phone",
                    user_id=None,
                    org_id=ORG_ID,
                    managed_by_org_id=MANAGER_ORG_ID,
                    managed_by_relay_id="relay-manager",
                    relay_serial=serial,
                )
            )
            await db.commit()

    async with session_factory() as db:
        claimed = await claim_relay_reported_serials(
            db,
            serials=[serial],
            user_id=MANAGER_USER_ID,
            org_id=MANAGER_ORG_ID,
            relay_id="relay-manager-reconnected",
        )
        await db.commit()

    assert claimed == [serial]

    async with session_factory() as db:
        allocated_device = await lookup_device_by_serial(db, serial)

    assert allocated_device is not None
    assert allocated_device.org_id == ORG_ID
    assert allocated_device.user_id is None
    assert allocated_device.managed_by_org_id == MANAGER_ORG_ID
    assert allocated_device.managed_by_relay_id == "relay-manager-reconnected"


@pytest.mark.asyncio
async def test_relay_auto_claim_preserves_existing_device_display_name(
    session_factory,
):
    serial = "serial-relay-register-display-name"
    async with session_factory() as db:
        with tenant_context(ORG_ID):
            db.add(
                Device(
                    id="dev-relay-register-display-name",
                    serial=serial,
                    device_serial=serial,
                    name="MH13",
                    user_id=USER_ID,
                    org_id=ORG_ID,
                    managed_by_org_id=ORG_ID,
                    managed_by_relay_id="relay-old",
                    relay_serial=serial,
                )
            )
            await db.commit()

    async with session_factory() as db:
        claimed = await claim_relay_reported_serials(
            db,
            serials=[serial],
            user_id=MANAGER_USER_ID,
            org_id=MANAGER_ORG_ID,
            relay_id="relay-manager",
        )
        await db.commit()

    assert claimed == [serial]

    async with session_factory() as db:
        manager_workspace_devices = await device_repo.list_devices(
            db, org_id=MANAGER_ORG_ID
        )

    manager_device = next(
        device for device in manager_workspace_devices if device.serial == serial
    )
    assert manager_device.name == "MH13"
    assert manager_device.user_id == MANAGER_USER_ID
    assert manager_device.managed_by_org_id == MANAGER_ORG_ID
    assert manager_device.managed_by_relay_id == "relay-manager"
