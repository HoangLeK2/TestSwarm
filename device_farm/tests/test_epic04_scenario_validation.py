"""Epic 04 DF-T-04-004: org scenario validation pipeline."""
from __future__ import annotations

import time

import pytest

pytest_plugins = ["tests.test_epic04_scenario_entity"]

from httpx import ASGITransport, AsyncClient

from tests.test_epic04_scenario_entity import _build_app, _seed_orgs


def _sequence_step(step_id: str, step_type: str, **config):
    return {
        "id": step_id,
        "type": step_type,
        "config": config,
    }


@pytest.mark.asyncio
async def test_ac1_valid_scenario_validate_pass(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/scenarios",
            json={"name": "Valid", "kind": "sequence"},
        )
        scenario_id = created.json()["id"]
        await client.post(
            f"/api/scenarios/{scenario_id}/body",
            json={
                "steps": [
                    _sequence_step("open", "navigation.open_app", package="com.app"),
                    _sequence_step("wait", "input_wait.wait", seconds=1),
                ],
                "variables": {"KEYWORD": "hello"},
            },
        )
        resp = await client.post(f"/api/scenarios/{scenario_id}/validate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "valid"
    assert data["errors"] == []
    assert data["last_validation_summary"]["status"] == "valid"


@pytest.mark.asyncio
async def test_ac2_graph_unreachable_node(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/scenarios",
            json={"name": "BadGraph", "kind": "graph"},
        )
        scenario_id = created.json()["id"]
        body = {
            "nodes": [
                _sequence_step("A", "input_wait.wait", seconds=1),
                _sequence_step("Z", "input_wait.wait", seconds=1),
            ],
            "edges": [],
        }
        validate = await client.post(
            f"/api/scenarios/{scenario_id}/validate",
            json=body,
        )
        save = await client.post(f"/api/scenarios/{scenario_id}/body", json=body)
        save_force = await client.post(
            f"/api/scenarios/{scenario_id}/body?force=true",
            json=body,
        )
    assert validate.status_code == 200
    assert validate.json()["status"] == "invalid"
    assert any(e["code"] == "GRAPH_UNREACHABLE_NODE" for e in validate.json()["errors"])
    assert save.status_code == 400
    assert save_force.status_code == 200


@pytest.mark.asyncio
async def test_ac3_undeclared_variable(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/scenarios",
            json={"name": "BadVar", "kind": "sequence"},
        )
        scenario_id = created.json()["id"]
        resp = await client.post(
            f"/api/scenarios/{scenario_id}/validate",
            json={
                "steps": [
                    _sequence_step(
                        "tap_search",
                        "interaction.tap",
                        selector="${magic_var}",
                    ),
                ],
            },
        )
    assert resp.status_code == 200
    errors = resp.json()["errors"]
    assert any(e["code"] == "UNDECLARED_VARIABLE" for e in errors)
    err = next(e for e in errors if e["code"] == "UNDECLARED_VARIABLE")
    assert "magic_var" in err["message"]
    assert "tap_search" in err["location"]


@pytest.mark.asyncio
async def test_ac4_scenario_ref_not_found_and_bad_version(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/scenarios",
            json={"name": "Parent", "kind": "sequence"},
        )
        scenario_id = created.json()["id"]

        missing = await client.post(
            f"/api/scenarios/{scenario_id}/validate",
            json={
                "steps": [
                    {
                        "id": "run_sub",
                        "type": "composition.run_scenario",
                        "config": {"scenario_id": "S_missing", "scenario_version": 1},
                    },
                ],
            },
        )

        child = await client.post(
            "/api/scenarios",
            json={"name": "Child", "kind": "sequence"},
        )
        child_id = child.json()["id"]
        bad_version = await client.post(
            f"/api/scenarios/{scenario_id}/validate",
            json={
                "steps": [
                    {
                        "id": "run_sub2",
                        "type": "composition.run_scenario",
                        "config": {"scenario_id": child_id, "scenario_version": 99},
                    },
                ],
            },
        )
    assert any(e["code"] == "SCENARIO_REF_NOT_FOUND" for e in missing.json()["errors"])
    assert any(e["code"] == "SCENARIO_VERSION_NOT_FOUND" for e in bad_version.json()["errors"])


@pytest.mark.asyncio
async def test_ac5_invalid_on_error_target(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/scenarios",
            json={"name": "BadOnError", "kind": "sequence"},
        )
        scenario_id = created.json()["id"]
        resp = await client.post(
            f"/api/scenarios/{scenario_id}/validate",
            json={
                "steps": [
                    {
                        "id": "s1",
                        "type": "input_wait.wait",
                        "config": {"seconds": 1},
                        "on_error": "s_recovery",
                    },
                ],
            },
        )
    assert any(e["code"] == "INVALID_ON_ERROR_TARGET" for e in resp.json()["errors"])


@pytest.mark.asyncio
async def test_ac6_no_verification_warning_allows_save(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/scenarios",
            json={"name": "SocialNoVerify", "kind": "sequence"},
        )
        scenario_id = created.json()["id"]
        body = {
            "steps": [
                _sequence_step(f"tap_{i}", "interaction.tap", selector=f"id:{i}")
                for i in range(3)
            ],
        }
        validate = await client.post(
            f"/api/scenarios/{scenario_id}/validate",
            json=body,
        )
        save = await client.post(f"/api/scenarios/{scenario_id}/body", json=body)
    assert validate.json()["status"] == "valid"
    assert any(w["code"] == "NO_VERIFICATION_STEP" for w in validate.json()["warnings"])
    assert save.status_code == 200


@pytest.mark.asyncio
async def test_tc06_circular_scenario_reference(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        s1 = await client.post("/api/scenarios", json={"name": "S1", "kind": "sequence"})
        s2 = await client.post("/api/scenarios", json={"name": "S2", "kind": "sequence"})
        s1_id = s1.json()["id"]
        s2_id = s2.json()["id"]

        await client.post(
            f"/api/scenarios/{s2_id}/body",
            json={
                "steps": [
                    {
                        "id": "to_s1",
                        "type": "composition.run_scenario",
                        "config": {"scenario_id": s1_id},
                    },
                ],
            },
        )
        resp = await client.post(
            f"/api/scenarios/{s1_id}/validate",
            json={
                "steps": [
                    {
                        "id": "to_s2",
                        "type": "composition.run_scenario",
                        "config": {"scenario_id": s2_id},
                    },
                ],
            },
        )
    assert any(e["code"] == "CIRCULAR_SCENARIO_REFERENCE" for e in resp.json()["errors"])


@pytest.mark.asyncio
async def test_validate_500_steps_under_500ms(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    steps = [
        _sequence_step(f"s{i}", "input_wait.wait", seconds=1)
        for i in range(500)
    ]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/scenarios",
            json={"name": "Perf500", "kind": "sequence"},
        )
        scenario_id = created.json()["id"]
        started = time.perf_counter()
        resp = await client.post(
            f"/api/scenarios/{scenario_id}/validate",
            json={"steps": steps},
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert resp.status_code == 200
    assert elapsed_ms < 500.0
