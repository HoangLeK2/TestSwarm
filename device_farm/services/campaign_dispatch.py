
from __future__ import annotations

import logging
from typing import Any, Dict, Tuple

from db.database import AsyncSessionLocal
from db import crud as repo
from runtime.core import Task, TaskQueue

log = logging.getLogger(__name__)


async def _get_device_account_vars(
    device_id: str,
    platform: str,
    db,
) -> Dict[str, Any]:
    """
    DF-007: Resolve the primary active account for a device and return it as
    scenario variables so templates can use ${__ACCOUNT_USERNAME__} etc.
    Returns an empty dict if no primary account is configured.
    """
    from db.crud.account import get_primary_account_for_device
    from common.crypto import decrypt_password

    account = await get_primary_account_for_device(db, device_id, platform)
    if not account:
        return {}
    return {
        "__ACCOUNT_USERNAME__": account.username,
        "__ACCOUNT_PASSWORD__": decrypt_password(account.password_encrypted),
        "__ACCOUNT_DISPLAY_NAME__": account.display_name or "",
        "__ACCOUNT_PLATFORM__": account.platform,
    }


def _build_scenario_registry(
    scenarios: list,
    templates: list,
) -> Dict[str, Any]:
    """
    Build a flat, JSON-serializable scenario registry for sub-scenario lookup.

    Pre-loaded at async dispatch time to avoid async DB access inside the
    synchronous scenario_task executor.

    Structure:
        {
            "by_id":            {scenario_id: {steps, variables, name}},
            "by_campaign_name": {scenario_name: {steps, variables, name}},
            "by_template_name": {template_name: {steps, variables, name}},
        }
    """
    registry: Dict[str, Any] = {
        "by_id": {},
        "by_campaign_name": {},
        "by_template_name": {},
    }
    for s in scenarios:
        entry: Dict[str, Any] = {
            "steps": s.steps or [],
            "variables": s.variables or {},
            "name": s.name,
        }
        registry["by_id"][s.id] = entry
        # Last writer wins for duplicate names (same campaign, shouldn't happen).
        registry["by_campaign_name"][s.name] = entry

    for t in templates:
        registry["by_template_name"][t.name] = {
            "steps": t.steps or [],
            "variables": t.variables or {},
            "name": t.name,
        }
    return registry


async def enqueue_campaign_run(
    campaign_id: str,
    queue: TaskQueue,
) -> Tuple[Dict[str, Any], int]:
    """
    Load campaign + devices from DB, push scenario/example tasks to queue.
    Returns (json_body, http_status).

    DF-003: Pre-loads _scenario_registry (all campaign scenarios + all templates)
    at dispatch time so the synchronous task executor never needs async DB access.
    """
    from tasks.example_task import demo_u2_task
    from tasks.scenario_task import make_scenario_task
    from db.crud.scenario_template import list_templates
    from db.crud.device_group import list_group_devices

    async with AsyncSessionLocal() as db:
        campaign = await repo.get_campaign(db, campaign_id)
        if not campaign:
            return {"error": "Campaign not found"}, 404

        target_group_id = getattr(campaign, "target_group_id", None)
        if target_group_id:
            devices = await list_group_devices(db, target_group_id)
        else:
            devices = await repo.list_campaign_devices(db, campaign_id)

        if not devices:
            return {"error": "Campaign has no devices"}, 400

        scenarios = await repo.list_scenarios(db, campaign_id)
        templates = await list_templates(db)
        legacy_scenario: dict = campaign.scenario or {}

        # Build registry once; passed into every task payload so sub-scenarios
        # can be resolved without touching the DB during execution.
        registry = _build_scenario_registry(scenarios, templates)

        await repo.update_campaign_status(db, campaign_id, "running")
        await db.commit()

    task_ids: list[str] = []

    # DF-007: Resolve per-device account vars outside the task executor (async-safe).
    # We detect the platform from campaign variables or default to "facebook".
    campaign_platform: str = (campaign.variables or {}).get("__PLATFORM__", "facebook")

    async with AsyncSessionLocal() as account_db:
        device_account_vars: Dict[str, Dict[str, Any]] = {}
        for d in devices:
            device_account_vars[d.id] = await _get_device_account_vars(
                d.id, campaign_platform, account_db
            )

    if scenarios:
        for d in devices:
            acct_vars = device_account_vars.get(d.id, {})
            for scen in scenarios:
                if not scen.steps:
                    continue
                payload = {
                    "instructions": scen.instructions or "",
                    "steps": scen.steps,
                    "variables": {**(scen.variables or {}), **acct_vars},
                    "_campaign_vars": campaign.variables or {},
                    "_scenario_registry": registry,
                }
                task = Task(
                    fn=lambda dev: None,  # placeholder, replaced below
                    priority=5,
                    target=d.serial,
                    timeout=300,
                    max_retries=1,
                    name=f"campaign:{campaign_id}:scenario:{scen.id}",
                )
                task.fn = make_scenario_task(payload, cancel_event=task.cancel_event)
                queue.put(task)
                task_ids.append(task.id)
    elif isinstance(legacy_scenario, dict) and legacy_scenario.get("steps"):
        for d in devices:
            acct_vars = device_account_vars.get(d.id, {})
            legacy_payload = {
                **legacy_scenario,
                "variables": {
                    **(legacy_scenario.get("variables") or {}),
                    **acct_vars,
                },
                "_campaign_vars": campaign.variables or {},
                "_scenario_registry": registry,
            }
            task = Task(
                fn=lambda dev: None,
                priority=5,
                target=d.serial,
                timeout=300,
                max_retries=1,
                name=f"campaign:{campaign_id}:scenario",
            )
            task.fn = make_scenario_task(legacy_payload, cancel_event=task.cancel_event)
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
        "execution_engine": "task_queue",
        "engine": "task_queue",
    }, 200


async def enqueue_campaign_run_temporal(
    campaign_id: str,
    temporal_client,
    temporal_config=None,
) -> Tuple[Dict[str, Any], int]:
   
    from temporal.shared import ScenarioInput, TASK_QUEUE_NAME
    from temporal.workflows import ScenarioWorkflow
    from db.crud.scenario_template import list_templates
    from db.crud.device_group import list_group_devices

    async with AsyncSessionLocal() as db:
        campaign = await repo.get_campaign(db, campaign_id)
        if not campaign:
            return {"error": "Campaign not found"}, 404

        target_group_id = getattr(campaign, "target_group_id", None)
        if target_group_id:
            devices = await list_group_devices(db, target_group_id)
        else:
            devices = await repo.list_campaign_devices(db, campaign_id)

        if not devices:
            return {"error": "Campaign has no devices"}, 400

        scenarios = await repo.list_scenarios(db, campaign_id)
        templates = await list_templates(db)
        legacy_scenario: dict = campaign.scenario or {}

        registry = _build_scenario_registry(scenarios, templates)
        await repo.update_campaign_status(db, campaign_id, "running")
        await db.commit()

    # Resolve per-device account vars
    campaign_platform: str = (campaign.variables or {}).get("__PLATFORM__", "facebook")
    async with AsyncSessionLocal() as account_db:
        device_account_vars: Dict[str, Dict[str, Any]] = {}
        for d in devices:
            device_account_vars[d.id] = await _get_device_account_vars(
                d.id, campaign_platform, account_db
            )

    task_queue = TASK_QUEUE_NAME
    if temporal_config:
        task_queue = temporal_config.task_queue or task_queue

    workflow_ids: list[str] = []

    if scenarios:
        for d in devices:
            acct_vars = device_account_vars.get(d.id, {})
            for scen in scenarios:
                if not scen.steps:
                    continue
                wf_id = f"campaign:{campaign_id}:device:{d.serial}:scenario:{scen.id}"
                try:
                    await temporal_client.start_workflow(
                        ScenarioWorkflow.run,
                        ScenarioInput(
                            campaign_id=campaign_id,
                            device_serial=d.serial,
                            steps=scen.steps,
                            variables={**(scen.variables or {}), **acct_vars},
                            campaign_vars=campaign.variables or {},
                            scenario_registry=registry,
                        ),
                        id=wf_id,
                        task_queue=task_queue,
                    )
                    workflow_ids.append(wf_id)
                except Exception as exc:
                    log.error("Failed to start workflow %s: %s", wf_id, exc)
    elif isinstance(legacy_scenario, dict) and legacy_scenario.get("steps"):
        for d in devices:
            acct_vars = device_account_vars.get(d.id, {})
            wf_id = f"campaign:{campaign_id}:device:{d.serial}:scenario:legacy"
            try:
                await temporal_client.start_workflow(
                    ScenarioWorkflow.run,
                    ScenarioInput(
                        campaign_id=campaign_id,
                        device_serial=d.serial,
                        steps=legacy_scenario.get("steps", []),
                        variables={
                            **(legacy_scenario.get("variables") or {}),
                            **acct_vars,
                        },
                        campaign_vars=campaign.variables or {},
                        scenario_registry=registry,
                    ),
                    id=wf_id,
                    task_queue=task_queue,
                )
                workflow_ids.append(wf_id)
            except Exception as exc:
                log.error("Failed to start workflow %s: %s", wf_id, exc)

    return {
        "id": campaign_id,
        "status": "running",
        "device_serials": [d.serial for d in devices],
        "workflow_ids": workflow_ids,
        "scenarios_count": len(scenarios),
        "execution_engine": "temporal",
        "engine": "temporal",
    }, 200
