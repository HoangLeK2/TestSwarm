"""Epic 04 DF-T-04-002: scenario DSL, step contract, body validation API."""
from __future__ import annotations

import pytest

pytest_plugins = ["tests.test_epic04_scenario_entity"]

from httpx import ASGITransport, AsyncClient

from services.scenario_dsl import (
    StepRegistry,
    assert_no_implicit_recovery,
    effective_error_policy,
    normalize_step,
)
from services.scenario_dsl.step_handler import StepResult
from services.scenario_dsl.variable_resolver import EffectiveVariableResolver
from tests.test_epic04_scenario_entity import _build_app, _seed_orgs


class _StubHandler:
    async def execute(self, ctx, step) -> StepResult:
        return StepResult(ok=True)


@pytest.fixture(autouse=True)
def _reset_step_registry():
    StepRegistry.reset_for_tests()
    yield
    StepRegistry.reset_for_tests()


def _sequence_step(step_id: str, step_type: str, **config):
    return {
        "id": step_id,
        "type": step_type,
        "config": config,
    }


@pytest.mark.asyncio
async def test_ac1_post_sequence_body_is_runnable(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/scenarios",
            json={"name": "FB-Open", "kind": "sequence"},
        )
        scenario_id = created.json()["id"]
        resp = await client.post(
            f"/api/scenarios/{scenario_id}/body",
            json={
                "steps": [
                    _sequence_step("open_fb", "navigation.open_app", package="com.facebook.katana"),
                    _sequence_step("tap_search", "interaction.tap", selector="id:search_btn"),
                ]
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_runnable"] is True
    assert data["validation"]["status"] == "valid"
    assert data["body_json"]["steps"][0]["error_policy"] == "stop"
    assert data["body_json"]["steps"][0]["pre_capture"] is False


@pytest.mark.asyncio
async def test_list_scenarios_reports_is_runnable(session_factory):
    """List API must not always return is_runnable=false (body_json was deferred)."""
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/scenarios",
            json={"name": "ListRunnable", "kind": "sequence"},
        )
        scenario_id = created.json()["id"]
        await client.post(
            f"/api/scenarios/{scenario_id}/body",
            json={
                "steps": [
                    _sequence_step("s1", "input_wait.wait", seconds=1),
                ]
            },
        )
        listed = await client.get("/api/scenarios")
    assert listed.status_code == 200
    row = next((s for s in listed.json() if s["id"] == scenario_id), None)
    assert row is not None
    assert row["is_runnable"] is True


@pytest.mark.asyncio
async def test_ac2_graph_body_with_conditions(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/scenarios",
            json={"name": "GraphFlow", "kind": "graph"},
        )
        scenario_id = created.json()["id"]
        resp = await client.post(
            f"/api/scenarios/{scenario_id}/body",
            json={
                "nodes": [
                    _sequence_step("A", "navigation.open_app", package="com.app"),
                    _sequence_step("B", "interaction.tap", selector="id:close"),
                    _sequence_step("C", "input_wait.wait", seconds=1),
                ],
                "edges": [
                    {
                        "source": "A",
                        "target": "B",
                        "condition": {"if_element": "id:popup_close"},
                    },
                    {"source": "A", "target": "C", "condition": {"else": True}},
                ],
            },
        )
    assert resp.status_code == 200
    body = resp.json()["body_json"]
    assert len(body["edges"]) == 2
    assert body["edges"][0]["condition"]["if_element"] == "id:popup_close"


@pytest.mark.asyncio
async def test_ac3_unknown_step_type_rejected(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/scenarios",
            json={"name": "BadType", "kind": "sequence"},
        )
        scenario_id = created.json()["id"]
        resp = await client.post(
            f"/api/scenarios/{scenario_id}/body",
            json={
                "steps": [
                    {"id": "x", "type": "weird_step.do_thing", "config": {}},
                ]
            },
        )
        got = await client.get(f"/api/scenarios/{scenario_id}/body")
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "UNKNOWN_STEP_TYPE"
    assert detail["errors"][0]["code"] == "UNKNOWN_STEP_TYPE"
    assert got.json()["is_runnable"] is False


@pytest.mark.asyncio
async def test_tc03_duplicate_step_id(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/api/scenarios", json={"name": "Dup", "kind": "sequence"})
        scenario_id = created.json()["id"]
        resp = await client.post(
            f"/api/scenarios/{scenario_id}/body",
            json={
                "steps": [
                    _sequence_step("s1", "input_wait.wait", seconds=1),
                    _sequence_step("s1", "interaction.tap", selector="id:x"),
                ]
            },
        )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "DUPLICATE_STEP_ID"


@pytest.mark.asyncio
async def test_ac4_default_stop_on_regular_steps_no_warnings(session_factory):
    steps = [
        {"id": "s1", "type": "interaction.tap", "config": {"selector": "a"}},
        {"id": "s2", "type": "input_wait.wait", "config": {"seconds": 1}},
        {"id": "s3", "type": "verification.verify_screen", "config": {}},
    ]
    normalized = [normalize_step(s) for s in steps]
    for step in normalized:
        assert effective_error_policy(step) == "stop"
    assert_no_implicit_recovery(steps)

    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/api/scenarios", json={"name": "Defaults", "kind": "sequence"})
        scenario_id = created.json()["id"]
        resp = await client.post(
            f"/api/scenarios/{scenario_id}/body",
            json={"steps": steps},
        )
    assert resp.status_code == 200
    assert resp.json()["is_runnable"] is True


def test_fr04_20_guard_no_implicit_recovery_on_normalize():
    raw = {"id": "a", "type": "interaction.tap", "config": {}}
    out = normalize_step(raw)
    assert out["error_policy"] == "stop"
    assert out["retry"] is None
    assert_no_implicit_recovery([raw])


def test_normalize_extract_defaults_capture_on():
    out = normalize_step({"id": "x", "type": "extract", "config": {"strategy": "fb_posts"}})
    assert out["pre_capture"] is True
    assert out["post_capture"] is True


def test_fr04_20_normalize_never_adds_on_error_branch():
    step = {"id": "s1", "type": "input_wait.wait", "config": {"seconds": 2}}
    normalized = normalize_step(step)
    assert "on_error" not in normalized or normalized.get("on_error") in (None, "")


def test_fr04_20_effective_policy_stops_regular_steps_unless_declared():
    assert effective_error_policy({"id": "x", "type": "input_wait.wait"}) == "stop"
    assert effective_error_policy({"id": "x", "type": "input_wait.wait", "error_policy": "ignore"}) == "ignore"
    assert effective_error_policy({"id": "x", "type": "input_wait.wait", "error_policy": "continue"}) == "ignore"
    assert effective_error_policy({"id": "x", "type": "input_wait.wait", "error_policy": "stop"}) == "stop"


def test_run_scenario_default_policy_stops_parent_flow():
    assert effective_error_policy({"id": "x", "type": "run_scenario"}) == "stop"
    assert effective_error_policy({"id": "x", "type": "composition.run_scenario"}) == "stop"
    assert effective_error_policy({"id": "x", "type": "run_scenario", "error_policy": "stop"}) == "stop"


def test_legacy_runtime_step_types_are_known():
    """Flat executor step types (imports / graph nodes) must pass org body validation."""
    legacy = [
        "launch_app",
        "if_element",
        "tap_selector",
        "tap_ratio",
        "wait_stable",
        "scroll_down",
        "social_open_comments",
        "social_open_comments",
    ]
    for step_type in legacy:
        assert StepRegistry.is_known_type(step_type), step_type


@pytest.mark.asyncio
async def test_ac5_nested_depth_exceeded(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    ids: list[str] = []
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for i in range(7):
            created = await client.post(
                "/api/scenarios",
                json={"name": f"Nest-{i}", "kind": "sequence"},
            )
            ids.append(created.json()["id"])

        for i in range(6):
            child_id = ids[i + 1]
            await client.post(
                f"/api/scenarios/{ids[i]}/body",
                json={
                    "steps": [
                        {
                            "id": f"run_{i}",
                            "type": "composition.run_scenario",
                            "config": {"scenario_id": child_id},
                        }
                    ]
                },
            )

        resp = await client.post(
            f"/api/scenarios/{ids[0]}/body",
            json={
                "steps": [
                    {
                        "id": "run_root",
                        "type": "composition.run_scenario",
                        "config": {"scenario_id": ids[1]},
                    }
                ]
            },
        )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "SCENARIO_DEPTH_EXCEEDED"


def test_ac6_variable_resolve_priority():
    resolver = EffectiveVariableResolver(
        campaign_vars={"keyword": "campaign_kw"},
        scenario_vars={"keyword": "scenario_kw"},
        device_vars={"keyword": "device_kw"},
        account_vars={"keyword": "account_kw"},
        runtime_vars={"keyword": "runtime_kw"},
    )
    value, provenance = resolver.resolve_with_provenance("${keyword}")
    assert value == "runtime_kw"
    assert provenance["keyword"] == "runtime"

    resolver.runtime_vars.pop("keyword")
    value, provenance = resolver.resolve_with_provenance("${keyword}")
    assert value == "account_kw"
    assert provenance["keyword"] == "account"

    resolver.account_vars.pop("keyword")
    value, provenance = resolver.resolve_with_provenance("${keyword}")
    assert value == "device_kw"
    assert provenance["keyword"] == "device"


@pytest.mark.asyncio
async def test_tc08_custom_step_registry(session_factory):
    StepRegistry.register("social_open_comments", _StubHandler())

    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/api/scenarios", json={"name": "FB", "kind": "sequence"})
        scenario_id = created.json()["id"]
        resp = await client.post(
            f"/api/scenarios/{scenario_id}/body",
            json={
                "steps": [
                    {"id": "fb1", "type": "social_open_comments", "config": {"post_id": "123"}},
                ]
            },
        )
    assert resp.status_code == 200
    assert resp.json()["is_runnable"] is True


@pytest.mark.asyncio
async def test_get_scenario_body(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/api/scenarios", json={"name": "ReadBody", "kind": "sequence"})
        scenario_id = created.json()["id"]
        await client.post(
            f"/api/scenarios/{scenario_id}/body",
            json={"steps": [_sequence_step("w", "input_wait.wait", seconds=2)]},
        )
        resp = await client.get(f"/api/scenarios/{scenario_id}/body")
    assert resp.status_code == 200
    assert resp.json()["body_json"]["steps"][0]["id"] == "w"


@pytest.mark.asyncio
async def test_post_scenario_body_replaces_previous_body_on_reload(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/scenarios",
            json={"name": "ReloadLatestBody", "kind": "sequence"},
        )
        scenario_id = created.json()["id"]
        first = await client.post(
            f"/api/scenarios/{scenario_id}/body",
            json={
                "steps": [
                    {
                        "id": "scroll",
                        "type": "input_wait.wait",
                        "description": "old description",
                        "config": {"seconds": 1},
                    }
                ],
                "variables": {"GROUP_TEXT": "old group"},
            },
        )
        second = await client.post(
            f"/api/scenarios/{scenario_id}/body",
            json={
                "steps": [
                    {
                        "id": "scroll",
                        "type": "input_wait.wait",
                        "description": "${GROUP_TEXT}",
                        "config": {"seconds": 2, "x": "${SCROLL_X_RATIO}"},
                    }
                ],
                "variables": {
                    "GROUP_TEXT": "Codex VN,Cong khai - 193K thanh vien",
                    "SCROLL_X_RATIO": 0.18,
                },
            },
        )
        reloaded = await client.get(f"/api/scenarios/{scenario_id}/body")
        detail = await client.get(f"/api/scenarios/{scenario_id}")

    assert first.status_code == 200
    assert second.status_code == 200
    body = reloaded.json()["body_json"]
    assert reloaded.status_code == 200
    assert body["steps"][0]["description"] == "${GROUP_TEXT}"
    assert body["steps"][0]["config"]["seconds"] == 2
    assert body["steps"][0]["config"]["x"] == "${SCROLL_X_RATIO}"
    assert body["variables"]["GROUP_TEXT"] == "Codex VN,Cong khai - 193K thanh vien"
    detail_body = detail.json()["body_json"]
    assert detail.status_code == 200
    assert detail_body["steps"][0]["description"] == "${GROUP_TEXT}"
    assert detail_body["steps"][0]["config"]["seconds"] == 2


@pytest.mark.asyncio
async def test_invalid_graph_edge(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/api/scenarios", json={"name": "BadEdge", "kind": "graph"})
        scenario_id = created.json()["id"]
        resp = await client.post(
            f"/api/scenarios/{scenario_id}/body",
            json={
                "nodes": [_sequence_step("A", "input_wait.wait", seconds=1)],
                "edges": [{"source": "A", "target": "MISSING"}],
            },
        )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "INVALID_GRAPH_EDGE"
