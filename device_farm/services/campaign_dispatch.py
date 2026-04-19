
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Tuple

from db.database import AsyncSessionLocal
from db import crud as repo
from db.crud.default_scenario import DEVICE_CONTEXT_KEY

log = logging.getLogger(__name__)

# Allowed characters for campaign_id embedded in Temporal workflow IDs.
# Colons (:) are reserved as segment separators; quotes/backslashes risk
# injection into Temporal query string filter expressions.
_CAMPAIGN_ID_RE = re.compile(r'^[\w\-]{1,128}$')


def _account_to_vars(account) -> Dict[str, Any]:
    """Common ``__ACCOUNT_*`` variable shape injected into scenario runs.

    Password is NOT included here — Temporal activities resolve it at runtime
    via ``__ACCOUNT_ID__`` so plaintext never hits Temporal's event history.
    """
    return {
        "__ACCOUNT_ID__": str(account.id),
        "__ACCOUNT_USERNAME__": account.username,
        "__ACCOUNT_DISPLAY_NAME__": account.display_name or "",
        "__ACCOUNT_PLATFORM__": account.platform,
    }


async def _get_device_account_vars(
    device_id: str,
    platform: str,
    db,
) -> Dict[str, Any]:
    from db.crud.account import get_primary_account_for_device

    account = await get_primary_account_for_device(db, device_id, platform)
    if not account:
        return {}
    return _account_to_vars(account)


async def _build_per_scenario_device_vars(
    db,
    scenarios: list,
    devices: list,
    *,
    platform: str,
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Pre-compute ``{scenario_id: {device_id: __ACCOUNT_* vars}}`` for a dispatch.

    Scenarios bound to an ``account_group_id`` get a single batch pick so
    every device receives a distinct account from the pool. Unbound
    scenarios fall back to the primary-per-device lookup (legacy path).

    This avoids N*M round-trips (N devices × M scenarios) by picking once
    per scenario. The per-device primary lookup is also cached per device
    so a campaign with K unbound scenarios does not repeat the same query.
    """
    from db.crud.account_group import pick_next_batch

    # Cache primary-account lookups per device — used for unbound scenarios.
    primary_cache: Dict[str, Dict[str, Any]] = {}

    async def _primary_for(device_id: str) -> Dict[str, Any]:
        if device_id in primary_cache:
            return primary_cache[device_id]
        vars_ = await _get_device_account_vars(device_id, platform, db)
        primary_cache[device_id] = vars_
        return vars_

    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for scen in scenarios:
        per_device: Dict[str, Dict[str, Any]] = {}
        group_id = getattr(scen, "account_group_id", None)
        if group_id:
            accounts = await pick_next_batch(db, group_id, len(devices))
            granted = len(accounts)
            log.info(
                "account_group.pick scenario=%s group=%s requested=%d granted=%d",
                scen.id, group_id, len(devices), granted,
            )
            for idx, device in enumerate(devices):
                if idx < granted:
                    per_device[device.id] = _account_to_vars(accounts[idx])
                else:
                    # Group exhausted for this device — leave vars empty so the
                    # scenario can detect and abort if it references __ACCOUNT_*.
                    per_device[device.id] = {}
        else:
            for device in devices:
                per_device[device.id] = await _primary_for(device.id)
        out[scen.id] = per_device
    return out


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
        _vars = dict(s.variables or {})
        _vars.pop(DEVICE_CONTEXT_KEY, None)
        entry: Dict[str, Any] = {
            "steps": s.steps or [],
            "variables": _vars,
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
        if not scenarios:
            return {
                "error": "Campaign has no scenarios. Add a scenario before running.",
                "campaign_id": campaign_id,
            }, 400
        if all(not s.steps for s in scenarios):
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

        templates = await list_templates(db)

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

        # Create Execution record (single source of truth for all run types)
        from db.crud.execution import create_execution, add_device_to_execution
        execution_record = await create_execution(
            db,
            run_type="campaign_run",
            campaign_id=campaign_id,
            user_id=getattr(campaign, "user_id", None),
            status="running",
            meta={"scenarios_count": len(scenarios)},
        )
        execution_id = execution_record.id
        for d in devices:
            await add_device_to_execution(db, execution_id, d.id)

        await db.commit()

    # Resolve per-(scenario, device) account vars. Scenarios bound to an
    # account group get a rotated pick; unbound scenarios use the device's
    # primary account (existing behavior).
    campaign_platform: str = (campaign.variables or {}).get("__PLATFORM__", "facebook")
    async with AsyncSessionLocal() as account_db:
        per_scenario_device_vars = await _build_per_scenario_device_vars(
            account_db,
            scenarios=scenarios,
            devices=devices,
            platform=campaign_platform,
        )
        # Commit so rotation cursor/last_used_at updates land before workflow
        # start — if a later dispatch happens, it must see the advanced cursor.
        await account_db.commit()

    task_queue = TASK_QUEUE_NAME
    if temporal_config:
        task_queue = temporal_config.task_queue or task_queue

    workflow_ids: list[str] = []

    for d in devices:
        for scen in scenarios:
            if not scen.steps:
                continue
            acct_vars = per_scenario_device_vars.get(scen.id, {}).get(d.id, {})
            wf_id = f"campaign:{campaign_id}:device:{d.serial}:scenario:{scen.id}"
            try:
                from temporalio.common import WorkflowIDReusePolicy
                _sc_vars = dict(scen.variables or {})
                _sc_vars.pop(DEVICE_CONTEXT_KEY, None)
                _campaign_vars = dict(campaign.variables or {})
                if campaign.user_id:
                    _campaign_vars["__USER_ID__"] = str(campaign.user_id)
                await temporal_client.start_workflow(
                    ScenarioWorkflow.run,
                    ScenarioInput(
                        campaign_id=campaign_id,
                        device_serial=d.serial,
                        steps=scen.steps,
                        variables={**_sc_vars, **acct_vars},
                        campaign_vars=_campaign_vars,
                        scenario_registry=registry,
                        run_id=execution_id,
                        execution_id=execution_id,
                    ),
                    id=wf_id,
                    task_queue=task_queue,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                )
                workflow_ids.append(wf_id)
            except Exception as exc:
                log.error("Failed to start workflow %s: %s", wf_id, exc)

    scen_with_steps = sum(1 for s in scenarios if s.steps)
    expected_workflows = len(devices) * scen_with_steps
    if expected_workflows > 0 and not workflow_ids:
        log.error(
            "Campaign %s: all %d workflow start(s) failed — no devices are running",
            campaign_id, expected_workflows,
        )
        # Mark execution as failed and reset campaign out of running state
        from db.crud.execution import finish_execution
        async with AsyncSessionLocal() as db:
            await finish_execution(db, execution_id, status="failed")
            await repo.update_campaign_status(db, campaign_id, "idle")
            await db.commit()
        return {
            "error": "Failed to start any workflows — check Temporal server connectivity",
            "campaign_id": campaign_id,
        }, 500

    # Store workflow IDs in execution.meta
    from db.crud.execution import update_execution
    async with AsyncSessionLocal() as db:
        await update_execution(
            db, execution_id,
            meta={**execution_record.meta, "workflow_ids": workflow_ids},
        )
        await db.commit()

    return {
        "id": campaign_id,
        "execution_id": execution_id,
        "status": "running",
        "device_serials": [d.serial for d in devices],
        "workflow_ids": workflow_ids,
        "scenarios_count": len(scenarios),
        "execution_engine": "temporal",
        "engine": "temporal",
    }, 200
