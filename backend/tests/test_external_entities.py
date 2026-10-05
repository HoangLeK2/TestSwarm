"""Org-scoped external entity catalog and observation history."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

pytest_plugins = ["tests.test_epic04_scenario_entity"]

from db.crud.external_entity import (
    get_external_entities_by_ids,
    upsert_external_entity,
)
from db.models.external_entity import (
    ExternalEntity,
    ExternalEntityDiscovery,
    ExternalEntityObservation,
)
from tenancy.context import set_current_org_id, tenant_context
from tests.test_epic04_scenario_entity import (
    ORG_A,
    ORG_B,
    _build_app,
    _seed_orgs,
)


@pytest.mark.asyncio
async def test_upsert_reuses_entity_and_appends_observation_history(session_factory):
    await _seed_orgs(session_factory)
    first_seen = datetime.now(timezone.utc) - timedelta(days=1)
    second_seen = datetime.now(timezone.utc)

    set_current_org_id(ORG_A)
    async with session_factory() as db:
        first, created = await upsert_external_entity(
            db,
            org_id=ORG_A,
            platform="example",
            entity_type="group",
            display_name="OpenClaw VN",
            canonical_url="https://www.example.com/groups/openclawvn/?ref=share",
            attributes={"privacy": "public"},
            metrics={"member_count": 158_771},
            observed_at=first_seen,
            query="openclaw",
            rank=1,
        )
        second, created_again = await upsert_external_entity(
            db,
            org_id=ORG_A,
            platform="example",
            entity_type="group",
            display_name="OpenClaw Việt Nam",
            canonical_url="https://example.com/groups/openclawvn",
            attributes={"privacy": "public"},
            metrics={"member_count": 160_000},
            observed_at=second_seen,
            query="automation",
            rank=2,
        )
        await db.commit()

        assert created is True
        assert created_again is False
        assert second.id == first.id
        assert second.display_name == "OpenClaw Việt Nam"
        assert second.current_metrics["member_count"] == 160_000

        observations = await db.scalar(
            select(func.count(ExternalEntityObservation.id)).where(
                ExternalEntityObservation.external_entity_id == first.id
            )
        )
        discoveries = await db.scalar(
            select(func.count(ExternalEntityDiscovery.id)).where(
                ExternalEntityDiscovery.external_entity_id == first.id
            )
        )
        assert observations == 2
        assert discoveries == 2


@pytest.mark.asyncio
async def test_upsert_enriches_name_only_entity_without_creating_duplicate(
    session_factory,
):
    await _seed_orgs(session_factory)
    set_current_org_id(ORG_A)

    async with session_factory() as db:
        discovered, created = await upsert_external_entity(
            db,
            org_id=ORG_A,
            platform="example",
            entity_type="group",
            display_name="OpenClaw VN",
        )
        original_identity_key = discovered.identity_key
        enriched, created_again = await upsert_external_entity(
            db,
            org_id=ORG_A,
            platform="example",
            entity_type="group",
            display_name="OpenClaw VN",
            canonical_url="https://example.com/groups/openclawvn",
        )
        await db.commit()

        assert created is True
        assert created_again is False
        assert enriched.id == discovered.id
        assert enriched.identity_key == original_identity_key
        assert enriched.identity_confidence == "canonical_url"
        assert enriched.canonical_url == "https://example.com/groups/openclawvn"
        assert (
            await db.scalar(select(func.count(ExternalEntity.id)))
            == 1
        )


@pytest.mark.asyncio
async def test_catalog_lookup_never_crosses_org_boundary(session_factory):
    await _seed_orgs(session_factory)

    set_current_org_id(ORG_A)
    async with session_factory() as db:
        entity, _ = await upsert_external_entity(
            db,
            org_id=ORG_A,
            platform="example",
            entity_type="group",
            display_name="Tenant A Group",
            external_id="123",
        )
        await db.commit()
        entity_id = entity.id

    with tenant_context(ORG_B):
        async with session_factory() as db:
            assert (
                await get_external_entities_by_ids(
                    db,
                    org_id=ORG_B,
                    entity_ids=[entity_id],
                )
                == []
            )
            assert (
                await db.scalar(
                    select(func.count(ExternalEntity.id)).where(
                        ExternalEntity.id == entity_id
                    )
                )
                == 0
            )


@pytest.mark.asyncio
async def test_external_entity_api_observes_and_lists_current_org(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        observed = await client.post(
            "/api/external-entities/observe",
            json={
                "platform": "example",
                "entity_type": "group",
                "display_name": "API Group",
                "external_id": "api-group",
                "metrics": {"member_count": 99},
                "query": "api",
                "rank": 1,
            },
        )
        listed = await client.get(
            "/api/external-entities",
            params={"platform": "example", "entity_type": "group"},
        )

    assert observed.status_code == 200, observed.text
    assert observed.json()["created"] is True
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["display_name"] == "API Group"


