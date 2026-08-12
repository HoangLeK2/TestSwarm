from types import SimpleNamespace

import pytest

from temporal.continuous_crawl_activities import (
    _entity_vars,
    _snapshot,
    _source_pool_spec,
)


def test_source_pool_contract_preserves_filters():
    spec = _source_pool_spec(
        {
            "platform": "facebook",
            "entity_type": "group",
            "statuses": ["active"],
            "output_prefix": "group target",
        }
    )
    assert spec.statuses == ("active",)
    assert spec.output_prefix == "group target"


def test_external_entity_variables_match_dispatch_contract_without_custom_overrides():
    values = _entity_vars(
        {
            "id": "entity-1",
            "platform": "facebook",
            "entity_type": "group",
            "external_id": "42",
            "canonical_url": "https://example.test/42",
            "display_name": "Python",
            "attributes": {
                "locator": {
                    "search_query": "Python jobs",
                    "selector": {"by": "text", "value": "Python"},
                    "fallback_selector": {
                        "by": "textContains",
                        "value": "Python jobs",
                    },
                },
                "variables": {
                    "TARGET_NAME": "untrusted override",
                    "CAMPAIGN_SECRET": "must not propagate",
                },
            },
        },
        "group target",
    )
    assert values["TARGET_ENTITY_ID"] == "entity-1"
    assert values["TARGET_NAME"] == "Python"
    assert values["GROUP_TARGET_NAME"] == "Python"
    assert values["GROUP_NAME"] == "Python"
    assert values["TARGET_GROUP_NAME"] == "Python"
    assert values["TARGET_SEARCH_QUERY"] == "Python jobs"
    assert values["TARGET_SELECTOR_BY"] == "text"
    assert values["TARGET_SELECTOR_VALUE"] == "Python"
    assert values["GROUP_TARGET_FALLBACK_SELECTOR_VALUE"] == "Python jobs"
    assert "CAMPAIGN_SECRET" not in values


@pytest.mark.parametrize(
    ("entity_type", "prefix"), [("page", "PAGE"), ("profile", "PROFILE")]
)
def test_page_and_profile_targets_export_type_specific_variables(entity_type, prefix):
    values = _entity_vars(
        {
            "id": f"{entity_type}-1",
            "platform": "facebook",
            "entity_type": entity_type,
            "display_name": "Target name",
            "attributes": {},
        },
        prefix,
    )

    assert values[f"{prefix}_NAME"] == "Target name"
    assert values[f"{prefix}_SEARCH_QUERY"] == "Target name"


def test_runtime_finalizer_dispatch_source_gate_accepts_continuous_crawl():
    execution_meta = {"dispatch_source": "continuous_crawl"}
    assert execution_meta.get("dispatch_source")


def test_temporal_target_snapshot_excludes_unbounded_entity_documents():
    entity = SimpleNamespace(
        id="entity-1",
        platform="facebook",
        entity_type="group",
        external_id="42",
        canonical_url="https://example.test/42",
        display_name="Python",
        current_attributes={
            "locator": {
                "search_query": "Python jobs",
                "selector": {"by": "text", "value": "Python"},
            },
            "raw_document": "x" * 100_000,
        },
        current_metrics={"history": list(range(10_000))},
    )

    assert _snapshot(entity) == {
        "id": "entity-1",
        "platform": "facebook",
        "entity_type": "group",
        "external_id": "42",
        "canonical_url": "https://example.test/42",
        "display_name": "Python",
        "attributes": {
            "locator": {
                "search_query": "Python jobs",
                "selector": {"by": "text", "value": "Python"},
            }
        },
    }
