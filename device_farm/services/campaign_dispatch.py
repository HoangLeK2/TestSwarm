
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from db.database import activity_session
from db import crud as repo
from db.crud.default_scenario import DEVICE_CONTEXT_KEY
from db.crud.scenario_device_variable import (
    get_scenario_device_variables as _get_scenario_device_variables_crud,
    get_scenario_device_variables_bulk,
)
from common.variable_resolver import _VAR_PATTERN, normalize_device_vars

log = logging.getLogger(__name__)

# Allowed characters for campaign_id embedded in Temporal workflow IDs.
# Colons (:) are reserved as segment separators; quotes/backslashes risk
# injection into Temporal query string filter expressions.
_CAMPAIGN_ID_RE = re.compile(r'^[\w\-]{1,128}$')


def _offline_dismiss_minutes() -> int:
    raw = os.environ.get("DEVICE_FARM_DLQ_OFFLINE_DISMISS_MINUTES", "5")
    try:
        return max(1, min(10_080, int(raw)))
    except ValueError:
        return 5


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
        if isinstance(group_id, str) and group_id:
            accounts = await pick_next_batch(db, group_id, len(devices))
            granted = len(accounts)
            log.info(
                "account_group.pick scenario=%s group=%s requested=%d granted=%d",
                scen.id, group_id, len(devices), granted,
            )
            from services.account_event_recorder import get_account_event_recorder

            rec = get_account_event_recorder()
            for idx, device in enumerate(devices):
                if idx < granted:
                    acc = accounts[idx]
                    per_device[device.id] = _account_to_vars(acc)
                    rec.record(
                        account_id=acc.id,
                        event_type="account.picked",
                        platform=acc.platform,
                        entity_type="account_group",
                        entity_id=group_id,
                        device_serial=device.serial,
                        details={"scenario_id": scen.id, "position": idx},
                    )
                else:
                    # Group exhausted for this device — leave vars empty so the
                    # scenario can detect and abort if it references __ACCOUNT_*.
                    per_device[device.id] = {}
        else:
            for device in devices:
                per_device[device.id] = await _primary_for(device.id)
        out[scen.id] = per_device
    return out


async def _build_per_scenario_device_runtime_vars(
    db,
    scenarios: list,
    devices: list,
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    scenario_ids = [s.id for s in scenarios]
    device_ids = [d.id for d in devices]
    bulk = await get_scenario_device_variables_bulk(db, scenario_ids, device_ids)

    # Backward-compatible path: older tests and call sites patch
    # `services.campaign_dispatch.get_scenario_device_variables`. Also, when
    # there are no DB rows at all, bulk will be empty; in that case it is safe
    # to do a minimal per-(scenario,device) lookup to preserve override semantics.
    if not bulk and scenario_ids and device_ids:
        for scen in scenarios:
            for device in devices:
                bulk[(scen.id, device.id)] = await get_scenario_device_variables(
                    db, scen.id, device.id
                )

    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for scen in scenarios:
        per_device: Dict[str, Dict[str, Any]] = {}
        for device in devices:
            raw = bulk.get((scen.id, device.id), {})
            per_device[device.id] = normalize_device_vars(raw)
        out[scen.id] = per_device
    return out


async def get_scenario_device_variables(db, scenario_id: str, device_id: str) -> Dict[str, Any]:
    # Exposed for patching in tests and to keep a stable import surface.
    return await _get_scenario_device_variables_crud(db, scenario_id, device_id)


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


def _build_device_sequence_steps(
    *,
    scenarios: list,
    device,
    slot_idx: int,
    campaign_vars: Dict[str, Any] | None = None,
    per_scenario_device_vars: Dict[str, Dict[str, Dict[str, Any]]],
    per_scenario_device_runtime_vars: Dict[str, Dict[str, Dict[str, Any]]],
    scenario_registry: Dict[str, Any] | None = None,
) -> list[Dict[str, Any]]:
    """Build ordered run_scenario steps for one device.

    A campaign run should fan out by device, not by scenario. Each device gets a
    single workflow whose top-level steps call the campaign scenarios in DB
    order, carrying the per-scenario device/account variables as overrides.
    """
    steps: list[Dict[str, Any]] = []
    campaign_override_vars = {
        key: value
        for key, value in dict(campaign_vars or {}).items()
        if not str(key).startswith("__")
    }
    by_template_name = (scenario_registry or {}).get("by_template_name") or {}
    for scenario_idx, scen in enumerate(scenarios):
        # Some campaigns use ScenarioTemplates (stored separately) and keep
        # Scenario.steps empty. In that case, still include the scenario in the
        # device sequence if a template with the same name exists.
        has_steps = bool(getattr(scen, "steps", None))
        has_template = bool(getattr(scen, "name", "") and (scen.name in by_template_name))
        if not has_steps and not has_template:
            continue
        acct_vars = per_scenario_device_vars.get(scen.id, {}).get(device.id, {})
        device_runtime_vars = (
            per_scenario_device_runtime_vars.get(scen.id, {}).get(device.id, {})
        )
        steps.append({
            "type": "run_scenario",
            "scenario_id": scen.id,
            "scenario_name": scen.name,
            "variables": {
                **campaign_override_vars,
                "DEVICE_INDEX": str(slot_idx),
                "SCENARIO_INDEX": str(scenario_idx),
                **device_runtime_vars,
                **acct_vars,
            },
        })
    return steps


def _scan_variable_refs(value: Any) -> list[str]:
    if isinstance(value, str):
        return list(_VAR_PATTERN.findall(value))
    if isinstance(value, dict):
        refs: list[str] = []
        for item in value.values():
            refs.extend(_scan_variable_refs(item))
        return refs
    if isinstance(value, list):
        refs: list[str] = []
        for item in value:
            refs.extend(_scan_variable_refs(item))
        return refs
    return []


def _resolve_fb_group_device_var_keys(
    scenario: Any,
    token_map: Dict[str, Dict[str, Any]],
) -> list[str]:
    device_var_keys: list[str] = []
    seen: set[str] = set()
    for vars_for_device in token_map.values():
        for key in vars_for_device.keys():
            if key.startswith("__") or key in seen:
                continue
            seen.add(key)
            device_var_keys.append(key)

    device_key_set = set(device_var_keys)
    refs: list[str] = []
    for ref in _scan_variable_refs(getattr(scenario, "steps", None) or []):
        if ref in device_key_set and ref not in refs:
            refs.append(ref)
    if refs:
        return refs

    aliases = [
        key
        for key in ("group_name", "GROUP_NAME", "group")
        if key in device_key_set
    ]
    if aliases:
        return aliases

    if len(device_var_keys) == 1:
        return device_var_keys

    return ["group_name", "GROUP_NAME", "group"]


def _first_non_empty_var(
    vars_for_device: Dict[str, Any],
    keys: list[str],
) -> str:
    for key in keys:
        raw = str(vars_for_device.get(key) or "").strip()
        if raw:
            return raw
    return ""


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

    async with activity_session() as db:
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

        from services.device_liveness import filter_live_devices_for_dispatch

        devices, skipped_devices = await filter_live_devices_for_dispatch(
            db,
            devices,
            offline_after_minutes=_offline_dismiss_minutes(),
        )
        if not devices:
            return {
                "error": "No online devices available for campaign dispatch",
                "campaign_id": campaign_id,
                "skipped_offline_device_serials": [d.serial for d in skipped_devices],
            }, 400

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
            meta={
                "scenarios_count": len(scenarios),
                "org_id": getattr(campaign, "org_id", None),
            },
        )
        execution_id = execution_record.id
        for d in devices:
            await add_device_to_execution(db, execution_id, d.id)

        await db.commit()

    # Resolve per-(scenario, device) account vars. Scenarios bound to an
    # account group get a rotated pick; unbound scenarios use the device's
    # primary account (existing behavior).
    campaign_platform: str = (campaign.variables or {}).get("__PLATFORM__", "facebook")
    async with activity_session() as account_db:
        per_scenario_device_vars = await _build_per_scenario_device_vars(
            account_db,
            scenarios=scenarios,
            devices=devices,
            platform=campaign_platform,
        )
        per_scenario_device_runtime_vars = await _build_per_scenario_device_runtime_vars(
            account_db,
            scenarios=scenarios,
            devices=devices,
        )
        # Commit so rotation cursor/last_used_at updates land before workflow
        # start — if a later dispatch happens, it must see the advanced cursor.
        await account_db.commit()

    from services.account_event_recorder import get_account_event_recorder
    from services.account_manager import start_account_usage

    account_usage_meta: Dict[str, Dict[str, Any]] = {}
    started_accounts: set[str] = set()
    for device in devices:
        acct_id: str | None = None
        platform: str | None = None
        for scen in scenarios:
            vars_ = per_scenario_device_vars.get(scen.id, {}).get(device.id, {})
            aid = vars_.get("__ACCOUNT_ID__")
            if aid:
                acct_id = str(aid)
                platform = str(vars_.get("__ACCOUNT_PLATFORM__") or campaign_platform)
                break
        if not acct_id:
            continue
        now_iso = datetime.now(timezone.utc).isoformat()
        account_usage_meta[device.serial] = {
            "account_id": acct_id,
            "platform": platform,
            "started_at": now_iso,
        }
        if acct_id not in started_accounts:
            started_accounts.add(acct_id)
            await start_account_usage(
                acct_id,
                user_id=str(campaign.user_id) if getattr(campaign, "user_id", None) else None,
                device_serial=device.serial,
                platform=platform,
                entity_type="execution",
                entity_id=execution_id,
            )

    await get_account_event_recorder().flush_all()

    # Guardrail: fb_groups_per_device requires unique per-device group value
    # from scenario_device_variables. Device vars share the same namespace as
    # global vars and override them at dispatch time.
    for scen in scenarios:
        if getattr(scen, "name", "") != "fb_groups_per_device":
            continue
        token_map = per_scenario_device_runtime_vars.get(scen.id, {})
        group_keys = _resolve_fb_group_device_var_keys(scen, token_map)
        missing_serials: list[str] = []
        group_to_serials: dict[str, list[str]] = {}
        for d in devices:
            vars_for_device = token_map.get(d.id, {})
            raw_group = _first_non_empty_var(vars_for_device, group_keys)
            if not raw_group:
                missing_serials.append(d.serial)
                continue
            key = raw_group.lower()
            group_to_serials.setdefault(key, []).append(d.serial)
        duplicate_groups = {
            group: serials for group, serials in group_to_serials.items() if len(serials) > 1
        }
        if missing_serials or duplicate_groups:
            return {
                "error": "Invalid device vars for fb_groups_per_device",
                "scenario_id": scen.id,
                "scenario_name": scen.name,
                "missing_group_devices": missing_serials,
                "duplicate_groups": duplicate_groups,
                "hint": (
                    "Set a unique per-device value for one of "
                    f"{group_keys!r} in scenario device variables and use the same "
                    "variable key in scenario/global variables."
                ),
            }, 400

    task_queue = TASK_QUEUE_NAME
    if temporal_config:
        task_queue = temporal_config.task_queue or task_queue

    workflow_ids: list[str] = []

    _campaign_vars = dict(campaign.variables or {})
    if campaign.user_id:
        _campaign_vars["__USER_ID__"] = str(campaign.user_id)

    for slot_idx, d in enumerate(devices):
        sequence_steps = _build_device_sequence_steps(
            scenarios=scenarios,
            device=d,
            slot_idx=slot_idx,
            campaign_vars=_campaign_vars,
            per_scenario_device_vars=per_scenario_device_vars,
            per_scenario_device_runtime_vars=per_scenario_device_runtime_vars,
            scenario_registry=registry,
        )
        if not sequence_steps:
            continue

        wf_id = f"campaign:{campaign_id}:device:{d.serial}:scenario:__sequence__"
        try:
            from temporalio.common import WorkflowIDReusePolicy
            await temporal_client.start_workflow(
                ScenarioWorkflow.run,
                ScenarioInput(
                    campaign_id=campaign_id,
                    device_serial=d.serial,
                    steps=sequence_steps,
                    variables={},
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
    expected_workflows = len(devices) if scen_with_steps else 0
    if expected_workflows > 0 and not workflow_ids:
        log.error(
            "Campaign %s: all %d workflow start(s) failed — no devices are running",
            campaign_id, expected_workflows,
        )
        # Mark execution as failed and reset campaign out of running state
        from db.crud.execution import finish_execution
        async with activity_session() as db:
            await finish_execution(db, execution_id, status="failed")
            await repo.update_campaign_status(db, campaign_id, "idle")
            await db.commit()
        return {
            "error": "Failed to start any workflows — check Temporal server connectivity",
            "campaign_id": campaign_id,
        }, 500

    # Store workflow IDs in execution.meta
    from db.crud.execution import update_execution
    async with activity_session() as db:
        await update_execution(
            db, execution_id,
            meta={
                **(execution_record.meta or {}),
                "workflow_ids": workflow_ids,
                "scenario_ids": [s.id for s in scenarios if s.steps],
                "execution_mode": "device_sequence",
                "account_usage": account_usage_meta,
                "skipped_offline_device_serials": [d.serial for d in skipped_devices],
            },
        )
        await db.commit()

    return {
        "id": campaign_id,
        "execution_id": execution_id,
        "status": "running",
        "device_serials": [d.serial for d in devices],
        "skipped_offline_device_serials": [d.serial for d in skipped_devices],
        "workflow_ids": workflow_ids,
        "scenarios_count": len(scenarios),
        "execution_engine": "temporal",
        "engine": "temporal",
    }, 200
