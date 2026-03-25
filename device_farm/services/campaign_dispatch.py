

from __future__ import annotations

from typing import Any, Dict, Tuple

from db.database import AsyncSessionLocal
from db import crud as repo
from runtime.core import Task, TaskQueue


async def enqueue_campaign_run(
    campaign_id: str,
    queue: TaskQueue,
) -> Tuple[Dict[str, Any], int]:
    """
    Load campaign + devices from DB, push scenario/example tasks to queue.
    Returns (json_body, http_status).
    """
    from tasks.example_task import demo_u2_task
    from tasks.scenario_task import make_scenario_task

    async with AsyncSessionLocal() as db:
        campaign = await repo.get_campaign(db, campaign_id)
        if not campaign:
            return {"error": "Campaign not found"}, 404

        devices = await repo.list_campaign_devices(db, campaign_id)
        if not devices:
            return {"error": "Campaign has no devices"}, 400

        scenarios = await repo.list_scenarios(db, campaign_id)
        legacy_scenario: dict = campaign.scenario or {}

        await repo.update_campaign_status(db, campaign_id, "running")
        await db.commit()

    task_ids: list[str] = []

    if scenarios:
        for d in devices:
            for scen in scenarios:
                if not scen.steps:
                    continue
                payload = {"instructions": scen.instructions or "", "steps": scen.steps}
                task = Task(
                    fn=make_scenario_task(payload),
                    priority=5,
                    target=d.serial,
                    timeout=300,
                    max_retries=1,
                    name=f"campaign:{campaign_id}:scenario:{scen.id}",
                )
                queue.put(task)
                task_ids.append(task.id)
    elif isinstance(legacy_scenario, dict) and legacy_scenario.get("steps"):
        for d in devices:
            task = Task(
                fn=make_scenario_task(legacy_scenario),
                priority=5,
                target=d.serial,
                timeout=300,
                max_retries=1,
                name=f"campaign:{campaign_id}:scenario",
            )
            queue.put(task)
            task_ids.append(task.id)
    else:
        for d in devices:
            task = Task(
                fn=demo_u2_task,
                priority=5,
                target=d.serial,
                timeout=300,
                max_retries=1,
                name=f"campaign:{campaign_id}:example",
            )
            queue.put(task)
            task_ids.append(task.id)

    return {
        "id": campaign_id,
        "status": "running",
        "device_serials": [d.serial for d in devices],
        "task_ids": task_ids,
        "scenarios_count": len(scenarios),
    }, 200
