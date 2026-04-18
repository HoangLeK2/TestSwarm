from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from runtime.core.device_client import DeviceState
from runtime.core.dispatcher import Dispatcher
from runtime.core.task_queue import Task, TaskQueue, TaskStatus
from tests.perf_assertions import (
    MemoryTracker,
    assert_p95,
    assert_peak_memory,
    assert_queue_growth,
    perf_budget,
)


def _cfg() -> SimpleNamespace:
    return SimpleNamespace(
        dispatcher=SimpleNamespace(loop_interval=0.01, max_tasks_per_minute=100),
    )


def _device(serial: str, state: DeviceState = DeviceState.READY) -> SimpleNamespace:
    return SimpleNamespace(serial=serial, state=state, ensure_u2_healthy=MagicMock(return_value=True))


def test_dispatch_cycle_ignores_busy_device_and_dispatches_ready_only():
    ready = _device("SN_READY", DeviceState.READY)
    busy = _device("SN_BUSY", DeviceState.BUSY)
    manager = MagicMock()
    manager.ready_devices.return_value = [ready]  # busy device intentionally excluded by manager

    queue = MagicMock()
    queue.get_next.return_value = None

    disp = Dispatcher(manager=manager, queue=queue, config=_cfg())
    disp._dispatch_cycle()

    queue.get_next.assert_called_once_with(serial="SN_READY")


def test_run_task_requeues_on_exception_when_retries_remain():
    device = _device("SN001", DeviceState.BUSY)
    manager = MagicMock()
    queue = MagicMock()
    disp = Dispatcher(manager=manager, queue=queue, config=_cfg())

    task = Task(fn=lambda _d: (_ for _ in ()).throw(RuntimeError("boom")), max_retries=2, timeout=1.0)
    task.retry_count = 0

    disp._run_task(device, task)

    queue.requeue.assert_called_once_with(task)
    assert task.status in (TaskStatus.REQUEUED, TaskStatus.PENDING, TaskStatus.RUNNING)
    assert device.state == DeviceState.READY


def test_run_task_marks_failed_when_scenario_result_is_unsuccessful():
    device = _device("SN001", DeviceState.BUSY)
    manager = MagicMock()
    queue = MagicMock()
    disp = Dispatcher(manager=manager, queue=queue, config=_cfg())

    task = Task(
        fn=lambda _d: {"success": False, "failed_message": "step failed"},
        max_retries=3,
        timeout=1.0,
    )
    task.retry_count = 0

    disp._run_task(device, task)

    queue.requeue.assert_not_called()
    assert task.status == TaskStatus.FAILED
    assert "step failed" in (task.error or "")
    assert device.state == DeviceState.READY


def test_run_task_timeout_requeues_when_retry_available():
    device = _device("SN001", DeviceState.BUSY)
    manager = MagicMock()
    queue = MagicMock()
    disp = Dispatcher(manager=manager, queue=queue, config=_cfg())

    def _slow_task(_d):
        time.sleep(0.15)
        return {"ok": True}

    task = Task(fn=_slow_task, timeout=0.01, max_retries=2)
    task.retry_count = 0

    disp._run_task(device, task)

    queue.requeue.assert_called_once_with(task)
    assert device.state == DeviceState.READY


def test_dispatcher_perf_budget_and_queue_growth():
    manager = MagicMock()
    queue = TaskQueue()
    disp = Dispatcher(manager=manager, queue=queue, config=_cfg())
    device = _device("SN_PERF", DeviceState.READY)

    latencies_ms: list[float] = []
    for i in range(50):
        queue.put(Task(fn=lambda _d: {"success": True}, target="SN_PERF", max_retries=0, timeout=1.0, name=f"perf-{i}"))

    max_pending = 0
    with MemoryTracker(enabled=True) as mem:
        while True:
            pending = queue.pending_count()
            max_pending = max(max_pending, pending)
            task = queue.get_next(serial="SN_PERF")
            if task is None:
                break
            device.state = DeviceState.BUSY
            t0 = time.perf_counter()
            disp._run_task(device, task)
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)

    p95_budget_ms = perf_budget("STRESS_DISPATCHER_P95_MS_BUDGET", 100.0)
    peak_mem_budget_mb = perf_budget("STRESS_DISPATCHER_PEAK_MEM_MB_BUDGET", 96.0)
    max_pending_budget = int(perf_budget("STRESS_DISPATCHER_MAX_PENDING_BUDGET", 80))
    assert_p95(latencies_ms, p95_budget_ms, label="dispatcher_run_task")
    assert_peak_memory(mem.peak_mb, peak_mem_budget_mb, label="dispatcher_memory")
    assert_queue_growth(
        max_pending=max_pending,
        end_pending=queue.pending_count(),
        max_budget=max_pending_budget,
        label="dispatcher_queue_growth",
    )
