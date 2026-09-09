"""Campaign/session path must not decide on Facebook by itself (roadmap 2.2)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.database import Base
from db.models.account import Account, DeviceAccount
from db.models.enums import AccountState
from services.campaign.account_resolver import resolve_accounts_for_devices
from services.platform_readiness import PlatformReadinessStatus
from services.platform_session_guard import (
    observe_platform_readiness_for_device,
    platform_app_package,
)
from tenancy.context import use_tenant_scope

ORG = "org-1"
DEVICE = "device-1"


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


async def _seed_two_platform_accounts(db: AsyncSession) -> dict[str, str]:
    """One device with a primary active account on facebook *and* on tiktok."""
    ids: dict[str, str] = {}
    for platform in ("facebook", "tiktok"):
        account = Account(
            id=f"account-{platform}",
            org_id=ORG,
            platform=platform,
            username=f"user-{platform}",
            state=AccountState.ACTIVE.value,
            status=AccountState.ACTIVE.value,
        )
        db.add(account)
        db.add(
            DeviceAccount(
                id=f"link-{platform}",
                device_id=DEVICE,
                account_id=account.id,
                is_primary=True,
            )
        )
        ids[platform] = account.id
    await db.flush()
    return ids


def _campaign() -> SimpleNamespace:
    return SimpleNamespace(
        id="campaign-1",
        org_id=ORG,
        per_device_accounts=None,
        scenario_account_id=None,
        account_group_id=None,
        variables={},
    )


@pytest.mark.asyncio
async def test_resolver_uses_requested_platform(session_factory):
    async with session_factory() as db:
        with use_tenant_scope(ORG):
            ids = await _seed_two_platform_accounts(db)
            resolved = await resolve_accounts_for_devices(
                db,
                campaign=_campaign(),
                org_id=ORG,
                device_ids=[DEVICE],
                platform="tiktok",
            )

    assert resolved[DEVICE].account_id == ids["tiktok"]
    assert resolved[DEVICE].account_vars["__ACCOUNT_PLATFORM__"] == "tiktok"


@pytest.mark.asyncio
async def test_resolver_defaults_to_facebook(session_factory):
    async with session_factory() as db:
        with use_tenant_scope(ORG):
            ids = await _seed_two_platform_accounts(db)
            resolved = await resolve_accounts_for_devices(
                db,
                campaign=_campaign(),
                org_id=ORG,
                device_ids=[DEVICE],
            )

    assert resolved[DEVICE].account_id == ids["facebook"]


def test_app_package_comes_from_social_ext():
    assert platform_app_package("facebook") == "com.facebook.katana"
    assert platform_app_package("tiktok") is None
    assert platform_app_package("") is None


class _RecordingClient:
    def __init__(self) -> None:
        self.launched: list[str] = []

    def launch_app(self, package: str) -> None:
        self.launched.append(package)

    def hierarchy_xml(self, force_refresh: bool = False) -> str:
        return "<hierarchy/>"


class _FakeManager:
    def __init__(self, client: _RecordingClient) -> None:
        self.client = client

    def get_device(self, serial: str) -> _RecordingClient:
        return self.client


@pytest.mark.asyncio
async def test_unknown_app_package_never_launches_another_app():
    client = _RecordingClient()

    result = await observe_platform_readiness_for_device(
        device_serial="serial-1",
        manager=_FakeManager(client),
        platform="tiktok",
    )

    assert result.status == PlatformReadinessStatus.INCONCLUSIVE
    assert result.reason == "platform_app_package_unknown"
    assert client.launched == []


@pytest.mark.asyncio
async def test_known_app_package_still_launches():
    client = _RecordingClient()

    await observe_platform_readiness_for_device(
        device_serial="serial-1",
        manager=_FakeManager(client),
        platform="facebook",
    )

    assert client.launched == ["com.facebook.katana"]
