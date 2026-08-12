from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.deps import _get_current_user, _get_db
from api.routes.external_entities import device_target_groups_router
from db.database import Base
from db.models.device import Device
from db.models.external_entity import DeviceTargetGroup, ExternalEntity
from services.campaign.entity_allocation import (
    SourcePoolSpec,
    count_assigned_targets_by_device,
    load_assigned_target_page,
)
from tenancy.context import set_current_org_id


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


def _app(session_factory) -> FastAPI:
    app = FastAPI()
    app.include_router(device_target_groups_router, prefix="/api")

    async def db_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    async def user_override():
        set_current_org_id("org-1")
        return SimpleNamespace(id="user-1", org_id="org-1", org_role="owner")

    async def allow_permission():
        return None

    app.dependency_overrides[_get_db] = db_override
    app.dependency_overrides[_get_current_user] = user_override
    for route in app.routes:
        for dependency in getattr(
            getattr(route, "dependant", None), "dependencies", []
        ):
            if getattr(dependency.call, "__name__", "") == "_require_permission":
                app.dependency_overrides[dependency.call] = allow_permission
    return app


async def _seed(session_factory):
    async with session_factory() as session:
        session.add_all(
            [
                Device(id="device-1", serial="serial-1", org_id="org-1"),
                Device(id="device-3", serial="serial-3", org_id="org-1"),
                Device(id="device-2", serial="serial-2", org_id="org-2"),
                ExternalEntity(
                    id="group-1",
                    org_id="org-1",
                    platform="facebook",
                    entity_type="group",
                    identity_key="g1",
                    display_name="Group 1",
                ),
                ExternalEntity(
                    id="group-2",
                    org_id="org-1",
                    platform="facebook",
                    entity_type="group",
                    identity_key="g2",
                    display_name="Group 2",
                ),
                ExternalEntity(
                    id="page-1",
                    org_id="org-1",
                    platform="facebook",
                    entity_type="page",
                    identity_key="p1",
                    display_name="Page 1",
                ),
                ExternalEntity(
                    id="profile-1",
                    org_id="org-1",
                    platform="facebook",
                    entity_type="profile",
                    identity_key="u1",
                    display_name="Profile 1",
                ),
                ExternalEntity(
                    id="profile-2",
                    org_id="org-1",
                    platform="facebook",
                    entity_type="profile",
                    identity_key="u2",
                    display_name="Profile 2",
                ),
                ExternalEntity(
                    id="post-1",
                    org_id="org-1",
                    platform="facebook",
                    entity_type="post",
                    identity_key="post1",
                    display_name="Post 1",
                ),
                ExternalEntity(
                    id="foreign",
                    org_id="org-2",
                    platform="facebook",
                    entity_type="group",
                    identity_key="gf",
                    display_name="Foreign",
                ),
            ]
        )
        await session.commit()


@pytest.mark.asyncio
async def test_replace_target_groups_is_ordered_atomic_and_idempotent(session_factory):
    await _seed(session_factory)
    async with AsyncClient(
        transport=ASGITransport(app=_app(session_factory)), base_url="http://test"
    ) as client:
        first = await client.put(
            "/api/devices/device-1/target-groups",
            json={"external_entity_ids": ["group-2", "group-1", "group-2"]},
        )
        assert first.status_code == 200, first.text
        assert [item["id"] for item in first.json()["groups"]] == ["group-2", "group-1"]
        assert first.json()["added_count"] == 2
        async with session_factory() as session:
            original_ids = list(
                (
                    await session.scalars(
                        select(DeviceTargetGroup.id).order_by(
                            DeviceTargetGroup.position
                        )
                    )
                ).all()
            )
        second = await client.put(
            "/api/devices/device-1/target-groups",
            json={"external_entity_ids": ["group-2", "group-1"]},
        )
        assert second.status_code == 200, second.text
        assert second.json()["added_count"] == 0
        assert second.json()["unchanged_count"] == 2
        assert "current_attributes" not in second.json()["groups"][0]
        async with session_factory() as session:
            assert (
                list(
                    (
                        await session.scalars(
                            select(DeviceTargetGroup.id).order_by(
                                DeviceTargetGroup.position
                            )
                        )
                    ).all()
                )
                == original_ids
            )
        reordered = await client.put(
            "/api/devices/device-1/target-groups",
            json={"external_entity_ids": ["group-1", "group-2"]},
        )
        assert [item["id"] for item in reordered.json()["groups"]] == [
            "group-1",
            "group-2",
        ]
        async with session_factory() as session:
            assert set(
                (await session.scalars(select(DeviceTargetGroup.id))).all()
            ) == set(original_ids)
        listed = await client.get("/api/devices/device-1/target-groups")
        assert [item["id"] for item in listed.json()["groups"]] == [
            "group-1",
            "group-2",
        ]


@pytest.mark.asyncio
async def test_device_targets_accept_groups_pages_and_profiles_only(session_factory):
    await _seed(session_factory)
    async with AsyncClient(
        transport=ASGITransport(app=_app(session_factory)), base_url="http://test"
    ) as client:
        saved = await client.put(
            "/api/devices/device-1/target-groups",
            json={"external_entity_ids": ["group-1", "page-1", "profile-1"]},
        )
        assert saved.status_code == 200
        assert [item["entity_type"] for item in saved.json()["groups"]] == [
            "group",
            "page",
            "profile",
        ]
        assert (
            await client.put(
                "/api/devices/device-1/target-groups",
                json={"external_entity_ids": ["post-1"]},
            )
        ).status_code == 400
        assert (
            await client.put(
                "/api/devices/device-1/target-groups",
                json={"external_entity_ids": ["foreign"]},
            )
        ).status_code == 400
        assert (
            await client.get("/api/devices/device-2/target-groups")
        ).status_code == 404
        listed = await client.get("/api/devices/device-1/target-groups")
        assert [item["id"] for item in listed.json()["groups"]] == [
            "group-1",
            "page-1",
            "profile-1",
        ]


@pytest.mark.asyncio
async def test_replace_requires_explicit_list_and_allows_explicit_clear(
    session_factory,
):
    await _seed(session_factory)
    async with AsyncClient(
        transport=ASGITransport(app=_app(session_factory)), base_url="http://test"
    ) as client:
        saved = await client.put(
            "/api/devices/device-1/target-groups",
            json={"external_entity_ids": ["group-1"]},
        )
        assert saved.status_code == 200

        missing = await client.put("/api/devices/device-1/target-groups", json={})
        assert missing.status_code == 422
        listed = await client.get("/api/devices/device-1/target-groups")
        assert [item["id"] for item in listed.json()["groups"]] == ["group-1"]

        cleared = await client.put(
            "/api/devices/device-1/target-groups",
            json={"external_entity_ids": []},
        )
        assert cleared.status_code == 200
        assert cleared.json()["removed_count"] == 1
        assert cleared.json()["groups"] == []


@pytest.mark.asyncio
async def test_assigned_target_page_keeps_each_target_on_its_device(session_factory):
    await _seed(session_factory)
    async with session_factory() as session:
        session.add_all(
            [
                DeviceTargetGroup(
                    org_id="org-1",
                    device_id="device-1",
                    external_entity_id="profile-1",
                    position=0,
                ),
                DeviceTargetGroup(
                    org_id="org-1",
                    device_id="device-3",
                    external_entity_id="profile-1",
                    position=0,
                ),
                DeviceTargetGroup(
                    org_id="org-1",
                    device_id="device-1",
                    external_entity_id="profile-2",
                    position=1,
                ),
            ]
        )
        await session.commit()

    spec = SourcePoolSpec(platform="facebook", entity_type="profile")
    snapshot_at = datetime.now(UTC)
    async with session_factory() as session:
        first = await load_assigned_target_page(
            session,
            org_id="org-1",
            spec=spec,
            dispatch_id="dispatch-1",
            device_serials=["serial-1", "serial-3"],
            snapshot_at=snapshot_at,
            cursor=None,
            limit=2,
        )
        assert [(item.device_serial, item.entity.id) for item in first.items] == [
            ("serial-1", "profile-1"),
            ("serial-3", "profile-1"),
        ]
        assert first.exhausted is False

        second = await load_assigned_target_page(
            session,
            org_id="org-1",
            spec=spec,
            dispatch_id="dispatch-1",
            device_serials=["serial-1", "serial-3"],
            snapshot_at=snapshot_at,
            cursor=first.next_cursor,
            limit=2,
        )
        assert [(item.device_serial, item.entity.id) for item in second.items] == [
            ("serial-1", "profile-2")
        ]
        assert second.exhausted is True

        counts = await count_assigned_targets_by_device(
            session,
            org_id="org-1",
            spec=spec,
            device_ids=["device-1", "device-3"],
            snapshot_at=snapshot_at,
        )
        assert counts == {"device-1": 2, "device-3": 1}
