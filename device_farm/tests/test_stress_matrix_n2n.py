from __future__ import annotations

import asyncio
import time
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.routes import campaigns as campaigns_route
from runtime.core.device_client import DeviceState
from runtime.core.dispatcher import Dispatcher
from runtime.core.task_queue import Task, TaskQueue
from services.campaign_dispatch import enqueue_campaign_run_temporal
from tests.perf_assertions import (
    MemoryTracker,
    assert_p95,
    assert_peak_memory,
    assert_queue_growth,
    perf_budget,
)


def _db_mock():
    db = AsyncMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=False)
    return db


def _campaign(campaign_id: str, user_id: str = "user-1"):
    return SimpleNamespace(id=campaign_id, user_id=user_id, variables={}, target_group_id=None)


def _device(device_id: str, serial: str):
    return SimpleNamespace(id=device_id, serial=serial)


def _scenario(scenario_id: str):
    return SimpleNamespace(id=scenario_id, steps=[{"type": "wait", "seconds": 0}], variables={}, name=scenario_id)


@pytest.mark.asyncio
async def test_matrix_single_device_two_campaign_allow_policy_distinct_workflows():
    db = _db_mock()
    temporal = AsyncMock()
    temporal.start_workflow = AsyncMock()

    campaigns = [_campaign("camp-1"), _campaign("camp-2")]
    executions = [
        SimpleNamespace(id="exec-1", meta={"scenarios_count": 1}),
        SimpleNamespace(id="exec-2", meta={"scenarios_count": 1}),
    ]

    with ExitStack() as stack:
        stack.enter_context(patch("services.campaign_dispatch.AsyncSessionLocal", return_value=db))
        stack.enter_context(patch("services.campaign_dispatch.repo.get_campaign", side_effect=campaigns))
        stack.enter_context(
            patch("services.campaign_dispatch.repo.list_campaign_devices", return_value=[_device("dev-1", "SN001")])
        )
        stack.enter_context(patch("services.campaign_dispatch.repo.list_scenarios", return_value=[_scenario("sc-1")]))
        stack.enter_context(patch("services.campaign_dispatch.repo.update_campaign_status", new_callable=AsyncMock))
        stack.enter_context(patch("db.crud.scenario_template.list_templates", new_callable=AsyncMock, return_value=[]))
        stack.enter_context(patch("services.campaign_dispatch._get_device_account_vars", new_callable=AsyncMock, return_value={}))
        stack.enter_context(patch("db.crud.execution.create_execution", new_callable=AsyncMock, side_effect=executions))
        stack.enter_context(patch("db.crud.execution.add_device_to_execution", new_callable=AsyncMock))
        stack.enter_context(patch("db.crud.execution.update_execution", new_callable=AsyncMock))

        r1, s1 = await enqueue_campaign_run_temporal("camp-1", temporal)
        r2, s2 = await enqueue_campaign_run_temporal("camp-2", temporal)

    assert s1 == 200 and s2 == 200
    assert r1["workflow_ids"][0] != r2["workflow_ids"][0]
    assert "campaign:camp-1" in r1["workflow_ids"][0]
    assert "campaign:camp-2" in r2["workflow_ids"][0]


@pytest.mark.asyncio
async def test_matrix_n_device_m_campaign_partial_overlap_device_sets():
    db = _db_mock()
    temporal = AsyncMock()
    temporal.start_workflow = AsyncMock()

    def _campaign_for(cid: str):
        return _campaign(cid)

    executions = [
        SimpleNamespace(id="exec-a", meta={"scenarios_count": 1}),
        SimpleNamespace(id="exec-b", meta={"scenarios_count": 1}),
    ]

    with ExitStack() as stack:
        stack.enter_context(patch("services.campaign_dispatch.AsyncSessionLocal", return_value=db))
        stack.enter_context(
            patch("services.campaign_dispatch.repo.get_campaign", side_effect=[_campaign_for("camp-a"), _campaign_for("camp-b")])
        )
        # camp-a: SN001,SN002 ; camp-b: overlap SN002,SN003 via override
        stack.enter_context(
            patch("services.campaign_dispatch.repo.list_campaign_devices", return_value=[_device("d1", "SN001"), _device("d2", "SN002")])
        )
        stack.enter_context(patch("services.campaign_dispatch.repo.list_scenarios", return_value=[_scenario("sc-1")]))
        stack.enter_context(patch("services.campaign_dispatch.repo.update_campaign_status", new_callable=AsyncMock))
        stack.enter_context(patch("db.crud.scenario_template.list_templates", new_callable=AsyncMock, return_value=[]))
        stack.enter_context(patch("services.campaign_dispatch._get_device_account_vars", new_callable=AsyncMock, return_value={}))
        stack.enter_context(patch("db.crud.execution.create_execution", new_callable=AsyncMock, side_effect=executions))
        stack.enter_context(patch("db.crud.execution.add_device_to_execution", new_callable=AsyncMock))
        stack.enter_context(patch("db.crud.execution.update_execution", new_callable=AsyncMock))
        stack.enter_context(
            patch(
                "db.crud.device.get_device_by_serial",
                new_callable=AsyncMock,
                side_effect=[_device("d2", "SN002"), _device("d3", "SN003")],
            )
        )

        ra, sa = await enqueue_campaign_run_temporal("camp-a", temporal)
        rb, sb = await enqueue_campaign_run_temporal(
            "camp-b",
            temporal,
            device_serials_override=["SN002", "SN003"],
        )

    assert sa == 200 and sb == 200
    assert sorted(ra["device_serials"]) == ["SN001", "SN002"]
    assert sorted(rb["device_serials"]) == ["SN002", "SN003"]


@pytest.mark.asyncio
async def test_matrix_campaign1_running_then_campaign2_cancel_and_force_run_paths():
    user = SimpleNamespace(id="user-1")
    db = AsyncMock()
    queue = MagicMock()
    queue.cancel_by_name_prefix.return_value = 3

    class _Handle:
        def __init__(self):
            self.cancel = AsyncMock()
            self.signal = AsyncMock()

    class _TemporalClient:
        def __init__(self):
            self.handle = _Handle()

        async def list_workflows(self, _query):
            yield SimpleNamespace(id="campaign:camp-1:device:SN001:scenario:sc-1")

        def get_workflow_handle(self, _wf_id):
            return self.handle

    temporal_client = _TemporalClient()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                queue=queue,
                config=SimpleNamespace(temporal=SimpleNamespace(enabled=True)),
            )
        )
    )

    with (
        patch.object(campaigns_route, "_get_campaign_or_404", new=AsyncMock(return_value=_campaign("camp-1"))),
        patch.object(campaigns_route.repo, "update_campaign_status", new=AsyncMock()),
        patch("temporal.worker.get_temporal_client", new=AsyncMock(return_value=temporal_client)),
    ):
        cancelled = await campaigns_route.update_status(
            "camp-1",
            campaigns_route.StatusUpdate(status="stopped"),
            db,
            user,
            request,
        )
        resumed = await campaigns_route.update_status(
            "camp-1",
            campaigns_route.StatusUpdate(status="running"),
            db,
            user,
            request,
        )

    assert cancelled["tasks_cancelled"] == 3
    assert cancelled["status"] == "idle"
    temporal_client.handle.cancel.assert_awaited()
    temporal_client.handle.signal.assert_awaited()  # running => resume signal path
    assert resumed["status"] == "running"


def test_matrix_device_dead_mid_run_keeps_dead_state_for_recovery_logic():
    manager = MagicMock()
    queue = TaskQueue()
    cfg = SimpleNamespace(dispatcher=SimpleNamespace(loop_interval=0.01, max_tasks_per_minute=100))
    dispatcher = Dispatcher(manager=manager, queue=queue, config=cfg)

    device = SimpleNamespace(
        serial="SN001",
        state=DeviceState.BUSY,
        ensure_u2_healthy=MagicMock(return_value=True),
    )

    def _dead_mid_run(_dev):
        _dev.state = DeviceState.DEAD
        return {"success": False, "failed_message": "device disconnected"}

    task = Task(fn=_dead_mid_run, target="SN001", max_retries=0, timeout=1.0, name="campaign:camp-1:scenario:sc-1")
    queue.put(task)
    running = queue.get_next(serial="SN001")
    dispatcher._run_task(device, running)

    assert device.state == DeviceState.DEAD
    assert running.status.name == "FAILED"


def test_matrix_mixed_outcome_aggregate_stats_done_fail_retry_timeout():
    manager = MagicMock()
    queue = TaskQueue()
    cfg = SimpleNamespace(dispatcher=SimpleNamespace(loop_interval=0.01, max_tasks_per_minute=100))
    dispatcher = Dispatcher(manager=manager, queue=queue, config=cfg)

    device = SimpleNamespace(
        serial="SN001",
        state=DeviceState.READY,
        ensure_u2_healthy=MagicMock(return_value=True),
    )

    def _ok(_d):
        return {"success": True}

    def _scenario_fail(_d):
        return {"success": False, "failed_message": "step failed"}

    def _timeout(_d):
        time.sleep(0.05)
        return {"success": True}

    queue.put(Task(fn=_ok, target="SN001", max_retries=0, timeout=1.0, name="campaign:a:ok"))
    queue.put(Task(fn=_scenario_fail, target="SN001", max_retries=2, timeout=1.0, name="campaign:a:fail"))
    queue.put(Task(fn=_timeout, target="SN001", max_retries=1, timeout=0.01, name="campaign:a:timeout"))

    # Drain queue, including requeued tasks.
    max_pending = 0
    latencies_ms: list[float] = []
    with MemoryTracker(enabled=True) as mem:
        while True:
            max_pending = max(max_pending, queue.pending_count())
            task = queue.get_next(serial="SN001")
            if task is None:
                break
            device.state = DeviceState.BUSY
            t0 = time.perf_counter()
            dispatcher._run_task(device, task)
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)

    stats = queue.stats()
    assert stats.get("DONE", 0) >= 1
    assert stats.get("FAILED", 0) >= 2
    assert stats.get("PENDING", 0) == 0
    p95_budget_ms = perf_budget("STRESS_MATRIX_P95_MS_BUDGET", 200.0)
    peak_mem_budget_mb = perf_budget("STRESS_MATRIX_PEAK_MEM_MB_BUDGET", 96.0)
    max_pending_budget = int(perf_budget("STRESS_MATRIX_MAX_PENDING_BUDGET", 20))
    assert_p95(latencies_ms, p95_budget_ms, label="stress_matrix_dispatch")
    assert_peak_memory(mem.peak_mb, peak_mem_budget_mb, label="stress_matrix_memory")
    assert_queue_growth(
        max_pending=max_pending,
        end_pending=queue.pending_count(),
        max_budget=max_pending_budget,
        label="stress_matrix_queue",
    )
