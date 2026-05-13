from __future__ import annotations

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services.campaign_dispatch import enqueue_campaign_run_temporal
from temporal.shared import ScenarioInput


def _make_db_mock():
    db = AsyncMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=False)
    return db


def _campaign(campaign_id: str, *, user_id: str = "user-1"):
    return SimpleNamespace(
        id=campaign_id,
        user_id=user_id,
        variables={"__PLATFORM__": "facebook"},
        target_group_id=None,
    )


def _device(device_id: str, serial: str):
    return SimpleNamespace(id=device_id, serial=serial)


def _scenario(scenario_id: str, *, has_steps: bool = True):
    return SimpleNamespace(
        id=scenario_id,
        steps=[{"type": "wait", "seconds": 0}] if has_steps else [],
        variables={},
        name=f"scenario-{scenario_id}",
    )


@pytest.mark.asyncio
async def test_dispatch_single_device_single_scenario_n2n():
    db = _make_db_mock()
    temporal = AsyncMock()
    temporal.start_workflow = AsyncMock()
    execution = SimpleNamespace(id="exec-1", meta={"scenarios_count": 1})

    with ExitStack() as stack:
        stack.enter_context(patch("services.campaign_dispatch.AsyncSessionLocal", return_value=db))
        stack.enter_context(patch("services.campaign_dispatch.repo.get_campaign", return_value=_campaign("camp-1")))
        stack.enter_context(
            patch("services.campaign_dispatch.repo.list_campaign_devices", return_value=[_device("dev-1", "SN001")])
        )
        stack.enter_context(
            patch("services.campaign_dispatch.repo.list_scenarios", return_value=[_scenario("sc-1")])
        )
        stack.enter_context(patch("services.campaign_dispatch.repo.update_campaign_status", new_callable=AsyncMock))
        stack.enter_context(patch("db.crud.scenario_template.list_templates", new_callable=AsyncMock, return_value=[]))
        stack.enter_context(patch("services.campaign_dispatch._get_device_account_vars", new_callable=AsyncMock, return_value={}))
        stack.enter_context(patch("db.crud.execution.create_execution", new_callable=AsyncMock, return_value=execution))
        stack.enter_context(patch("db.crud.execution.add_device_to_execution", new_callable=AsyncMock))
        stack.enter_context(patch("db.crud.execution.update_execution", new_callable=AsyncMock))

        result, status = await enqueue_campaign_run_temporal("camp-1", temporal)

    assert status == 200
    assert result["execution_id"] == "exec-1"
    assert result["device_serials"] == ["SN001"]
    temporal.start_workflow.assert_awaited_once()
    started_input: ScenarioInput = temporal.start_workflow.await_args.args[1]
    assert started_input.device_serial == "SN001"
    assert started_input.execution_id == "exec-1"
    assert started_input.campaign_vars["__USER_ID__"] == "user-1"


@pytest.mark.asyncio
async def test_dispatch_device_vars_share_namespace_and_override_global_vars():
    db = _make_db_mock()
    temporal = AsyncMock()
    temporal.start_workflow = AsyncMock()
    execution = SimpleNamespace(id="exec-override", meta={"scenarios_count": 1})
    scenario = _scenario("sc-override")
    scenario.variables = {"group_name": "global-group", "save_collection": "global_collection"}

    with ExitStack() as stack:
        stack.enter_context(patch("services.campaign_dispatch.AsyncSessionLocal", return_value=db))
        stack.enter_context(patch("services.campaign_dispatch.repo.get_campaign", return_value=_campaign("camp-override")))
        stack.enter_context(
            patch("services.campaign_dispatch.repo.list_campaign_devices", return_value=[_device("dev-1", "SN001")])
        )
        stack.enter_context(
            patch("services.campaign_dispatch.repo.list_scenarios", return_value=[scenario])
        )
        stack.enter_context(patch("services.campaign_dispatch.repo.update_campaign_status", new_callable=AsyncMock))
        stack.enter_context(patch("db.crud.scenario_template.list_templates", new_callable=AsyncMock, return_value=[]))
        stack.enter_context(patch("services.campaign_dispatch._get_device_account_vars", new_callable=AsyncMock, return_value={}))
        stack.enter_context(
            patch(
                "services.campaign_dispatch.get_scenario_device_variables",
                new_callable=AsyncMock,
                return_value={"group_name": "device-group"},
            )
        )
        stack.enter_context(patch("db.crud.execution.create_execution", new_callable=AsyncMock, return_value=execution))
        stack.enter_context(patch("db.crud.execution.add_device_to_execution", new_callable=AsyncMock))
        stack.enter_context(patch("db.crud.execution.update_execution", new_callable=AsyncMock))

        _, status = await enqueue_campaign_run_temporal("camp-override", temporal)

    assert status == 200
    started_input: ScenarioInput = temporal.start_workflow.await_args.args[1]
    step_vars = started_input.steps[0]["variables"]
    registry_vars = started_input.scenario_registry["by_id"]["sc-override"]["variables"]
    assert step_vars["group_name"] == "device-group"
    assert registry_vars["save_collection"] == "global_collection"
    assert "__DEVICE_GROUP_NAME__" not in step_vars


@pytest.mark.asyncio
async def test_dispatch_multi_device_multi_scenario_starts_one_sequence_per_device():
    db = _make_db_mock()
    temporal = AsyncMock()
    temporal.start_workflow = AsyncMock()
    execution = SimpleNamespace(id="exec-2", meta={"scenarios_count": 2})
    devices = [_device("dev-1", "SN001"), _device("dev-2", "SN002")]
    scenarios = [_scenario("sc-1"), _scenario("sc-2")]

    with ExitStack() as stack:
        stack.enter_context(patch("services.campaign_dispatch.AsyncSessionLocal", return_value=db))
        stack.enter_context(patch("services.campaign_dispatch.repo.get_campaign", return_value=_campaign("camp-2")))
        stack.enter_context(patch("services.campaign_dispatch.repo.list_campaign_devices", return_value=devices))
        stack.enter_context(patch("services.campaign_dispatch.repo.list_scenarios", return_value=scenarios))
        stack.enter_context(patch("services.campaign_dispatch.repo.update_campaign_status", new_callable=AsyncMock))
        stack.enter_context(patch("db.crud.scenario_template.list_templates", new_callable=AsyncMock, return_value=[]))
        stack.enter_context(patch("services.campaign_dispatch._get_device_account_vars", new_callable=AsyncMock, return_value={}))
        stack.enter_context(patch("db.crud.execution.create_execution", new_callable=AsyncMock, return_value=execution))
        stack.enter_context(patch("db.crud.execution.add_device_to_execution", new_callable=AsyncMock))
        stack.enter_context(patch("db.crud.execution.update_execution", new_callable=AsyncMock))

        result, status = await enqueue_campaign_run_temporal("camp-2", temporal)

    assert status == 200
    assert len(result["workflow_ids"]) == 2
    assert temporal.start_workflow.await_count == 2
    assert sorted(result["device_serials"]) == ["SN001", "SN002"]
    started_inputs = [call.args[1] for call in temporal.start_workflow.await_args_list]
    assert all(len(inp.steps) == 2 for inp in started_inputs)
    assert all(step["type"] == "run_scenario" for inp in started_inputs for step in inp.steps)
    assert all(wf_id.endswith(":scenario:__sequence__") for wf_id in result["workflow_ids"])


@pytest.mark.asyncio
async def test_dispatch_skips_empty_scenarios_and_starts_only_valid_steps():
    db = _make_db_mock()
    temporal = AsyncMock()
    temporal.start_workflow = AsyncMock()
    execution = SimpleNamespace(id="exec-3", meta={"scenarios_count": 2})

    with ExitStack() as stack:
        stack.enter_context(patch("services.campaign_dispatch.AsyncSessionLocal", return_value=db))
        stack.enter_context(patch("services.campaign_dispatch.repo.get_campaign", return_value=_campaign("camp-3")))
        stack.enter_context(
            patch("services.campaign_dispatch.repo.list_campaign_devices", return_value=[_device("dev-1", "SN001")])
        )
        stack.enter_context(
            patch(
                "services.campaign_dispatch.repo.list_scenarios",
                return_value=[_scenario("sc-valid"), _scenario("sc-empty", has_steps=False)],
            )
        )
        stack.enter_context(patch("services.campaign_dispatch.repo.update_campaign_status", new_callable=AsyncMock))
        stack.enter_context(patch("db.crud.scenario_template.list_templates", new_callable=AsyncMock, return_value=[]))
        stack.enter_context(patch("services.campaign_dispatch._get_device_account_vars", new_callable=AsyncMock, return_value={}))
        stack.enter_context(patch("db.crud.execution.create_execution", new_callable=AsyncMock, return_value=execution))
        stack.enter_context(patch("db.crud.execution.add_device_to_execution", new_callable=AsyncMock))
        stack.enter_context(patch("db.crud.execution.update_execution", new_callable=AsyncMock))

        result, status = await enqueue_campaign_run_temporal("camp-3", temporal)

    assert status == 200
    assert temporal.start_workflow.await_count == 1
    assert len(result["workflow_ids"]) == 1
    assert result["workflow_ids"][0].endswith(":scenario:__sequence__")
    started_input: ScenarioInput = temporal.start_workflow.await_args.args[1]
    assert [step["scenario_id"] for step in started_input.steps] == ["sc-valid"]


@pytest.mark.asyncio
async def test_same_device_can_be_dispatched_in_two_campaigns_with_distinct_workflow_ids():
    db = _make_db_mock()
    temporal = AsyncMock()
    temporal.start_workflow = AsyncMock()

    campaigns = [_campaign("camp-A"), _campaign("camp-B")]
    executions = [
        SimpleNamespace(id="exec-A", meta={"scenarios_count": 1}),
        SimpleNamespace(id="exec-B", meta={"scenarios_count": 1}),
    ]

    with ExitStack() as stack:
        stack.enter_context(patch("services.campaign_dispatch.AsyncSessionLocal", return_value=db))
        stack.enter_context(patch("services.campaign_dispatch.repo.get_campaign", side_effect=campaigns))
        stack.enter_context(
            patch("services.campaign_dispatch.repo.list_campaign_devices", return_value=[_device("dev-1", "SN001")])
        )
        stack.enter_context(
            patch("services.campaign_dispatch.repo.list_scenarios", return_value=[_scenario("sc-1")])
        )
        stack.enter_context(patch("services.campaign_dispatch.repo.update_campaign_status", new_callable=AsyncMock))
        stack.enter_context(patch("db.crud.scenario_template.list_templates", new_callable=AsyncMock, return_value=[]))
        stack.enter_context(patch("services.campaign_dispatch._get_device_account_vars", new_callable=AsyncMock, return_value={}))
        stack.enter_context(patch("db.crud.execution.create_execution", new_callable=AsyncMock, side_effect=executions))
        stack.enter_context(patch("db.crud.execution.add_device_to_execution", new_callable=AsyncMock))
        stack.enter_context(patch("db.crud.execution.update_execution", new_callable=AsyncMock))

        result_a, status_a = await enqueue_campaign_run_temporal("camp-A", temporal)
        result_b, status_b = await enqueue_campaign_run_temporal("camp-B", temporal)

    assert status_a == 200 and status_b == 200
    assert result_a["workflow_ids"][0] != result_b["workflow_ids"][0]
    assert "campaign:camp-A" in result_a["workflow_ids"][0]
    assert "campaign:camp-B" in result_b["workflow_ids"][0]


@pytest.mark.asyncio
async def test_partial_start_failure_still_returns_running_when_at_least_one_started():
    db = _make_db_mock()
    execution = SimpleNamespace(id="exec-4", meta={"scenarios_count": 1})
    devices = [_device("dev-1", "SN001"), _device("dev-2", "SN002")]

    async def _start_workflow(_wf, inp: ScenarioInput, **_kwargs):
        if inp.device_serial == "SN002":
            raise RuntimeError("temporal unavailable for device")
        return None

    temporal = AsyncMock()
    temporal.start_workflow = _start_workflow

    with ExitStack() as stack:
        stack.enter_context(patch("services.campaign_dispatch.AsyncSessionLocal", return_value=db))
        stack.enter_context(patch("services.campaign_dispatch.repo.get_campaign", return_value=_campaign("camp-4")))
        stack.enter_context(patch("services.campaign_dispatch.repo.list_campaign_devices", return_value=devices))
        stack.enter_context(
            patch("services.campaign_dispatch.repo.list_scenarios", return_value=[_scenario("sc-1")])
        )
        stack.enter_context(patch("services.campaign_dispatch.repo.update_campaign_status", new_callable=AsyncMock))
        stack.enter_context(patch("db.crud.scenario_template.list_templates", new_callable=AsyncMock, return_value=[]))
        stack.enter_context(patch("services.campaign_dispatch._get_device_account_vars", new_callable=AsyncMock, return_value={}))
        stack.enter_context(patch("db.crud.execution.create_execution", new_callable=AsyncMock, return_value=execution))
        stack.enter_context(patch("db.crud.execution.add_device_to_execution", new_callable=AsyncMock))
        stack.enter_context(patch("db.crud.execution.update_execution", new_callable=AsyncMock))

        result, status = await enqueue_campaign_run_temporal("camp-4", temporal)

    assert status == 200
    assert len(result["workflow_ids"]) == 1
    assert "device:SN001" in result["workflow_ids"][0]
