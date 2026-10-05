from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import create_async_engine

from db.models.account import Account
from db.models.account_action import AccountAction
from db.models.content import ContentItem
from db.models.device import Device
from db.models.execution import Execution, ExecutionDevice
from db.models.external_entity import DeviceTargetGroup, ExternalEntity
from db.models.organization import Organization
from services.account_target_runtime import (
    _content_keyword_filter,
    _keyword_filter,
    lease_account_target,
)
from tenancy.context import tenant_context


async def _seed(session_factory) -> None:
    async with session_factory() as db:
        db.add(
            Organization(
                id="org-target",
                business_name="Target org",
                business_email="target@example.com",
            )
        )
        db.add(
            Account(
                id="account-target",
                org_id="org-target",
                platform="instagram",
                username="target-user",
            )
        )
        db.add(
            Device(
                id="device-target",
                org_id="org-target",
                serial="target-serial",
            )
        )
        db.add(
            Execution(
                id="execution-target",
                org_id="org-target",
                account_id="account-target",
                run_type="campaign",
            )
        )
        db.add(
            ExecutionDevice(
                id="execution-device-target",
                execution_id="execution-target",
                device_id="device-target",
            )
        )
        db.add_all(
            [
                ExternalEntity(
                    id="page-target",
                    org_id="org-target",
                    platform="instagram",
                    entity_type="page",
                    identity_key="page-target",
                    display_name="Cong nghe Viet Nam",
                    status="approved",
                ),
                ExternalEntity(
                    id="post-target-1",
                    org_id="org-target",
                    platform="instagram",
                    entity_type="post",
                    identity_key="post-target-1",
                    display_name="Bai viet cong nghe 1",
                    status="approved",
                ),
                ExternalEntity(
                    id="post-target-2",
                    org_id="org-target",
                    platform="instagram",
                    entity_type="post",
                    identity_key="post-target-2",
                    display_name="Bai viet cong nghe 2",
                    status="active",
                ),
                ContentItem(
                    id="content-post-target",
                    org_id="org-target",
                    platform="instagram",
                    content_type="ig_media",
                    body="Bai viet cong nghe tu kho crawl",
                    content_hash="content-post-target-hash",
                    item_level=0,
                ),
            ]
        )
        db.add(
            DeviceTargetGroup(
                id="assigned-page-target",
                org_id="org-target",
                device_id="device-target",
                external_entity_id="page-target",
                position=0,
            )
        )
        await db.commit()


def _identity(step_id: str) -> dict[str, str]:
    return {
        "account_id": "account-target",
        "execution_id": "execution-target",
        "step_id": step_id,
    }


@pytest.mark.asyncio
async def test_lease_prefers_device_assignment(tenancy_session_factory):
    await _seed(tenancy_session_factory)

    async with tenancy_session_factory() as db:
        result = await lease_account_target(
            db,
            identity=_identity("lease-page"),
            platform="instagram",
            entity_type="page",
            action_type="content_interaction",
            action="like",
        )
        await db.commit()

    assert result["available"] is True
    assert result["external_entity_id"] == "page-target"
    assert result["source"] == "device_target_group"


@pytest.mark.asyncio
async def test_lease_uses_org_pool_and_never_repeats_account_target(
    tenancy_session_factory,
):
    await _seed(tenancy_session_factory)

    async with tenancy_session_factory() as db:
        first = await lease_account_target(
            db,
            identity=_identity("lease-post-1"),
            platform="instagram",
            entity_type="post",
            action_type="content_interaction",
            action="like",
            keywords="cong nghe",
        )
        second = await lease_account_target(
            db,
            identity=_identity("lease-post-2"),
            platform="instagram",
            entity_type="post",
            action_type="content_interaction",
            action="like",
            keywords=["cong nghe"],
        )
        third = await lease_account_target(
            db,
            identity=_identity("lease-post-3"),
            platform="instagram",
            entity_type="post",
            action_type="content_interaction",
            action="like",
            keywords=["cong nghe"],
        )
        repeated_third = await lease_account_target(
            db,
            identity=_identity("lease-post-3"),
            platform="instagram",
            entity_type="post",
            action_type="content_interaction",
            action="like",
            keywords=["cong nghe"],
        )
        await db.commit()

    assert first["available"] is True
    assert second["available"] is True
    assert third["available"] is True
    assert first["source"] == second["source"] == "org_source_pool"
    assert third["source"] == "content_item"
    assert repeated_third["account_action_id"] == third["account_action_id"]
    assert first["external_entity_id"] != second["external_entity_id"]
    assert third["external_entity_id"] == "content-post-target"
    assert third["target_search_text"] == "Bai viet cong nghe tu kho crawl"

    async with tenancy_session_factory() as db:
        with tenant_context("org-target"):
            actions = list(
                (
                    await db.execute(
                        select(AccountAction).order_by(AccountAction.step_id)
                    )
                ).scalars()
            )
    assert {action.target["target_id"] for action in actions} == {
        "post-target-1",
        "post-target-2",
        "content-post-target",
    }


def test_postgres_keyword_filter_uses_indexable_full_text_search():
    db = SimpleNamespace(bind=SimpleNamespace(dialect=postgresql.dialect()))

    compiled = str(
        _keyword_filter(db, ("cong nghe", "AI")).compile(
            dialect=postgresql.dialect()
        )
    )

    assert "to_tsvector" in compiled
    assert "plainto_tsquery" in compiled
    assert "@@" in compiled
    content_compiled = str(
        _content_keyword_filter(db, ("cong nghe",)).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "to_tsvector('simple'" in content_compiled
    assert "coalesce(content_items.title, '') || ' '" in content_compiled


@pytest.mark.asyncio
async def test_target_lookup_migration_is_idempotent_on_sqlite():
    migration_108 = importlib.import_module(
        "db.migrations.108_account_action_target_lookup"
    )
    migration_109 = importlib.import_module(
        "db.migrations.109_content_item_action_target_lookup"
    )
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE account_actions ("
                "id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36), "
                "account_id VARCHAR(36), platform VARCHAR(32), "
                "action_type VARCHAR(64), status VARCHAR(32), target JSON)"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE content_items ("
                "id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36), "
                "platform VARCHAR(50), content_type VARCHAR(50), "
                "title VARCHAR(500), body TEXT, extracted_at TIMESTAMP, "
                "deleted_at TIMESTAMP, item_level INTEGER)"
            )
        )
        await migration_108.upgrade(conn)
        await migration_108.upgrade(conn)
        await migration_109.upgrade(conn)
        await migration_109.upgrade(conn)
        indexes = {
            row[1]
            for row in (
                await conn.execute(text("PRAGMA index_list(account_actions)"))
            ).all()
        }
        content_indexes = {
            row[1]
            for row in (
                await conn.execute(text("PRAGMA index_list(content_items)"))
            ).all()
        }
        await migration_109.downgrade(conn)
        await migration_108.downgrade(conn)
    await engine.dispose()

    assert "idx_account_actions_target_state" in indexes
    assert "idx_content_items_action_frontier" in content_indexes
