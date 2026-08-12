from datetime import UTC, datetime

import pytest

from db.crud.external_entity import upsert_external_entity
from services.campaign.continuous_crawl import (
    CONTINUOUS_CRAWL_MODE,
    ContinuousCrawlConfigError,
    crawl_execution_idempotency_key,
    crawl_workflow_id,
    parse_continuous_crawl_config,
    source_filter_hash,
)
from services.campaign.entity_allocation import SourcePoolSpec, load_source_pool_page
from services.campaign.source_pool_steps import source_pool_from_step


def test_continuous_config_is_bounded_and_typed():
    config = parse_continuous_crawl_config(
        {
            "_crawl": {
                "mode": CONTINUOUS_CRAWL_MODE,
                "max_concurrency": 20,
                "source_page_size": 1000,
                "target_retry": {"maximum_attempts": 5},
            }
        }
    )
    assert config.continuous is True
    assert config.max_concurrency == 20
    assert config.source_page_size == 1000
    assert config.maximum_attempts == 5


@pytest.mark.parametrize(
    "crawl",
    [
        {"mode": "unknown"},
        {"max_concurrency": 0},
        {"source_page_size": 2001},
        {"max_failure_ratio": 1.1},
        {"target_retry": {"maximum_attempts": 0}},
    ],
)
def test_continuous_config_rejects_unsafe_values(crawl):
    with pytest.raises(ContinuousCrawlConfigError):
        parse_continuous_crawl_config({"_crawl": crawl})


def test_continuous_identifiers_are_deterministic():
    assert crawl_workflow_id("c1", "d1") == "campaign:c1:crawl:d1"
    assert crawl_execution_idempotency_key("c1", "d1", "phone-a", "e1") == (
        "campaign-crawl:c1:d1:phone-a:e1"
    )


@pytest.mark.parametrize(
    ("entity_type", "expected_prefix"),
    [("group", "GROUP"), ("page", "PAGE"), ("profile", "PROFILE")],
)
def test_assigned_target_step_defaults_prefix_by_type(entity_type, expected_prefix):
    spec = source_pool_from_step(
        {"type": "use_source_pool", "entity_type": entity_type}
    )

    assert spec is not None
    assert spec.output_prefix == expected_prefix
    assert source_filter_hash({"b": 2, "a": 1}) == source_filter_hash({"a": 1, "b": 2})


@pytest.mark.asyncio
async def test_source_pool_page_is_keyset_paginated(
    tenancy_session_factory,
):
    session_factory = tenancy_session_factory
    org_id = "org-frontier"
    async with session_factory() as db:
        from db.models.organization import Organization

        db.add(Organization(id=org_id, business_name="Frontier Org"))
        await db.flush()
        entities = []
        for index in range(3):
            entity, _ = await upsert_external_entity(
                db,
                org_id=org_id,
                platform="facebook",
                entity_type="profile",
                display_name=f"Profile {index}",
                external_id=f"profile-{index}",
            )
            entities.append(entity)
        await db.commit()

    snapshot_at = datetime.now(UTC)
    spec = SourcePoolSpec(platform="facebook", entity_type="profile")
    async with session_factory() as db:
        first = await load_source_pool_page(
            db,
            org_id=org_id,
            spec=spec,
            dispatch_id="dispatch-1",
            snapshot_at=snapshot_at,
            cursor=None,
            limit=2,
        )
        assert [entity.id for entity in first.entities] == sorted(
            entity.id for entity in entities
        )[:2]
        assert first.exhausted is False
        second = await load_source_pool_page(
            db,
            org_id=org_id,
            spec=spec,
            dispatch_id="dispatch-1",
            snapshot_at=snapshot_at,
            cursor=first.next_cursor,
            limit=2,
        )
        assert len(second.entities) == 1
        assert second.exhausted is True
