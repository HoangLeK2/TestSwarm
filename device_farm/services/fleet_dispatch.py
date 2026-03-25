"""
Fleet-wide scenario dispatch (many devices, one scenario payload).
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

from runtime.core import DeviceManager, Task, TaskQueue


def enqueue_fleet_scenario(
    manager: DeviceManager,
    queue: TaskQueue,
    *,
    steps: List[Dict[str, Any]],
    filter_state: str,
    filter_model: Optional[str],
    max_devices: Optional[int],
    priority: int,
    timeout: float,
    max_retries: int,
) -> Tuple[Dict[str, Any], int]:
    from tasks.scenario_task import make_scenario_task

    all_devices = manager.all_devices()
    target_devices = [
        d for d in all_devices
        if filter_state.upper() in d.state.name.upper()
    ]
    if filter_model:
        needle = filter_model.lower()
        target_devices = [
            d for d in target_devices
            if needle in (d.model or "").lower()
        ]
    if max_devices is not None:
        target_devices = target_devices[:max_devices]

    if not target_devices:
        return {
            "error": f"No devices match filter_state={filter_state!r}",
        }, 400

    scenario: Dict[str, Any] = {"instructions": "", "steps": steps}
    fn = make_scenario_task(scenario)

    run_id = str(uuid.uuid4())
    task_ids: List[str] = []
    for d in target_devices:
        task = Task(
            fn=fn,
            priority=priority,
            target=d.serial,
            timeout=timeout,
            max_retries=max_retries,
            name=f"fleet:{run_id}",
        )
        queue.put(task)
        task_ids.append(task.id)

    return {
        "run_id": run_id,
        "dispatched": len(task_ids),
        "task_ids": task_ids,
        "device_serials": [d.serial for d in target_devices],
    }, 200


def fleet_run_status(queue: TaskQueue, run_id: Optional[str]) -> Dict[str, Any]:
    all_tasks = queue.all_tasks()
    if run_id:
        prefix = f"fleet:{run_id}"
        all_tasks = [t for t in all_tasks if t.name.startswith(prefix)]

    counts: Dict[str, int] = {}
    for t in all_tasks:
        counts[t.status.value] = counts.get(t.status.value, 0) + 1

    total = len(all_tasks)
    done = counts.get("DONE", 0)
    failed = counts.get("FAILED", 0)
    cancelled = counts.get("CANCELLED", 0)
    terminal = done + failed + cancelled
    return {
        "run_id": run_id,
        "total": total,
        "pending": counts.get("PENDING", 0),
        "running": counts.get("RUNNING", 0),
        "done": done,
        "failed": failed,
        "cancelled": cancelled,
        "progress_pct": round(terminal / total * 100, 1) if total else 0,
        "all_complete": terminal == total and total > 0,
    }
