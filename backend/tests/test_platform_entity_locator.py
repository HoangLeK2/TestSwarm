"""Snapshot of the TARGET_* variables a dispatched entity produces.

Written before the entity-locator extraction (plan A2) so the refactor is proven
to be output-identical, not merely plausible.
"""

from __future__ import annotations

from types import SimpleNamespace

from services.campaign.dispatcher import _with_external_entity_vars
from services.campaign.entity_allocation import SourcePoolSpec


def _entity(platform: str, entity_type: str, **attrs):
    return SimpleNamespace(
        id="ent-1",
        platform=platform,
        entity_type=entity_type,
        external_id="ext-1",
        canonical_url="https://example.test/ent-1",
        display_name="Group One",
        current_attributes=attrs,
    )


def test_instagram_group_locator_defaults():
    assert _with_external_entity_vars({}, _entity("instagram", "group")) == {
        "TARGET_ENTITY_ID": "ent-1",
        "TARGET_PLATFORM": "instagram",
        "TARGET_ENTITY_TYPE": "group",
        "TARGET_EXTERNAL_ID": "ext-1",
        "TARGET_URL": "https://example.test/ent-1",
        "TARGET_NAME": "Group One",
        "TARGET_SEARCH_QUERY": "Group One",
        "TARGET_SELECTOR_BY": "descriptionStartsWith",
        "TARGET_SELECTOR_VALUE": "Group One,",
        "TARGET_FALLBACK_SELECTOR_BY": "descriptionContains",
        "TARGET_FALLBACK_SELECTOR_VALUE": "Group One",
        "TARGET_LOCATOR": {},
        "GROUP_NAME": "Group One",
        "TARGET_GROUP_NAME": "Group One",
    }


def test_non_group_and_other_platform_use_neutral_defaults():
    neutral = {
        "TARGET_SELECTOR_BY": "text",
        "TARGET_SELECTOR_VALUE": "Group One",
        "TARGET_FALLBACK_SELECTOR_BY": "textContains",
        "TARGET_FALLBACK_SELECTOR_VALUE": "Group One",
    }
    for entity in (_entity("instagram", "page"), _entity("tiktok", "group")):
        values = _with_external_entity_vars({}, entity)
        assert {key: values[key] for key in neutral} == neutral
        assert "GROUP_NAME" not in values
        assert "TARGET_GROUP_NAME" not in values


def test_stored_locator_overrides_platform_defaults():
    entity = _entity(
        "instagram",
        "group",
        locator={
            "search_query": "custom query",
            "selector": {"by": "resourceId", "value": "com.x:id/y"},
            "fallback_selector": {"by": "text", "value": "fallback"},
        },
    )
    values = _with_external_entity_vars({}, entity)
    assert values["TARGET_SEARCH_QUERY"] == "custom query"
    assert values["TARGET_SELECTOR_BY"] == "resourceId"
    assert values["TARGET_SELECTOR_VALUE"] == "com.x:id/y"
    assert values["TARGET_FALLBACK_SELECTOR_BY"] == "text"
    assert values["TARGET_FALLBACK_SELECTOR_VALUE"] == "fallback"
    assert values["GROUP_NAME"] == "Group One"


def test_output_prefix_mirrors_target_vars():
    entity = _entity("instagram", "group")
    pool = SourcePoolSpec(platform="instagram", entity_type="group", output_prefix="src")
    values = _with_external_entity_vars({}, entity, source_pool=pool)
    assert values["SRC_ENTITY_ID"] == "ent-1"
    assert values["SRC_NAME"] == "Group One"
    assert values["SRC_SEARCH_QUERY"] == "Group One"
    assert values["SRC_SELECTOR_BY"] == "descriptionStartsWith"
    assert values["SRC_SELECTOR_VALUE"] == "Group One,"
    assert values["SRC_FALLBACK_SELECTOR_BY"] == "descriptionContains"
    assert values["SRC_FALLBACK_SELECTOR_VALUE"] == "Group One"


def test_no_entity_passes_effective_vars_through():
    assert _with_external_entity_vars({"A": 1}, None) == {"A": 1}
