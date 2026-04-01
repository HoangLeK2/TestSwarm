
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Tuple

from db.database import AsyncSessionLocal
from db import crud as repo

log = logging.getLogger(__name__)

# Allowed characters for campaign_id embedded in Temporal workflow IDs.
# Colons (:) are reserved as segment separators; quotes/backslashes risk
# injection into Temporal query string filter expressions.
_CAMPAIGN_ID_RE = re.compile(r'^[\w\-]{1,128}$')


async def _get_device_account_vars(
    device_id: str,
    platform: str,
    db,
) -> Dict[str, Any]:
  
    from db.crud.account import get_primary_account_for_device

    account = await get_primary_account_for_device(db, device_id, platform)
    if not account:
        return {}
    return {
        "__ACCOUNT_ID__": str(account.id),
        "__ACCOUNT_USERNAME__": account.username,
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


async def enqueue_campaign_run_temporal(
    campaign_id: str,
    temporal_client,
    temporal_config=None,
    *,
    device_serials_override: list[str] | None = None,
) -> Tuple[Dict[str, Any], int]:
    """Start Temporal workflows for a campaign.

    device_serials_override: if provided, use these serials instead of the
    campaign's assigned device list. Useful for live-filter runs (fleet-style).
    """
    if not campaign_id or not _CAMPAIGN_ID_RE.match(campaign_id):
        return {
            "error": (
                f"Invalid campaign_id {campaign_id!r}: must be 1-128 alphanumeric, "
                "hyphen, or underscore characters"
            )
        }, 400

    from temporal.shared import ScenarioInput, TASK_QUEUE_NAME
    from temporal.workflows import ScenarioWorkflow
    from db.crud.scenario_template import list_templates
    from db.crud.device_group import list_group_devices

    async with AsyncSessionLocal() as db:
        campaign = await repo.get_campaign(db, campaign_id)
        if not campaign:
            return {"error": "Campaign not found"}, 404

        if device_serials_override is not None:
            # Live-filter mode: look up device rows by serial so we have .id for account vars
            from db.crud.device import get_device_by_serial
            devices = []
            for serial in device_serials_override:
                d = await get_device_by_serial(db, serial)
                if d:
                    devices.append(d)
            if not devices:
                return {"error": "None of the filtered device serials exist in the database"}, 400
        else:
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

        import json as _json
        try:
            _registry_bytes = len(_json.dumps(registry).encode())
            if _registry_bytes > 500_000:  # 500 KB soft warning
                log.warning(
                    "Campaign %s: scenario_registry is %d KB — large registries risk "
                    "exceeding Temporal's 2 MB event payload limit.",
                    campaign_id, _registry_bytes // 1024,
                )
        except Exception:
            pass

        await repo.update_campaign_status(db, campaign_id, "running")
        # Create a CampaignRun record — populated with workflow IDs after dispatch
        from db.crud.campaign_run import create_campaign_run
        run_record = await create_campaign_run(
            db,
            campaign_id=campaign_id,
            device_serials=[d.serial for d in devices],
            workflow_ids=[],
            scenarios_count=len(scenarios),
        )
        run_id = run_record.id
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

    # Detect early: all scenarios have empty steps (misconfiguration, not Temporal failure)
    if scenarios and all(not s.steps for s in scenarios):
        log.error(
            "Campaign %s: %d scenario(s) found but none have steps — "
            "configure steps before running",
            campaign_id, len(scenarios),
        )
        return {
            "error": (
                f"Campaign has {len(scenarios)} scenario(s) but none contain steps. "
                "Add steps to at least one scenario before running."
            ),
            "campaign_id": campaign_id,
        }, 400

    if scenarios:
        for d in devices:
            acct_vars = device_account_vars.get(d.id, {})
            for scen in scenarios:
                if not scen.steps:
                    continue
                wf_id = f"campaign:{campaign_id}:device:{d.serial}:scenario:{scen.id}"
                try:
                    from temporalio.common import WorkflowIDReusePolicy
                    await temporal_client.start_workflow(
                        ScenarioWorkflow.run,
                        ScenarioInput(
                            campaign_id=campaign_id,
                            device_serial=d.serial,
                            steps=scen.steps,
                            variables={**(scen.variables or {}), **acct_vars},
                            campaign_vars=campaign.variables or {},
                            scenario_registry=registry,
                            run_id=run_id,
                        ),
                        id=wf_id,
                        task_queue=task_queue,
                        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
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
                        run_id=run_id,
                    ),
                    id=wf_id,
                    task_queue=task_queue,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                )
                workflow_ids.append(wf_id)
            except Exception as exc:
                log.error("Failed to start workflow %s: %s", wf_id, exc)

    expected_workflows = len(devices) * (len(scenarios) or 1)
    if expected_workflows > 0 and not workflow_ids:
        log.error(
            "Campaign %s: all %d workflow start(s) failed — no devices are running",
            campaign_id, expected_workflows,
        )
        # Mark run as failed
        from db.crud.campaign_run import finish_campaign_run
        async with AsyncSessionLocal() as db:
            await finish_campaign_run(db, run_id, status="failed")
            await db.commit()
        return {
            "error": "Failed to start any workflows — check Temporal server connectivity",
            "campaign_id": campaign_id,
        }, 500

    # Update run record with actual workflow IDs
    from sqlalchemy import update as sa_update
    from db.models.campaign import CampaignRun
    async with AsyncSessionLocal() as db:
        await db.execute(
            sa_update(CampaignRun)
            .where(CampaignRun.id == run_id)
            .values(workflow_ids=workflow_ids)
        )
        await db.commit()

    return {
        "id": campaign_id,
        "run_id": run_id,
        "status": "running",
        "device_serials": [d.serial for d in devices],
        "workflow_ids": workflow_ids,
        "scenarios_count": len(scenarios),
        "execution_engine": "temporal",
        "engine": "temporal",
    }, 200
