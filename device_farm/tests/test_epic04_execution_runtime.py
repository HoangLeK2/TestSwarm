"""Epic 04 DF-T-04-010: execution runtime (Temporal + fallback)."""
from __future__ import annotations

import asyncio
import time

import pytest

pytest_plugins = ["tests.test_epic04_scenario_entity"]

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.campaign.dispatcher import FanOutExecutionView, FanOutResult
from services.campaign_dispatch import _build_device_sequence_steps
from services.campaign.execution_runtime import (
    DISPATCH_SOURCE_FALLBACK,
    DISPATCH_SOURCE_TEMPORAL,
    _scenario_refs_with_recovery_refs,
    build_runtime_scenario_dict,
    build_sequence_steps,
    prepare_scenario_input,
    start_execution_runtime,
    workflow_id_for_execution,
)
from tests.perf_assertions import perf_budget


def test_workflow_id_for_execution():
    assert workflow_id_for_execution("abc-123") == "exec_abc-123"


def test_build_runtime_scenario_dict_includes_execution_capture_context():
    from temporal.shared import ScenarioInput

    inp = ScenarioInput(
        campaign_id="",
        device_serial="SN1",
        steps=[{"type": "extract", "strategy": "fb_posts"}],
        variables={"kw": "x"},
        campaign_vars={"__USER_ID__": "u1", "__ORG_ID__": "org1"},
        capture_steps=True,
        scenario_config={
            "capture_steps": True,
            "preview_collection": "preview_org1",
            "recovery_policy": {
                "enabled": True,
                "rules": [
                    {
                        "incident_type": "facebook_popup",
                        "scenario_id": "recovery-1",
                    }
                ],
            },
        },
        execution_id="exec-99",
        run_id="exec-99",
    )
    scenario = build_runtime_scenario_dict(
        inp,
        "exec-99",
        org_id="org1",
        scenario_name="FB Group Crawl",
    )
    assert scenario["execution_id"] == "exec-99"
    assert scenario["_execution_id"] == "exec-99"
    assert scenario["_run_hash_scope"] == "exec-99"
    assert scenario["capture_steps"] is True
    assert scenario["_campaign_vars"]["__ORG_ID__"] == "org1"
    assert scenario["preview_collection"] == "preview_org1"
    assert scenario["recovery_policy"]["enabled"] is True
    assert scenario["recovery_policy"]["rules"][0]["scenario_id"] == "recovery-1"
    assert scenario["scenario_name"] == "FB Group Crawl"


def test_build_sequence_steps_run_scenario_chain():
    refs = [{"scenario_id": "s1"}, {"scenario_id": "s2"}]
    steps = build_sequence_steps(
        refs,
        device_index=1,
        effective_vars={"kw": "x"},
        account_vars={"__ACCOUNT_ID__": "a1"},
    )
    assert len(steps) == 2
    assert steps[0]["type"] == "run_scenario"
    assert steps[0]["scenario_id"] == "s1"
    assert steps[0]["variables"]["DEVICE_INDEX"] == "1"
    assert steps[0]["variables"]["__ACCOUNT_ID__"] == "a1"


def test_build_sequence_steps_keeps_device_vars_scoped_per_scenario():
    refs = [{"scenario_id": "s1"}, {"scenario_id": "s2"}]
    steps = build_sequence_steps(
        refs,
        device_index=0,
        effective_vars={"shared": "campaign"},
        account_vars={},
        scenario_device_vars={
            "s1": {"kw": "scenario-one"},
            "s2": {"kw": "scenario-two"},
        },
    )

    assert steps[0]["variables"]["shared"] == "campaign"
    assert steps[0]["variables"]["kw"] == "scenario-one"
    assert steps[1]["variables"]["shared"] == "campaign"
    assert steps[1]["variables"]["kw"] == "scenario-two"


def test_build_sequence_steps_promotes_campaign_vars_as_campaign_scoped_overrides():
    refs = [{"scenario_id": "s1"}]
    steps = build_sequence_steps(
        refs,
        device_index=0,
        campaign_vars={
            "GROUP_NAME": "openclaw vn",
            "GROUP_TEXT": "OpenClaw VN",
            "SAVE_COLLECTION": "fb_group_posts",
        },
        effective_vars={
            "GROUP_NAME": "openclaw vn",
            "GROUP_TEXT": "OpenClaw VN",
            "SAVE_COLLECTION": "custom_collection",
            "DEVICE_ONLY": "device-value",
        },
        account_vars={"__ACCOUNT_ID__": "acct-1"},
        scenario_device_vars={"s1": {"GROUP_TEXT": "device text"}},
    )

    step_vars = steps[0]["variables"]
    assert step_vars["GROUP_NAME"] == "openclaw vn"
    assert step_vars["GROUP_TEXT"] == "device text"
    assert step_vars["SAVE_COLLECTION"] == "custom_collection"
    assert step_vars["DEVICE_ONLY"] == "device-value"
    assert step_vars["__ACCOUNT_ID__"] == "acct-1"


def test_build_sequence_steps_campaign_vars_override_scenario_defaults_without_leaking_system_vars():
    steps = build_sequence_steps(
        [{"scenario_id": "s1"}],
        device_index=0,
        campaign_vars={"COMMENT_TEXT": "campaign text", "__USER_ID__": "user-1"},
        effective_vars={"COMMENT_TEXT": "campaign text"},
        account_vars={},
    )

    assert steps[0]["variables"]["COMMENT_TEXT"] == "campaign text"
    assert "__USER_ID__" not in steps[0]["variables"]


def test_legacy_device_sequence_steps_promotes_campaign_vars_without_leaking_system_vars():
    steps = _build_device_sequence_steps(
        scenarios=[
            SimpleNamespace(
                id="s1",
                name="Scenario 1",
                steps=[{"type": "noop"}],
            )
        ],
        device=SimpleNamespace(id="d1"),
        slot_idx=0,
        campaign_vars={"COMMENT_TEXT": "campaign text", "__USER_ID__": "user-1"},
        per_scenario_device_vars={},
        per_scenario_device_runtime_vars={},
    )

    assert steps[0]["variables"]["COMMENT_TEXT"] == "campaign text"
    assert "__USER_ID__" not in steps[0]["variables"]


def test_recovery_refs_extend_registry_refs_without_sequence_refs():
    main_refs = [{"scenario_id": "main-1"}]
    registry_refs = _scenario_refs_with_recovery_refs(
        main_refs,
        {
            "enabled": True,
            "rules": [
                {"scenario_id": "recovery-1"},
                {"scenario_id": "main-1"},
                {"scenario_id": ""},
            ],
        },
    )

    assert main_refs == [{"scenario_id": "main-1"}]
    assert registry_refs == [
        {"scenario_id": "main-1"},
        {"scenario_id": "recovery-1"},
    ]


@pytest.mark.asyncio
async def test_prepare_scenario_input_defaults_campaign_capture_to_error_only(session_factory):
    await _seed_orgs(session_factory)
    campaign_id, execution_id = await _seed_campaign_execution(session_factory)

    async with session_factory() as db:
        campaign = await _load_campaign(db, campaign_id)
        execution = await _load_execution(db, execution_id)
        scenario_input = await prepare_scenario_input(
            db,
            execution=execution,
            campaign=campaign,
            org_id=campaign.org_id,
            device_serial="SN1",
            effective_vars={},
            account_vars={},
        )

    assert scenario_input is not None
    assert scenario_input.scenario_config["capture_mode"] == "error_only"


@pytest.mark.asyncio
async def test_prepare_scenario_input_loads_org_scenario_device_vars_per_step(session_factory):
    await _seed_orgs(session_factory)
    campaign_id, execution_id = await _seed_campaign_execution(session_factory)

    from db.models.org_scenario import CampaignOrgScenarioRef, OrgScenario
    from db.models.scenario_device_variable import CampaignOrgScenarioDeviceVariable

    async with session_factory() as db:
        db.add(
            OrgScenario(
                id="sc-2",
                org_id="org-runtime",
                name="WaitTwo",
                name_lower="waittwo",
                body_json={
                    "steps": [{"id": "w2", "type": "input_wait.wait", "config": {"seconds": 1}}]
                },
            )
        )
        db.add(
            CampaignOrgScenarioRef(
                id="ref-2",
                campaign_id=campaign_id,
                org_scenario_id="sc-2",
                order_index=1,
                pinned_version=1,
            )
        )
        db.add(
            CampaignOrgScenarioDeviceVariable(
                campaign_id=campaign_id,
                org_scenario_id="sc-1",
                device_id="dev-1",
                vars={"kw": "s1-device"},
            )
        )
        db.add(
            CampaignOrgScenarioDeviceVariable(
                campaign_id=campaign_id,
                org_scenario_id="sc-2",
                device_id="dev-1",
                vars={"kw": "s2-device"},
            )
        )
        await db.commit()

    async with session_factory() as db:
        campaign = await _load_campaign(db, campaign_id)
        execution = await _load_execution(db, execution_id)
        scenario_input = await prepare_scenario_input(
            db,
            execution=execution,
            campaign=campaign,
            org_id=campaign.org_id,
            device_serial="SN1",
            effective_vars={"kw": "campaign"},
            account_vars={},
            device_id="dev-1",
        )

    assert scenario_input is not None
    assert [step["scenario_id"] for step in scenario_input.steps] == ["sc-1", "sc-2"]
    assert scenario_input.steps[0]["variables"]["kw"] == "s1-device"
    assert scenario_input.steps[1]["variables"]["kw"] == "s2-device"


@pytest.mark.asyncio
async def test_start_runtime_uses_temporal_when_available(session_factory):
    await _seed_orgs(session_factory)
    campaign_id, execution_id = await _seed_campaign_execution(session_factory)

    fan_out = FanOutResult(
        dispatch_id="d1",
        campaign_id=campaign_id,
        dispatch_strategy="parallel",
        executions=[
            FanOutExecutionView(
                execution_id=execution_id,
                device_id="dev-1",
                status="running",
                effective_vars={"kw": "v"},
            )
        ],
    )

    temporal_client = SimpleNamespace(start_workflow=AsyncMock())
    temporal_config = SimpleNamespace(enabled=True, task_queue="device-scenario")

    from tenancy.context import set_current_org_id

    set_current_org_id("org-runtime")
    async with session_factory() as db:
        campaign = await _load_campaign(db, campaign_id)
        stats = await start_execution_runtime(
            db,
            fan_out=fan_out,
            campaign=campaign,
            org_id=campaign.org_id,
            actor_user_id="user-owner",
            temporal_client=temporal_client,
            temporal_config=temporal_config,
            manager=None,
        )
        execution = await _load_execution(db, execution_id)

    assert stats["temporal"] == 1
    assert stats["fallback"] == 0
    temporal_client.start_workflow.assert_awaited_once()
    assert execution.meta.get("dispatch_source") == DISPATCH_SOURCE_TEMPORAL
    assert execution.meta.get("workflow_id") == workflow_id_for_execution(execution.id)


@pytest.mark.asyncio
async def test_http_runtime_mode_releases_db_transaction_before_temporal_rpc(session_factory):
    await _seed_orgs(session_factory)
    campaign_id, execution_id = await _seed_campaign_execution(session_factory)
    fan_out = FanOutResult(
        dispatch_id="d-transaction-boundary",
        campaign_id=campaign_id,
        dispatch_strategy="parallel",
        executions=[
            FanOutExecutionView(
                execution_id=execution_id,
                device_id="dev-1",
                status="running",
                effective_vars={},
            )
        ],
    )
    transaction_states: list[bool] = []

    async with session_factory() as db:
        campaign = await _load_campaign(db, campaign_id)

        async def _start_workflow(*_args, **_kwargs):
            transaction_states.append(db.in_transaction())

        temporal_client = SimpleNamespace(start_workflow=_start_workflow)
        await start_execution_runtime(
            db,
            fan_out=fan_out,
            campaign=campaign,
            org_id=campaign.org_id,
            actor_user_id="user-owner",
            temporal_client=temporal_client,
            temporal_config=SimpleNamespace(enabled=True, task_queue="device-scenario"),
            manager=None,
            commit_before_start=True,
        )

    assert transaction_states == [False]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("device_count", "budget_ms"),
    [
        (20, 120.0),
        (100, 250.0),
        (500, 800.0),
    ],
)
async def test_start_runtime_large_fanout_starts_temporal_with_bounded_concurrency(
    device_count: int,
    budget_ms: float,
):
    bulk_execution_load_delay_s = 0.010
    bulk_device_serial_load_delay_s = 0.005
    registry_load_delay_s = 0.015
    scenario_device_vars_load_delay_s = 0.005
    start_workflow_delay_s = 0.005
    flush_meta_delay_s = 0.001
    fan_out = FanOutResult(
        dispatch_id=f"dispatch-scale-{device_count}",
        campaign_id="camp-runtime-scale",
        dispatch_strategy="parallel",
        executions=[
            FanOutExecutionView(
                execution_id=f"exec-{idx:04d}",
                device_id=f"dev-{idx:04d}",
                status="running",
                effective_vars={"kw": f"value-{idx}"},
            )
            for idx in range(device_count)
        ],
    )
    executions_by_id = {
        view.execution_id: SimpleNamespace(
            id=view.execution_id,
            meta={},
            checkpoint_step=0,
            device_config={
                "effective_vars": view.effective_vars,
                "account_vars": {},
                "device_serial": f"SN{idx:04d}",
            },
        )
        for idx, view in enumerate(fan_out.executions, start=1)
    }

    active_workflows = 0
    max_active_workflows = 0

    async def _load_runtime_executions(_db, execution_ids: list[str]):
        await asyncio.sleep(bulk_execution_load_delay_s)
        return {
            execution_id: executions_by_id[execution_id]
            for execution_id in execution_ids
        }

    async def _load_runtime_device_serials(_db, _execution_ids: list[str]):
        await asyncio.sleep(bulk_device_serial_load_delay_s)
        return {}

    async def _build_registry(*_args, **_kwargs):
        await asyncio.sleep(registry_load_delay_s)
        return {}

    async def _load_scenario_device_vars(*_args, **_kwargs):
        await asyncio.sleep(scenario_device_vars_load_delay_s)
        return {}

    async def _start_workflow(*_args, **_kwargs):
        nonlocal active_workflows, max_active_workflows
        active_workflows += 1
        max_active_workflows = max(max_active_workflows, active_workflows)
        try:
            await asyncio.sleep(start_workflow_delay_s)
        finally:
            active_workflows -= 1

    async def _flush_meta():
        await asyncio.sleep(flush_meta_delay_s)

    db = SimpleNamespace(flush=AsyncMock(side_effect=_flush_meta))
    campaign = SimpleNamespace(
        id="camp-runtime-scale",
        org_id="org-runtime",
        user_id="user-owner",
        created_by="user-owner",
        variables={},
        recovery_policy={},
    )
    temporal_client = SimpleNamespace(start_workflow=AsyncMock(side_effect=_start_workflow))
    temporal_config = SimpleNamespace(enabled=True, task_queue="device-scenario")

    with patch(
        "services.campaign.execution_runtime.resolve_campaign_scenario_refs",
        new=AsyncMock(return_value=[{"scenario_id": "sc-1"}]),
    ), patch(
        "services.campaign.execution_runtime._load_runtime_executions_by_id",
        new=AsyncMock(side_effect=_load_runtime_executions),
    ), patch(
        "services.campaign.execution_runtime._load_runtime_device_serials_by_execution",
        new=AsyncMock(side_effect=_load_runtime_device_serials),
    ), patch(
        "services.campaign.execution_runtime.build_campaign_scenario_registry",
        new=AsyncMock(side_effect=_build_registry),
    ), patch(
        "db.crud.scenario_device_variable.get_campaign_org_scenario_device_variables_bulk",
        new=AsyncMock(side_effect=_load_scenario_device_vars),
    ):
        started_at = time.perf_counter()
        stats = await start_execution_runtime(
            db,
            fan_out=fan_out,
            campaign=campaign,
            org_id=campaign.org_id,
            actor_user_id="user-owner",
            temporal_client=temporal_client,
            temporal_config=temporal_config,
            manager=None,
        )
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0

    budget_ms = perf_budget(
        f"EPIC04_RUNTIME_START_{device_count}_DEVICE_BUDGET_MS",
        budget_ms,
    )
    assert stats["temporal"] == device_count
    assert temporal_client.start_workflow.await_count == device_count
    assert db.flush.await_count == 1
    assert 1 < max_active_workflows <= 100
    assert elapsed_ms < budget_ms


@pytest.mark.asyncio
async def test_start_runtime_fallback_when_temporal_disabled(session_factory):
    await _seed_orgs(session_factory)
    campaign_id, execution_id = await _seed_campaign_execution(session_factory)

    fan_out = FanOutResult(
        dispatch_id="d2",
        campaign_id=campaign_id,
        dispatch_strategy="parallel",
        executions=[
            FanOutExecutionView(
                execution_id=execution_id,
                device_id="dev-1",
                status="running",
                effective_vars={},
            )
        ],
    )

    with patch(
        "services.campaign.execution_runtime.schedule_fallback_runtime",
    ) as schedule_mock:
        from tenancy.context import set_current_org_id

        set_current_org_id("org-runtime")
        async with session_factory() as db:
            campaign = await _load_campaign(db, campaign_id)
            stats = await start_execution_runtime(
                db,
                fan_out=fan_out,
                campaign=campaign,
                org_id=campaign.org_id,
                actor_user_id="user-owner",
                temporal_client=None,
                temporal_config=SimpleNamespace(enabled=False),
                manager=MagicMock(),
            )
            execution = await _load_execution(db, execution_id)

    assert stats["fallback"] == 1
    assert execution.meta.get("dispatch_source") == DISPATCH_SOURCE_FALLBACK
    schedule_mock.assert_called_once()


async def _seed_orgs(session_factory):
    from datetime import datetime, timezone

    from db.models import Organization, User

    NOW = datetime.now(timezone.utc)
    async with session_factory() as db:
        db.add(
            Organization(
                id="org-runtime",
                business_name="Runtime Org",
                business_email="r@org.local",
                status="active",
                plan="standard",
                created_at=NOW,
            )
        )
        db.add(
            User(
                id="user-owner",
                email="owner@org.local",
                name="Owner",
                hashed_password="x",
                org_id="org-runtime",
            )
        )
        await db.commit()


async def _seed_campaign_execution(session_factory):
    from datetime import datetime, timezone

    from db.crud.execution import add_device_to_execution, create_execution
    from db.models.campaign import Campaign
    from db.models.org_scenario import CampaignOrgScenarioRef, OrgScenario
    from db.models.device import Device

    NOW = datetime.now(timezone.utc)
    async with session_factory() as db:
        db.add(
            OrgScenario(
                id="sc-1",
                org_id="org-runtime",
                name="Wait",
                name_lower="wait",
                body_json={
                    "steps": [{"id": "w", "type": "input_wait.wait", "config": {"seconds": 1}}]
                },
            )
        )
        campaign = Campaign(
            id="camp-runtime-1",
            org_id="org-runtime",
            name="Runtime Camp",
            name_lower="runtime camp",
            description="",
            status="running",
            user_id="user-owner",
            created_by="user-owner",
            variables={"kw": "global"},
            created_at=NOW,
            updated_at=NOW,
        )
        db.add(campaign)
        db.add(
            CampaignOrgScenarioRef(
                id="ref-1",
                campaign_id=campaign.id,
                org_scenario_id="sc-1",
                order_index=0,
                pinned_version=1,
            )
        )
        device = Device(
            id="dev-1",
            serial="SN1",
            user_id="user-owner",
            org_id="org-runtime",
        )
        db.add(device)
        execution = await create_execution(
            db,
            run_type="campaign_device",
            campaign_id=campaign.id,
            user_id="user-owner",
            status="running",
            device_config={"effective_vars": {"kw": "v"}, "device_serial": "SN1"},
            meta={"dispatch_id": "d1", "dispatch_strategy": "parallel"},
        )
        await add_device_to_execution(db, execution.id, device.id)
        await db.commit()
        return campaign.id, execution.id


async def _load_campaign(db, campaign_id: str):
    from db.crud import campaign_entity as campaign_entity_repo

    campaign = await campaign_entity_repo.get_campaign_entity(db, campaign_id)
    assert campaign is not None
    return campaign


async def _load_execution(db, execution_id: str):
    from db.crud.execution import get_execution

    execution = await get_execution(db, execution_id)
    assert execution is not None
    return execution
