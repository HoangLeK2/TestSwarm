"""Tests for DF-T-04-004 scenario validation pipeline."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.scenario_validation.checks import (
    check_graph,
    check_lint_warnings,
    check_on_error_targets,
    check_retry_config,
    check_scenario_references,
    check_variables,
)
from services.scenario_validation.models import ValidationResult
from services.scenario_validation.ref_cache import ScenarioRefCache
from services.scenario_validation.step_index import StepIndex
from services.scenario_validation.validator import ScenarioValidator


def _result() -> ValidationResult:
    return ValidationResult()


def _idx(steps: list[dict]) -> StepIndex:
    return StepIndex.build(steps)


def test_graph_unreachable_node() -> None:
    result = _result()
    nodes = [
        {"id": "start", "type": "wait", "order": "a0", "config": {}},
        {"id": "orphan", "type": "wait", "order": "a1", "config": {}},
    ]
    check_graph(nodes, [], result)
    assert result.status == "invalid"
    assert "GRAPH_UNREACHABLE_NODE" in [e.code for e in result.errors]


def test_graph_nested_scope_nodes_are_reachable() -> None:
    result = _result()
    nodes = [
        {"id": "root", "type": "tap_fb_comment_button", "order": "a0", "config": {}},
        {
            "id": "child",
            "type": "extract",
            "order": "a0",
            "scope": {"parentId": "root", "branch": "then"},
            "config": {},
        },
    ]
    check_graph(nodes, [], result)
    assert result.status == "valid"
    assert not result.errors


def test_graph_last_root_step_without_outgoing_edge_is_valid() -> None:
    result = _result()
    nodes = [
        {"id": "first", "type": "open_app", "order": "a0", "config": {}},
        {"id": "last", "type": "extract", "order": "a1", "config": {"strategy": "fb_posts"}},
    ]
    edges = [{"source": "first", "target": "last"}]
    check_graph(nodes, edges, result)
    assert not any(e.code == "GRAPH_DEAD_END_NODE" for e in result.errors)


def test_graph_dead_end_mid_chain_still_invalid() -> None:
    result = _result()
    nodes = [
        {"id": "a", "type": "open_app", "order": "a0", "config": {}},
        {"id": "b", "type": "custom_unknown_step", "order": "a1", "config": {}},
        {"id": "c", "type": "extract", "order": "a2", "config": {}},
    ]
    edges = [{"source": "a", "target": "b"}]
    check_graph(nodes, edges, result)
    assert any(
        e.code == "GRAPH_DEAD_END_NODE" and e.location == "node.b"
        for e in result.errors
    )


def test_graph_dead_end_container_with_children_is_allowed() -> None:
    result = _result()
    nodes = [
        {"id": "loop", "type": "loop", "order": "a0", "config": {}},
        {
            "id": "inner",
            "type": "wait",
            "order": "a0",
            "scope": {"parentId": "loop", "branch": "steps"},
            "config": {},
        },
    ]
    check_graph(nodes, [], result)
    assert not any(e.code == "GRAPH_DEAD_END_NODE" for e in result.errors)


def test_undeclared_variable() -> None:
    result = _result()
    steps = [
        {
            "id": "tap_search",
            "type": "tap_selector",
            "selector": {"by": "text", "value": "${magic_var}"},
        }
    ]
    check_variables(_idx(steps), {}, {}, result)
    assert any(e.code == "UNDECLARED_VARIABLE" for e in result.errors)


def test_declared_variable_in_scenario_defaults() -> None:
    result = _result()
    steps = [{"type": "tap_selector", "selector": {"by": "text", "value": "${KEYWORD}"}}]
    check_variables(_idx(steps), {"KEYWORD": "hello"}, {}, result)
    assert not result.errors


def test_set_variable_declares_for_following_steps() -> None:
    result = _result()
    steps = [
        {"type": "set_variable", "name": "X", "value": 1},
        {"type": "wait", "seconds": "${X}"},
    ]
    check_variables(_idx(steps), {}, {}, result)
    assert not result.errors


def test_set_variable_in_loop_body_before_wait() -> None:
    """Regression: parent loop must not scan nested steps before index walk."""
    result = _result()
    steps = [
        {
            "type": "loop",
            "count": 3,
            "steps": [
                {"type": "set_variable", "name": "_W", "from_list": [0.5, 1, 2]},
                {"type": "wait", "seconds": "${_W}"},
            ],
        },
    ]
    check_variables(_idx(steps), {}, {}, result)
    assert not any(e.code == "UNDECLARED_VARIABLE" for e in result.errors)


def test_invalid_on_error_target() -> None:
    result = _result()
    steps = [{"id": "s1", "type": "wait", "on_error": "s_recovery"}]
    check_on_error_targets(_idx(steps), result)
    assert any(e.code == "INVALID_ON_ERROR_TARGET" for e in result.errors)


def test_on_error_policy_pause_allowed() -> None:
    result = _result()
    steps = [{"id": "s1", "type": "wait", "on_error": "pause"}]
    check_on_error_targets(_idx(steps), result)
    assert not result.errors


def test_retry_attempts_out_of_range() -> None:
    result = _result()
    steps = [{"type": "wait", "retry": {"attempts": 99}}]
    check_retry_config(_idx(steps), result)
    assert any(e.code == "RETRY_MAX_ATTEMPTS_OUT_OF_RANGE" for e in result.errors)


def test_no_verification_warning() -> None:
    result = _result()
    steps = [{"type": "tap_selector", "selector": {"by": "text", "value": "ok"}}] * 3
    check_lint_warnings(_idx(steps), scenario_vars={}, account_group_id=None, campaign_vars={}, result=result)
    assert result.status == "valid"
    assert any(w.code == "NO_VERIFICATION_STEP" for w in result.warnings)


def test_no_verification_skipped_by_tag() -> None:
    result = _result()
    steps = [{"type": "tap"}]
    check_lint_warnings(
        _idx(steps),
        scenario_vars={"_validation": {"skip_no_verification": True}},
        account_group_id=None,
        campaign_vars={},
        result=result,
    )
    assert not result.warnings


def test_var_scan_skips_screenshot_field() -> None:
    result = _result()
    steps = [
        {
            "type": "tap",
            "screen": {"screenshot": "${should_not_report}", "package": "com.app"},
        }
    ]
    check_variables(_idx(steps), {}, {}, result)
    assert not result.errors


@pytest.mark.asyncio
async def test_scenario_ref_not_found() -> None:
    result = _result()
    cache = ScenarioRefCache([])
    steps = [{"type": "run_scenario", "scenario_id": "S_missing"}]
    await check_scenario_references("root", steps, ref_cache=cache, result=result)
    assert any(e.code == "SCENARIO_REF_NOT_FOUND" for e in result.errors)


@pytest.mark.asyncio
async def test_circular_scenario_reference() -> None:
    result = _result()
    sub = SimpleNamespace(id="S2", name="sub", steps=[{"type": "run_scenario", "scenario_id": "root"}])
    cache = ScenarioRefCache([sub])
    steps = [{"type": "run_scenario", "scenario_id": "S2"}]
    await check_scenario_references("root", steps, ref_cache=cache, result=result)
    assert any(e.code == "CIRCULAR_SCENARIO_REFERENCE" for e in result.errors)


@pytest.mark.asyncio
async def test_ref_cache_single_db_round_trip() -> None:
    """Validator preloads campaign scenarios in one query (not per run_scenario)."""
    scenario = SimpleNamespace(
        id="sc-perf",
        campaign_id="camp-1",
        name="main",
        instructions="",
        steps=[{"type": "run_scenario", "scenario_id": "sub-1"}],
        nodes=[],
        edges=[],
        variables={},
        account_group_id=None,
    )
    sub = SimpleNamespace(
        id="sub-1",
        campaign_id="camp-1",
        name="sub",
        steps=[{"type": "wait"}],
        variables={},
    )

    scenarios_result = MagicMock()
    scenarios_result.scalars.return_value.all.return_value = [scenario, sub]
    versions_result = MagicMock()
    versions_result.all.return_value = []

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[scenarios_result, versions_result])

    validator = ScenarioValidator(db, scenario=scenario, campaign_variables={})
    await validator.validate()
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_combined_rules_fire_together() -> None:
    result = _result()
    nodes = [
        {"id": "a", "type": "wait", "order": "a0", "config": {}},
        {"id": "z", "type": "wait", "order": "a1", "config": {}},
    ]
    check_graph(nodes, [], result)
    steps = [
        {"id": "s1", "type": "tap_selector", "selector": {"value": "${missing}"}, "on_error": "nope"},
        {"type": "run_scenario", "scenario_id": "ghost"},
    ]
    check_variables(_idx(steps), {}, {}, result)
    check_on_error_targets(_idx(steps), result)
    await check_scenario_references("root", steps, ref_cache=ScenarioRefCache([]), result=result)
    codes = {e.code for e in result.errors}
    assert "GRAPH_UNREACHABLE_NODE" in codes
    assert "UNDECLARED_VARIABLE" in codes
    assert "INVALID_ON_ERROR_TARGET" in codes
    assert "SCENARIO_REF_NOT_FOUND" in codes


@pytest.mark.asyncio
async def test_validate_route_returns_valid(monkeypatch) -> None:
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from api import deps
    from api.routes import campaigns as campaign_routes
    from services.scenario_validation.models import ValidationResult

    app = FastAPI()
    app.include_router(campaign_routes.router)

    user = SimpleNamespace(id="u1", org_id="org-1")
    campaign = SimpleNamespace(id="camp-1", variables={})
    scenario = SimpleNamespace(
        id="sc-1",
        campaign_id="camp-1",
        instructions="",
        steps=[{"id": "s1", "type": "wait", "seconds": 1}],
        nodes=[],
        edges=[],
        variables={},
        account_group_id=None,
        last_validated_at=None,
    )

    async def fake_db():
        yield SimpleNamespace(commit=AsyncMock(), flush=AsyncMock())

    app.dependency_overrides[deps._get_current_user] = lambda: user
    app.dependency_overrides[deps._get_db] = fake_db
    monkeypatch.setattr(campaign_routes, "_get_campaign_or_404", AsyncMock(return_value=campaign))
    monkeypatch.setattr(campaign_routes.repo, "get_scenario", AsyncMock(return_value=scenario))
    monkeypatch.setattr(
        "services.scenario_validation.validator.validate_scenario_body",
        AsyncMock(return_value=ValidationResult(status="valid")),
    )
    monkeypatch.setattr(
        "services.scenario_validation.validator.persist_validation_summary",
        AsyncMock(),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/campaigns/camp-1/scenarios/sc-1/validate")

    assert resp.status_code == 200
    assert resp.json()["status"] == "valid"


@pytest.mark.asyncio
async def test_validate_500_steps_under_500ms() -> None:
    scenario = SimpleNamespace(
        id="sc-perf",
        campaign_id="camp-1",
        name="perf",
        instructions="",
        steps=[{"id": f"s{i}", "type": "wait", "seconds": 0} for i in range(500)],
        nodes=[],
        edges=[],
        variables={},
        account_group_id=None,
    )
    scenarios_result = MagicMock()
    scenarios_result.scalars.return_value.all.return_value = [scenario]
    versions_result = MagicMock()
    versions_result.all.return_value = []
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[scenarios_result, versions_result])

    validator = ScenarioValidator(db, scenario=scenario, campaign_variables={})
    started = time.perf_counter()
    result = await validator.validate()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert elapsed_ms < 500.0, f"validation took {elapsed_ms:.1f}ms"
    assert result.status == "valid"
