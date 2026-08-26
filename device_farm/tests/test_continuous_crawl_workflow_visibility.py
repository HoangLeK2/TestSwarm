"""Guards for the continuous crawl → UI visibility chain.

A continuous crawl used to be invisible to every workflow-shaped consumer: its
Temporal IDs do not have the `campaign:<id>:device:<serial>:scenario:<x>` shape,
so the campaign listing dropped them all, the UI concluded nothing was running,
and the pause and stop controls disappeared from a campaign that was very much
running. These tests pin the ID shapes and the settle-the-row behaviour that
depend on them, because both failure modes are silent: the endpoint returns 200
with an empty list, and the run keeps reporting a device as busy.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from api.routes.device_control.campaign_fleet import (
    is_campaign_top_level_workflow,
    is_device_top_level_workflow,
    _workflow_context_from_workflow_id,
)
from services.campaign.continuous_crawl import (
    crawl_target_workflow_id,
    crawl_workflow_id,
)

CAMPAIGN = "camp-1"
DISPATCH = "disp-1"
ENTITY = "group-99"
# A WiFi ADB serial carries a colon; nothing here may count colons to parse.
WIFI_SERIAL = "192.168.1.5:5555"
USB_SERIAL = "R58N12ABCDE"


@pytest.mark.parametrize("serial", [USB_SERIAL, WIFI_SERIAL])
def test_crawl_target_id_helper_matches_the_id_the_workflow_starts(serial):
    """The helper and ContinuousCrawlWorkflow._run_lane must agree byte for byte.

    The lane builds this ID inline; if the helper drifts from it, every consumer
    that parses the shape silently stops recognising running targets.
    """
    root = crawl_workflow_id(CAMPAIGN, DISPATCH)
    lane_built = f"{root}:device:{serial}:target:{ENTITY}"
    assert crawl_target_workflow_id(CAMPAIGN, DISPATCH, serial, ENTITY) == lane_built


@pytest.mark.parametrize("serial", [USB_SERIAL, WIFI_SERIAL])
def test_crawl_workflows_are_visible_to_the_campaign_view(serial):
    root = crawl_workflow_id(CAMPAIGN, DISPATCH)
    target = crawl_target_workflow_id(CAMPAIGN, DISPATCH, serial, ENTITY)

    assert is_campaign_top_level_workflow(root)
    assert is_campaign_top_level_workflow(target)


@pytest.mark.parametrize("serial", [USB_SERIAL, WIFI_SERIAL])
def test_only_the_target_occupies_a_device(serial):
    """The root drives the whole fleet; it must not show up as one device's run."""
    root = crawl_workflow_id(CAMPAIGN, DISPATCH)
    target = crawl_target_workflow_id(CAMPAIGN, DISPATCH, serial, ENTITY)

    assert not is_device_top_level_workflow(root)
    assert is_device_top_level_workflow(target)


@pytest.mark.parametrize("serial", [USB_SERIAL, WIFI_SERIAL])
def test_scenario_grandchild_stays_out_of_both_listings(serial):
    """`…:target:<id>:scenario` is an implementation detail, like `:steps`."""
    target = crawl_target_workflow_id(CAMPAIGN, DISPATCH, serial, ENTITY)
    grandchild = f"{target}:scenario"

    assert not is_campaign_top_level_workflow(grandchild)
    assert not is_device_top_level_workflow(grandchild)
    assert not is_campaign_top_level_workflow(f"{grandchild}:steps")


@pytest.mark.parametrize("serial", [USB_SERIAL, WIFI_SERIAL])
def test_normal_dispatch_workflows_keep_working(serial):
    sequence = f"campaign:{CAMPAIGN}:device:{serial}:scenario:__sequence__"

    assert is_campaign_top_level_workflow(sequence)
    assert is_device_top_level_workflow(sequence)
    assert not is_campaign_top_level_workflow(f"{sequence}:steps")


def test_exec_ids_are_not_mistaken_for_campaign_workflows():
    assert not is_campaign_top_level_workflow("exec_abc-123")
    assert not is_device_top_level_workflow("exec_abc-123")


@pytest.mark.parametrize("serial", [USB_SERIAL, WIFI_SERIAL])
def test_crawl_target_context_carries_campaign_and_serial(serial):
    target = crawl_target_workflow_id(CAMPAIGN, DISPATCH, serial, ENTITY)

    context = _workflow_context_from_workflow_id(target)

    assert context["campaign_id"] == CAMPAIGN
    assert context["device_serial"] == serial
    assert context["workflow_kind"] == "crawl_target"
    assert context["dispatch_source"] == "continuous_crawl"


def test_crawl_root_context_has_no_device():
    context = _workflow_context_from_workflow_id(crawl_workflow_id(CAMPAIGN, DISPATCH))

    assert context["campaign_id"] == CAMPAIGN
    assert context["device_serial"] is None
    assert context["workflow_kind"] == "crawl_root"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("execution_status", "expected_result_status"),
    [("completed", "passed"), ("failed", "failed"), ("cancelled", "failed")],
)
async def test_finish_fan_out_settles_open_result_rows(
    execution_status, expected_result_status
):
    """A terminal execution must not leave a per-device row at 'running'.

    Cumulative run stats count those rows, so an unsettled one keeps the
    campaign reporting an in-flight device long after the phone was released.
    """
    from services.campaign.dispatcher import finish_fan_out_execution

    execution = SimpleNamespace(id="exec-1", campaign_id=None)
    db = AsyncMock()

    with (
        patch("services.campaign.dispatcher.finish_execution", AsyncMock()),
        patch(
            "services.campaign.dispatcher.release_execution_device_claim",
            AsyncMock(),
        ),
    ):
        await finish_fan_out_execution(
            db,
            execution,
            org_id="org-1",
            actor_user_id="user-1",
            status=execution_status,
            device_id="device-1",
        )

    statements = [call.args[0] for call in db.execute.await_args_list]
    results_update = next(
        stmt for stmt in statements if stmt.table.name == "execution_results"
    )
    params = results_update.compile().params
    assert params["status"] == expected_result_status
    # Only rows with no recorded outcome — a pass/fail written by
    # finalize_campaign must never be overwritten by this settle pass.
    where_sql = str(results_update.whereclause)
    assert "status IN" in where_sql
