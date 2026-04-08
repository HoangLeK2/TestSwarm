"""
Fleet-wide scenario dispatch (many devices, one scenario payload).
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from runtime.core import DeviceManager, Task, TaskQueue


def _device_has_all_tags(serial: str, serial_tags: Dict[str, str], filter_tags: List[str]) -> bool:
    """
    Return True if the device (identified by serial) has ALL tags in filter_tags.

    Tags are stored as comma-separated lowercase strings in serial_tags.
    AND logic: the device must have every requested tag.
    """
    raw = serial_tags.get(serial, "")
    device_tag_set = {t.strip() for t in raw.split(",") if t.strip()}
    return all(tag in device_tag_set for tag in filter_tags)


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
    # DF-004: optional pre-loaded filters (resolved from DB in the async route handler)
    group_serials: Optional[FrozenSet[str]] = None,
    filter_tags: Optional[List[str]] = None,
    serial_tags: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], int]:
    """
    Enqueue scenario tasks for matching live devices.

    group_serials: frozenset of device serials belonging to a device group
                   (pre-loaded from DB by the route handler, None = no group filter)
    filter_tags:   list of tags that a device must have ALL of (AND logic)
    serial_tags:   {serial: tags_string} map pre-loaded from DB for tag matching
    """
    from tasks.scenario_task import make_scenario_task

    all_devices = manager.all_devices()

    # 1. state filter — exact enum name match; empty string defaults to "READY"
    _state = filter_state.strip().upper() or "READY"
    target_devices = [
        d for d in all_devices
        if d.state.name.upper() == _state
    ]
    # 2. model substring filter
    if filter_model:
        needle = filter_model.lower()
        target_devices = [
            d for d in target_devices
            if needle in (d.model or "").lower()
        ]
    # 3. group filter (O(1) per device — frozenset lookup)
    if group_serials is not None:
        target_devices = [d for d in target_devices if d.serial in group_serials]

    # 4. tags filter (AND logic — device must have all requested tags)
    if filter_tags:
        tags_map = serial_tags or {}
        normalised = [t.strip().lower() for t in filter_tags if t.strip()]
        target_devices = [
            d for d in target_devices
            if _device_has_all_tags(d.serial, tags_map, normalised)
        ]

    # 5. cap
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
