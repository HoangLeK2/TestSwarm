from __future__ import annotations

import asyncio
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services.campaign_dispatch import enqueue_campaign_run_temporal
from temporal.shared import ScenarioInput
from tests.perf_assertions import perf_budget


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


def _db_device(device_id: str, serial: str, *, last_seen):
    return SimpleNamespace(id=device_id, serial=serial, last_seen=last_seen)


def _scenario(scenario_id: str, *, has_steps: bool = True):
    return SimpleNamespace(
        id=scenario_id,
        steps=[{"type": "wait", "seconds": 0}] if has_steps else [],
        variables={},
        name=f"scenario-{scenario_id}",
    )


@pytest.mark.asyncio
async def test_runtime_device_vars_bulk_empty_does_not_fallback_to_per_device_queries():
    from services.campaign_dispatch import _build_per_scenario_device_runtime_vars

    db = _make_db_mock()
    scenarios = [_scenario("sc-1")]
    devices = [_device(f"dev-{idx:03d}", f"SN{idx:03d}") for idx in range(1, 501)]
    per_device_lookup = AsyncMock(return_value={})

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "services.campaign_dispatch.get_scenario_device_variables_bulk",
                new_callable=AsyncMock,
                return_value={},
            )
        )
        stack.enter_context(
            patch(
                "services.campaign_dispatch.get_scenario_device_variables",
                per_device_lookup,
            )
        )

        out = await _build_per_scenario_device_runtime_vars(db, scenarios, devices)

    per_device_lookup.assert_not_awaited()
    assert len(out["sc-1"]) == 500
    assert all(vars_ == {} for vars_ in out["sc-1"].values())


@pytest.mark.asyncio
async def test_unbound_scenario_account_vars_use_bulk_primary_account_lookup():
    from services.campaign_dispatch import _build_per_scenario_device_vars

    db = _make_db_mock()
    scenarios = [_scenario("sc-1")]
    devices = [_device(f"dev-{idx:03d}", f"SN{idx:03d}") for idx in range(1, 501)]
    accounts = {
        device.id: SimpleNamespace(
            id=f"acct-{idx:03d}",
            username=f"user-{idx:03d}",
            display_name="",
            platform="facebook",
        )
        for idx, device in enumerate(devices, start=1)
    }
    per_device_lookup = AsyncMock(return_value={})

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "services.campaign_dispatch._get_device_account_vars",
                per_device_lookup,
            )
        )
        stack.enter_context(
            patch(
                "db.crud.account.get_primary_accounts_for_devices",
                new_callable=AsyncMock,
                return_value=accounts,
            )
        )

        out = await _build_per_scenario_device_vars(
            db,
            scenarios,
            devices,
            platform="facebook",
        )

    per_device_lookup.assert_not_awaited()
    assert len(out["sc-1"]) == 500
    assert out["sc-1"]["dev-001"]["__ACCOUNT_ID__"] == "acct-001"
    assert out["sc-1"]["dev-500"]["__ACCOUNT_USERNAME__"] == "user-500"


@pytest.mark.asyncio
async def test_dispatch_single_device_single_scenario_n2n():
    db = _make_db_mock()
    temporal = AsyncMock()
    temporal.start_workflow = AsyncMock()
    execution = SimpleNamespace(id="exec-1", meta={"scenarios_count": 1})

    with ExitStack() as stack:
        stack.enter_context(patch("services.campaign_dispatch.activity_session", return_value=db))
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
        stack.enter_context(patch("db.crud.execution.add_devices_to_execution", new_callable=AsyncMock))
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
async def test_dispatch_skips_all_stale_offline_devices_before_creating_execution():
    db = _make_db_mock()
    temporal = AsyncMock()
    temporal.start_workflow = AsyncMock()
    old_seen = datetime.now(timezone.utc) - timedelta(hours=1)
    create_execution = AsyncMock()

    with ExitStack() as stack:
        stack.enter_context(patch("services.campaign_dispatch.activity_session", return_value=db))
        stack.enter_context(patch("services.campaign_dispatch.repo.get_campaign", return_value=_campaign("camp-offline")))
        stack.enter_context(
            patch(
                "services.campaign_dispatch.repo.list_campaign_devices",
                return_value=[_db_device("dev-1", "SN001", last_seen=old_seen)],
            )
        )
        stack.enter_context(patch("services.device_liveness.relay_has_device", return_value=False))
        stack.enter_context(
            patch("services.device_liveness.db_has_open_session", new_callable=AsyncMock, return_value=False)
        )
        stack.enter_context(patch("db.crud.execution.create_execution", create_execution))

        result, status = await enqueue_campaign_run_temporal("camp-offline", temporal)

    assert status == 400
    assert result["error"] == "No online devices available for campaign dispatch"
    assert result["skipped_offline_device_serials"] == ["SN001"]
    create_execution.assert_not_awaited()
    temporal.start_workflow.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_device_vars_share_namespace_and_override_global_vars():
    db = _make_db_mock()
    temporal = AsyncMock()
    temporal.start_workflow = AsyncMock()
    execution = SimpleNamespace(id="exec-override", meta={"scenarios_count": 1})
    scenario = _scenario("sc-override")
    scenario.variables = {"group_name": "global-group", "save_collection": "global_collection"}

    with ExitStack() as stack:
        stack.enter_context(patch("services.campaign_dispatch.activity_session", return_value=db))
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
                "services.campaign_dispatch.get_scenario_device_variables_bulk",
                new_callable=AsyncMock,
                return_value={("sc-override", "dev-1"): {"group_name": "device-group"}},
            )
        )
        stack.enter_context(patch("db.crud.execution.create_execution", new_callable=AsyncMock, return_value=execution))
        stack.enter_context(patch("db.crud.execution.add_devices_to_execution", new_callable=AsyncMock))
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
async def test_fb_groups_per_device_guard_uses_referenced_device_var_key():
    db = _make_db_mock()
    temporal = AsyncMock()
    temporal.start_workflow = AsyncMock()
    execution = SimpleNamespace(id="exec-profile-text", meta={"scenarios_count": 1})
    devices = [_device("dev-1", "SN001"), _device("dev-2", "SN002")]
    scenario = _scenario("sc-profile-text")
    scenario.name = "fb_groups_per_device"
    scenario.variables = {"profile_text": ""}
    scenario.steps = [
        {"type": "set_variable", "name": "SEARCH_TEXT", "value": "${profile_text}"},
        {"type": "wait", "seconds": 0},
    ]

    with ExitStack() as stack:
        stack.enter_context(patch("services.campaign_dispatch.activity_session", return_value=db))
        stack.enter_context(patch("services.campaign_dispatch.repo.get_campaign", return_value=_campaign("camp-profile-text")))
        stack.enter_context(patch("services.campaign_dispatch.repo.list_campaign_devices", return_value=devices))
        stack.enter_context(
            patch("services.campaign_dispatch.repo.list_scenarios", return_value=[scenario])
        )
        stack.enter_context(patch("services.campaign_dispatch.repo.update_campaign_status", new_callable=AsyncMock))
        stack.enter_context(patch("db.crud.scenario_template.list_templates", new_callable=AsyncMock, return_value=[]))
        stack.enter_context(patch("services.campaign_dispatch._get_device_account_vars", new_callable=AsyncMock, return_value={}))
        stack.enter_context(
            patch(
                "services.campaign_dispatch.get_scenario_device_variables_bulk",
                new_callable=AsyncMock,
                return_value={
                    ("sc-profile-text", "dev-1"): {"profile_text": "Group A"},
                    ("sc-profile-text", "dev-2"): {"profile_text": "Group B"},
                },
            )
        )
        stack.enter_context(patch("db.crud.execution.create_execution", new_callable=AsyncMock, return_value=execution))
        stack.enter_context(patch("db.crud.execution.add_devices_to_execution", new_callable=AsyncMock))
        stack.enter_context(patch("db.crud.execution.update_execution", new_callable=AsyncMock))

        result, status = await enqueue_campaign_run_temporal("camp-profile-text", temporal)

    assert status == 200
    assert len(result["workflow_ids"]) == 2
    started_inputs = [call.args[1] for call in temporal.start_workflow.await_args_list]
    values = {
        inp.device_serial: inp.steps[0]["variables"]["profile_text"]
        for inp in started_inputs
    }
    assert values == {"SN001": "Group A", "SN002": "Group B"}


@pytest.mark.asyncio
async def test_dispatch_multi_device_multi_scenario_starts_one_sequence_per_device():
    db = _make_db_mock()
    temporal = AsyncMock()
    temporal.start_workflow = AsyncMock()
    execution = SimpleNamespace(id="exec-2", meta={"scenarios_count": 2})
    devices = [_device("dev-1", "SN001"), _device("dev-2", "SN002")]
    scenarios = [_scenario("sc-1"), _scenario("sc-2")]

    with ExitStack() as stack:
        stack.enter_context(patch("services.campaign_dispatch.activity_session", return_value=db))
        stack.enter_context(patch("services.campaign_dispatch.repo.get_campaign", return_value=_campaign("camp-2")))
        stack.enter_context(patch("services.campaign_dispatch.repo.list_campaign_devices", return_value=devices))
        stack.enter_context(patch("services.campaign_dispatch.repo.list_scenarios", return_value=scenarios))
        stack.enter_context(patch("services.campaign_dispatch.repo.update_campaign_status", new_callable=AsyncMock))
        stack.enter_context(patch("db.crud.scenario_template.list_templates", new_callable=AsyncMock, return_value=[]))
        stack.enter_context(patch("services.campaign_dispatch._get_device_account_vars", new_callable=AsyncMock, return_value={}))
        stack.enter_context(patch("db.crud.execution.create_execution", new_callable=AsyncMock, return_value=execution))
        stack.enter_context(patch("db.crud.execution.add_devices_to_execution", new_callable=AsyncMock))
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


@pytest.mark.parametrize(
    ("device_count", "budget_ms"),
    [
        (20, 250.0),
        (100, 700.0),
        (500, 1_400.0),
    ],
)
@pytest.mark.asyncio
async def test_dispatch_large_device_counts_start_workflows_within_latency_budget(
    device_count: int,
    budget_ms: float,
):
    db = _make_db_mock()
    execution = SimpleNamespace(id=f"exec-{device_count}", meta={"scenarios_count": 1})
    devices = [
        _device(f"dev-{idx:03d}", f"SN{idx:03d}")
        for idx in range(1, device_count + 1)
    ]

    active_workflows = 0
    max_active_workflows = 0
    active_account_starts = 0
    max_active_account_starts = 0

    async def _start_workflow(_wf, _inp: ScenarioInput, **_kwargs):
        nonlocal active_workflows, max_active_workflows
        active_workflows += 1
        max_active_workflows = max(max_active_workflows, active_workflows)
        try:
            await asyncio.sleep(0.03)
        finally:
            active_workflows -= 1

    async def _add_device_to_execution(_db, _execution_id: str, _device_id: str):
        await asyncio.sleep(0.03)

    async def _add_devices_to_execution(_db, _execution_id: str, _device_ids: list[str]):
        await asyncio.sleep(0.03)

    async def _start_account_usage(_account_id: str, **_kwargs):
        nonlocal active_account_starts, max_active_account_starts
        active_account_starts += 1
        max_active_account_starts = max(max_active_account_starts, active_account_starts)
        try:
            await asyncio.sleep(0.03)
        finally:
            active_account_starts -= 1

    account_vars = {
        "sc-1": {
            device.id: {
                "__ACCOUNT_ID__": f"acct-{idx:02d}",
                "__ACCOUNT_PLATFORM__": "facebook",
            }
            for idx, device in enumerate(devices, start=1)
        }
    }

    temporal = SimpleNamespace(start_workflow=AsyncMock(side_effect=_start_workflow))
    add_device_to_execution = AsyncMock(side_effect=_add_device_to_execution)
    add_devices_to_execution = AsyncMock(side_effect=_add_devices_to_execution)
    start_account_usage = AsyncMock(side_effect=_start_account_usage)

    with ExitStack() as stack:
        stack.enter_context(patch("services.campaign_dispatch.activity_session", return_value=db))
        stack.enter_context(patch("services.campaign_dispatch.repo.get_campaign", return_value=_campaign(f"camp-{device_count}")))
        stack.enter_context(patch("services.campaign_dispatch.repo.list_campaign_devices", return_value=devices))
        stack.enter_context(
            patch("services.campaign_dispatch.repo.list_scenarios", return_value=[_scenario("sc-1")])
        )
        stack.enter_context(patch("services.campaign_dispatch.repo.update_campaign_status", new_callable=AsyncMock))
        stack.enter_context(patch("db.crud.scenario_template.list_templates", new_callable=AsyncMock, return_value=[]))
        stack.enter_context(
            patch(
                "services.campaign_dispatch._build_per_scenario_device_vars",
                new_callable=AsyncMock,
                return_value=account_vars,
            )
        )
        stack.enter_context(
            patch(
                "services.campaign_dispatch._build_per_scenario_device_runtime_vars",
                new_callable=AsyncMock,
                return_value={},
            )
        )
        stack.enter_context(patch("services.account_manager.start_account_usage", start_account_usage))
        stack.enter_context(patch("db.crud.execution.create_execution", new_callable=AsyncMock, return_value=execution))
        stack.enter_context(patch("db.crud.execution.add_device_to_execution", add_device_to_execution))
        stack.enter_context(patch("db.crud.execution.add_devices_to_execution", add_devices_to_execution))
        stack.enter_context(patch("db.crud.execution.update_execution", new_callable=AsyncMock))

        started_at = time.perf_counter()
        result, status = await enqueue_campaign_run_temporal(f"camp-{device_count}", temporal)
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0

    budget_ms = perf_budget(
        f"CAMPAIGN_DISPATCH_{device_count}_DEVICE_START_BUDGET_MS",
        budget_ms,
    )
    assert status == 200
    assert len(result["workflow_ids"]) == device_count
    assert temporal.start_workflow.await_count == device_count
    add_device_to_execution.assert_not_awaited()
    add_devices_to_execution.assert_awaited_once()
    assert add_devices_to_execution.await_args.args[2] == [d.id for d in devices]
    assert start_account_usage.await_count == device_count
    assert 1 < max_active_workflows <= 100
    assert 1 < max_active_account_starts <= 100
    assert elapsed_ms <= budget_ms, (
        f"{device_count}-device scenario dispatch took {elapsed_ms:.2f}ms, "
        f"above budget {budget_ms:.2f}ms"
    )


@pytest.mark.asyncio
async def test_dispatch_serial_override_uses_bulk_device_lookup_for_large_lists():
    db = _make_db_mock()
    temporal = SimpleNamespace(start_workflow=AsyncMock())
    execution = SimpleNamespace(id="exec-override-500", meta={"scenarios_count": 1})
    devices = [_device(f"dev-{idx:03d}", f"SN{idx:03d}") for idx in range(1, 501)]
    serials = [d.serial for d in devices]
    single_lookup = AsyncMock()
    bulk_lookup = AsyncMock(return_value=devices)

    with ExitStack() as stack:
        stack.enter_context(patch("services.campaign_dispatch.activity_session", return_value=db))
        stack.enter_context(patch("services.campaign_dispatch.repo.get_campaign", return_value=_campaign("camp-override-500")))
        stack.enter_context(
            patch("db.crud.device.list_devices_by_serial_aliases", bulk_lookup)
        )
        stack.enter_context(patch("db.crud.device.get_device_by_serial", single_lookup))
        stack.enter_context(
            patch("services.campaign_dispatch.repo.list_scenarios", return_value=[_scenario("sc-1")])
        )
        stack.enter_context(patch("services.campaign_dispatch.repo.update_campaign_status", new_callable=AsyncMock))
        stack.enter_context(patch("db.crud.scenario_template.list_templates", new_callable=AsyncMock, return_value=[]))
        stack.enter_context(patch("services.campaign_dispatch._get_device_account_vars", new_callable=AsyncMock, return_value={}))
        stack.enter_context(
            patch(
                "services.campaign_dispatch.get_scenario_device_variables_bulk",
                new_callable=AsyncMock,
                return_value={},
            )
        )
        stack.enter_context(patch("db.crud.execution.create_execution", new_callable=AsyncMock, return_value=execution))
        stack.enter_context(patch("db.crud.execution.add_devices_to_execution", new_callable=AsyncMock))
        stack.enter_context(patch("db.crud.execution.update_execution", new_callable=AsyncMock))

        result, status = await enqueue_campaign_run_temporal(
            "camp-override-500",
            temporal,
            device_serials_override=serials,
        )

    assert status == 200
    assert len(result["workflow_ids"]) == 500
    bulk_lookup.assert_awaited_once_with(db, serials)
    single_lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_skips_empty_scenarios_and_starts_only_valid_steps():
    db = _make_db_mock()
    temporal = AsyncMock()
    temporal.start_workflow = AsyncMock()
    execution = SimpleNamespace(id="exec-3", meta={"scenarios_count": 2})

    with ExitStack() as stack:
        stack.enter_context(patch("services.campaign_dispatch.activity_session", return_value=db))
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
        stack.enter_context(patch("db.crud.execution.add_devices_to_execution", new_callable=AsyncMock))
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
        stack.enter_context(patch("services.campaign_dispatch.activity_session", return_value=db))
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
        stack.enter_context(patch("db.crud.execution.add_devices_to_execution", new_callable=AsyncMock))
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
        stack.enter_context(patch("services.campaign_dispatch.activity_session", return_value=db))
        stack.enter_context(patch("services.campaign_dispatch.repo.get_campaign", return_value=_campaign("camp-4")))
        stack.enter_context(patch("services.campaign_dispatch.repo.list_campaign_devices", return_value=devices))
        stack.enter_context(
            patch("services.campaign_dispatch.repo.list_scenarios", return_value=[_scenario("sc-1")])
        )
        stack.enter_context(patch("services.campaign_dispatch.repo.update_campaign_status", new_callable=AsyncMock))
        stack.enter_context(patch("db.crud.scenario_template.list_templates", new_callable=AsyncMock, return_value=[]))
        stack.enter_context(patch("services.campaign_dispatch._get_device_account_vars", new_callable=AsyncMock, return_value={}))
        stack.enter_context(patch("db.crud.execution.create_execution", new_callable=AsyncMock, return_value=execution))
        stack.enter_context(patch("db.crud.execution.add_devices_to_execution", new_callable=AsyncMock))
        stack.enter_context(patch("db.crud.execution.update_execution", new_callable=AsyncMock))

        result, status = await enqueue_campaign_run_temporal("camp-4", temporal)

    assert status == 200
    assert len(result["workflow_ids"]) == 1
    assert "device:SN001" in result["workflow_ids"][0]
