"""Nested run_scenario refs must land in the runtime registry.

Only the campaign's pinned refs were loaded, so a `run_scenario` step pointing
at another library scenario resolved to nothing and the run died with
"run_scenario: sub-scenario not found".
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from services.campaign.execution_runtime import build_org_scenario_registry
from services.org_scenario_validation.checks import build_org_ref_cache
from services.scenario_dsl.ref_cache import extract_run_scenario_id

# A (pinned) --loop--> B --> C, plus D which nobody references.
_BODIES = {
    "sc-a": {
        "steps": [
            {"id": "s1", "type": "wait", "seconds": 1},
            {
                "id": "s2",
                "type": "loop",
                "count": 2,
                "steps": [{"id": "s3", "type": "run_scenario", "scenario_id": "sc-b"}],
            },
        ]
    },
    "sc-b": {
        "steps": [
            {"id": "s1", "type": "composition.run_scenario", "config": {"scenario_id": "sc-c"}}
        ]
    },
    "sc-c": {"steps": [{"id": "s1", "type": "tap", "x": 1, "y": 2}]},
    "sc-d": {"steps": [{"id": "s1", "type": "tap", "x": 3, "y": 4}]},
}


async def _bodies(_db, _org_id, scenario_ids):
    return [(sid, "sequence", _BODIES[sid]) for sid in scenario_ids if sid in _BODIES]


async def _names(_db, _org_id, scenario_ids):
    return {sid: f"name-{sid}" for sid in scenario_ids if sid in _BODIES}


@pytest.mark.asyncio
async def test_registry_walks_nested_run_scenario_refs():
    bodies = AsyncMock(side_effect=_bodies)
    with patch("db.crud.org_scenario.get_org_scenario_bodies_by_ids", new=bodies), patch(
        "db.crud.org_scenario.get_org_scenario_names_by_ids", new=AsyncMock(side_effect=_names)
    ):
        registry = await build_org_scenario_registry(
            AsyncMock(), "org-1", [{"scenario_id": "sc-a"}]
        )

    # Nested in a loop (sc-b) and one level deeper (sc-c) both resolve.
    assert set(registry["by_id"]) == {"sc-a", "sc-b", "sc-c"}
    assert set(registry["by_campaign_name"]) == {"name-sc-a", "name-sc-b", "name-sc-c"}
    assert "sc-d" not in registry["by_id"]
    # One batched query per depth level, not one per scenario.
    assert [list(c.args[2]) for c in bodies.await_args_list] == [["sc-a"], ["sc-b"], ["sc-c"]]


@pytest.mark.asyncio
async def test_registry_stops_on_circular_refs():
    loop_bodies = {
        "sc-x": {"steps": [{"id": "s1", "type": "run_scenario", "scenario_id": "sc-y"}]},
        "sc-y": {"steps": [{"id": "s1", "type": "run_scenario", "scenario_id": "sc-x"}]},
    }

    async def bodies(_db, _org_id, scenario_ids):
        return [(sid, "sequence", loop_bodies[sid]) for sid in scenario_ids if sid in loop_bodies]

    async def names(_db, _org_id, scenario_ids):
        return {sid: f"name-{sid}" for sid in scenario_ids if sid in loop_bodies}

    with patch(
        "db.crud.org_scenario.get_org_scenario_bodies_by_ids", new=AsyncMock(side_effect=bodies)
    ), patch(
        "db.crud.org_scenario.get_org_scenario_names_by_ids", new=AsyncMock(side_effect=names)
    ):
        registry = await build_org_scenario_registry(
            AsyncMock(), "org-1", [{"scenario_id": "sc-x"}]
        )

    assert set(registry["by_id"]) == {"sc-x", "sc-y"}


@pytest.mark.asyncio
async def test_validation_ref_cache_collects_normalized_root_scenario_id():
    bodies = AsyncMock(
        return_value=[
            (
                "sc-child",
                "sequence",
                {"steps": []},
                "draft",
                1,
            )
        ]
    )
    root_body = {
        "steps": [
            {
                "id": "run-child",
                "type": "run_scenario",
                "scenario_id": "sc-child",
                "config": {},
            }
        ]
    }

    with patch("db.crud.org_scenario.get_org_scenario_refs_by_ids", new=bodies):
        cache = await build_org_ref_cache(
            AsyncMock(),
            org_id="org-1",
            root_scenario_id="sc-root",
            root_kind="sequence",
            root_body=root_body,
            root_status="draft",
            root_version=1,
            depth_limit=3,
        )

    assert cache.get("sc-child") == ("sequence", {"steps": []}, "draft", 1)
    bodies.assert_awaited_once()
    assert list(bodies.await_args.args[2]) == ["sc-child"]


def test_extract_run_scenario_id_accepts_both_type_spellings():
    assert extract_run_scenario_id({"type": "run_scenario", "scenario_id": "a"}) == "a"
    assert (
        extract_run_scenario_id(
            {"type": "composition.run_scenario", "config": {"scenario_id": "b"}}
        )
        == "b"
    )
    assert (
        extract_run_scenario_id(
            {"type": "run_scenario", "scenario_id": "c", "config": {}}
        )
        == "c"
    )
    assert (
        extract_run_scenario_id(
            {
                "type": "run_scenario",
                "scenario_id": "root",
                "config": {"scenario_id": "config"},
            }
        )
        == "config"
    )
    assert extract_run_scenario_id({"type": "tap", "scenario_id": "d"}) is None
