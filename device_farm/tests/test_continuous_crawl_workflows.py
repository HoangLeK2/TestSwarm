import asyncio
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from temporal.continuous_crawl_workflows import (
    CleanupCrawlTargetInput,
    ContinuousCrawlInput,
    ContinuousCrawlProgress,
    ContinuousCrawlWorkflow,
    CrawlTarget,
    CrawlTargetInput,
    FinalizeCrawlInput,
    LoadCrawlPageResult,
    PrepareCrawlTargetInput,
    circuit_breaker_reason,
)


def crawl_input(**changes):
    values = {
        "campaign_id": "campaign-1",
        "dispatch_id": "dispatch-1",
        "org_id": "org-1",
        "device_serials": ["device-1", "device-2"],
        "source_pool": {"platform": "facebook", "entity_type": "profile"},
        "snapshot_at": "2026-08-07T00:00:00+00:00",
    }
    values.update(changes)
    return ContinuousCrawlInput(**values)


def test_contracts_are_deterministic_frozen_values():
    target = CrawlTarget("entity-1", {"name": "Ada"})
    with pytest.raises(FrozenInstanceError):
        target.external_entity_id = "entity-2"  # type: ignore[misc]
    assert crawl_input().max_concurrency == 10


def test_target_contract_propagates_source_pool_and_finalize_org_fence():
    source_pool = {"platform": "facebook", "entity_type": "group"}
    target = CrawlTarget("entity-1")
    child = CrawlTargetInput(
        "campaign-1", "dispatch-1", "org-1", "device-1", target, source_pool
    )
    prepare = PrepareCrawlTargetInput(
        child.campaign_id,
        child.dispatch_id,
        child.org_id,
        child.device_serial,
        child.target,
        child.source_pool,
    )
    finalize = FinalizeCrawlInput(
        child.campaign_id,
        child.dispatch_id,
        child.org_id,
        "completed",
        ContinuousCrawlProgress(),
    )
    assert prepare.source_pool is source_pool
    assert finalize.org_id == "org-1"


@pytest.mark.parametrize(
    ("inp", "progress", "reason"),
    [
        (
            crawl_input(failure_policy="fail_fast"),
            ContinuousCrawlProgress(failed=1),
            "target failed under fail-fast policy",
        ),
        (
            crawl_input(max_failure_ratio=0.25),
            ContinuousCrawlProgress(succeeded=2, failed=1),
            "maximum failure ratio exceeded",
        ),
        (
            crawl_input(max_consecutive_failures=3),
            ContinuousCrawlProgress(failed=3, consecutive_failures=3),
            "maximum consecutive failures exceeded",
        ),
        (crawl_input(), ContinuousCrawlProgress(succeeded=9, failed=1), None),
    ],
)
def test_circuit_breaker_is_deterministic(inp, progress, reason):
    assert circuit_breaker_reason(inp, progress) == reason


def test_progress_query_and_control_signals_are_registered():
    definition = ContinuousCrawlWorkflow.__temporal_workflow_definition
    assert definition.name == "ContinuousCrawlWorkflow"
    assert set(definition.signals) >= {"pause", "resume", "cancel"}
    assert "get_progress" in definition.queries


def test_pause_drains_active_targets_without_forwarding_pause(monkeypatch):
    workflow = ContinuousCrawlWorkflow()
    workflow._active_child_ids.add("target-1")

    async def unexpected_signal(_signal):
        pytest.fail("pause must not interrupt active target workflows")

    monkeypatch.setattr(workflow, "_signal_children", unexpected_signal)
    asyncio.run(workflow.pause())

    assert workflow.get_progress().status == "pausing"


def test_pause_is_immediate_when_no_targets_are_active():
    workflow = ContinuousCrawlWorkflow()

    asyncio.run(workflow.pause())

    assert workflow.get_progress().status == "paused"


def test_operational_progress_is_bounded_and_tracks_each_lane():
    workflow = ContinuousCrawlWorkflow()
    inp = crawl_input(device_serials=[f"device-{index}" for index in range(20)])

    workflow._initialize_operational_progress(inp, lane_count=20)
    for index in range(12):
        target = CrawlTarget(
            f"entity-{index}",
            {"display_name": f"Target {index}"},
        )
        workflow._mark_target_running("device-0", target)
        workflow._mark_target_finished(
            "device-0",
            target,
            success=index % 3 != 0,
            message="failed" if index % 3 == 0 else "",
        )

    progress = workflow.get_progress()
    assert len(progress.device_lanes) == 20
    assert progress.device_lanes[0] == {
        "device_serial": "device-0",
        "status": "idle",
        "target_id": None,
        "target_label": None,
        "completed": 8,
        "failed": 4,
        "message": None,
    }
    assert len(progress.recent_targets) == 8
    assert progress.recent_targets[0]["target_id"] == "entity-11"
    assert progress.recent_targets[-1]["target_id"] == "entity-4"


def test_failed_child_outcome_runs_cleanup_and_records_failure(monkeypatch):
    crawl = ContinuousCrawlWorkflow()
    inp = crawl_input(device_serials=["device-1"])
    target = CrawlTarget("entity-1", {"display_name": "Python"})
    queue: asyncio.Queue[CrawlTarget | None] = asyncio.Queue()
    queue.put_nowait(target)
    queue.put_nowait(None)
    cleanup_inputs: list[CleanupCrawlTargetInput] = []

    async def wait_condition(_predicate):
        return None

    async def execute_child_workflow(*_args, **_kwargs):
        return SimpleNamespace(success=False, message="scenario failed")

    async def execute_activity(_name, activity_input, **_kwargs):
        cleanup_inputs.append(activity_input)

    monkeypatch.setattr(
        "temporal.continuous_crawl_workflows.workflow.wait_condition", wait_condition
    )
    monkeypatch.setattr(
        "temporal.continuous_crawl_workflows.workflow.info",
        lambda: SimpleNamespace(workflow_id="crawl-1"),
    )
    monkeypatch.setattr(
        "temporal.continuous_crawl_workflows.workflow.execute_child_workflow",
        execute_child_workflow,
    )
    monkeypatch.setattr(
        "temporal.continuous_crawl_workflows.workflow.execute_activity",
        execute_activity,
    )

    crawl._initialize_operational_progress(inp, lane_count=1)
    asyncio.run(crawl._run_lane(inp, "device-1", queue))

    assert cleanup_inputs == [
        CleanupCrawlTargetInput(
            inp.campaign_id,
            inp.dispatch_id,
            inp.org_id,
            target.external_entity_id,
            "device-1",
        )
    ]
    assert crawl.get_progress().failed == 1


def test_cleanup_failure_does_not_abort_lane(monkeypatch):
    crawl = ContinuousCrawlWorkflow()
    inp = crawl_input(device_serials=["device-1"])
    target = CrawlTarget("entity-1", {"display_name": "Python"})
    queue: asyncio.Queue[CrawlTarget | None] = asyncio.Queue()
    queue.put_nowait(target)
    queue.put_nowait(None)
    cleanup_attempts = 0

    async def wait_condition(_predicate):
        return None

    async def execute_child_workflow(*_args, **_kwargs):
        return SimpleNamespace(success=False, message="scenario failed")

    async def execute_activity(*_args, **_kwargs):
        nonlocal cleanup_attempts
        cleanup_attempts += 1
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        "temporal.continuous_crawl_workflows.workflow.wait_condition", wait_condition
    )
    monkeypatch.setattr(
        "temporal.continuous_crawl_workflows.workflow.info",
        lambda: SimpleNamespace(workflow_id="crawl-1"),
    )
    monkeypatch.setattr(
        "temporal.continuous_crawl_workflows.workflow.execute_child_workflow",
        execute_child_workflow,
    )
    monkeypatch.setattr(
        "temporal.continuous_crawl_workflows.workflow.execute_activity",
        execute_activity,
    )

    crawl._initialize_operational_progress(inp, lane_count=1)
    asyncio.run(crawl._run_lane(inp, "device-1", queue))

    progress = crawl.get_progress()
    assert cleanup_attempts == 1
    assert progress.failed == 1
    assert progress.recent_targets[0]["message"] == (
        "scenario failed; cleanup failed: database unavailable"
    )


def test_workflow_routes_each_assigned_target_to_its_own_device(monkeypatch):
    crawl = ContinuousCrawlWorkflow()
    inp = crawl_input(device_serials=["phone-a", "phone-b"], max_concurrency=2)
    child_pairs: list[tuple[str, str]] = []
    child_ids: list[str] = []

    async def wait_condition(_predicate):
        return None

    async def execute_activity(name, activity_input, **_kwargs):
        if name == "load_continuous_crawl_source_page":
            assert activity_input.device_serials == ["phone-a", "phone-b"]
            return LoadCrawlPageResult(
                targets=[
                    CrawlTarget(
                        "entity-shared",
                        {"display_name": "Shared profile"},
                        device_serial="phone-a",
                    ),
                    CrawlTarget(
                        "entity-shared",
                        {"display_name": "Shared profile"},
                        device_serial="phone-b",
                    ),
                ],
                exhausted=True,
            )
        return None

    async def execute_child_workflow(_workflow_run, child_input, **kwargs):
        child_pairs.append(
            (child_input.device_serial, child_input.target.device_serial)
        )
        child_ids.append(kwargs["id"])
        return SimpleNamespace(success=True, message="")

    monkeypatch.setattr(
        "temporal.continuous_crawl_workflows.workflow.wait_condition", wait_condition
    )
    monkeypatch.setattr(
        "temporal.continuous_crawl_workflows.workflow.info",
        lambda: SimpleNamespace(workflow_id="crawl-1"),
    )
    monkeypatch.setattr(
        "temporal.continuous_crawl_workflows.workflow.execute_activity",
        execute_activity,
    )
    monkeypatch.setattr(
        "temporal.continuous_crawl_workflows.workflow.execute_child_workflow",
        execute_child_workflow,
    )

    progress = asyncio.run(crawl.run(inp))

    assert sorted(child_pairs) == [
        ("phone-a", "phone-a"),
        ("phone-b", "phone-b"),
    ]
    assert len(set(child_ids)) == 2
    assert progress.succeeded == 2
    assert len(progress.recent_targets) == 2
