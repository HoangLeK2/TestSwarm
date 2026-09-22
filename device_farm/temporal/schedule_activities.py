"""
temporal/schedule_activities.py — Temporal activities for schedule execution (DF-008).

Activities interact with DB and dispatch systems.
They are non-deterministic (I/O, randomness) so they live here, not in the workflow.
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from temporalio import activity

from temporal.schedule_shared import ScheduleDispatchResult

log = logging.getLogger(__name__)


def _parse_scheduled_for(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@asynccontextmanager
async def _schedule_tenant_db(schedule_id: str):
    """Activity DB session with tenant context resolved from schedule_id."""
    from db.crud.schedule import lookup_schedule_org_id
    from db.database import activity_session
    from tenancy.context import tenant_context

    async with activity_session() as db:
        org_id = await lookup_schedule_org_id(db, schedule_id)
        if not org_id:
            raise ValueError(f"Schedule {schedule_id!r} not found")
        with tenant_context(org_id):
            yield db, org_id


@asynccontextmanager
async def _tenant_scope_for_config(cfg: dict[str, Any]):
    """Tenant context for dispatch using org_id from config or schedule lookup."""
    from db.crud.schedule import lookup_schedule_org_id
    from db.database import activity_session
    from tenancy.context import tenant_context

    org_id = cfg.get("org_id")
    if org_id:
        with tenant_context(org_id):
            yield
        return
    schedule_id = cfg.get("id")
    if not schedule_id:
        raise ValueError("Schedule config missing id")
    async with activity_session() as db:
        org_id = await lookup_schedule_org_id(db, schedule_id)
        if not org_id:
            raise ValueError(f"Schedule {schedule_id!r} not found")
        with tenant_context(org_id):
            yield


# Injected by worker startup — same pattern as DeviceActivities
_queue_ref = None
_manager_ref = None
_temporal_client_ref = None
_temporal_config_ref = None


def set_scheduler_deps(queue, manager, temporal_client=None, temporal_config=None) -> None:
    """Called by worker startup to inject runtime dependencies."""
    global _queue_ref, _manager_ref, _temporal_client_ref, _temporal_config_ref
    _queue_ref = queue
    _manager_ref = manager
    _temporal_client_ref = temporal_client
    _temporal_config_ref = temporal_config


class ScheduleActivities:
    """
    Temporal activity methods for scheduled run execution.

    Design principles:
    - Each activity is idempotent where possible (safe to retry)
    - DB operations use AsyncSessionLocal (own connection per activity)
    - Dispatch delegates to existing campaign_dispatch service
    """

    def __init__(
        self,
        *,
        queue=None,
        manager=None,
        temporal_client=None,
        temporal_config=None,
    ) -> None:
        # Workers polling the same queue must all register these activities.
        # Keep runtime dependencies on the activity instance so each worker
        # uses the Temporal client bound to its own asyncio event loop.
        self._queue = queue if queue is not None else _queue_ref
        self._manager = manager if manager is not None else _manager_ref
        self._temporal_client = (
            temporal_client if temporal_client is not None else _temporal_client_ref
        )
        self._temporal_config = (
            temporal_config if temporal_config is not None else _temporal_config_ref
        )

    @activity.defn
    async def load_schedule(self, schedule_id: str) -> dict[str, Any]:
        """Load schedule config from DB. Returns serializable dict."""
        from db.crud.schedule import get_schedule

        activity.heartbeat("load_schedule")
        async with _schedule_tenant_db(schedule_id) as (db, _org_id):
            schedule = await get_schedule(db, schedule_id)
            if schedule is None:
                raise ValueError(f"Schedule {schedule_id!r} not found")
            return {
                "id": schedule.id,
                "name": schedule.name,
                "target_type": schedule.target_type,
                "target_id": schedule.target_id,
                "inline_steps": schedule.inline_steps,
                "inline_variables": schedule.inline_variables or {},
                "user_id": str(schedule.user_id) if schedule.user_id else None,
                "device_group_id": schedule.device_group_id,
                "device_serials": getattr(schedule, "device_serials", []) or [],
                "filter_state": schedule.filter_state,
                "filter_model": schedule.filter_model,
                "max_devices": schedule.max_devices,
                "cron_expression": schedule.cron_expression,
                "timezone": schedule.timezone,
                "schedule_kind": getattr(schedule, "schedule_kind", "cron"),
                "run_at": getattr(schedule, "run_at", None),
                "skip_dates": getattr(schedule, "skip_dates", []) or [],
                "skip_windows": getattr(schedule, "skip_windows", []) or [],
                "misfire_policy": getattr(schedule, "misfire_policy", "skip"),
                "random_delay_min": schedule.random_delay_min,
                "random_delay_max": schedule.random_delay_max,
                "stagger_devices": schedule.stagger_devices,
                "stagger_interval_seconds": schedule.stagger_interval_seconds,
                "is_enabled": schedule.is_enabled,
                "org_id": schedule.org_id,
            }

    @activity.defn
    async def create_run_record(
        self, schedule_id: str, scheduled_for: str | None = None
    ) -> str:
        """Create a ScheduleRun record and return its ID."""
        from db.crud.schedule import create_schedule_run

        activity.heartbeat("create_run_record")
        scheduled_at = _parse_scheduled_for(scheduled_for) or datetime.now(timezone.utc)
        async with _schedule_tenant_db(schedule_id) as (db, org_id):
            run = await create_schedule_run(
                db,
                schedule_id=schedule_id,
                status="pending",
                trigger_source="temporal",
                scheduled_at=scheduled_at,
                org_id=org_id,
            )
            await db.commit()
            return run.id

    @activity.defn
    async def dispatch_schedule(
        self, schedule_config: dict[str, Any], run_id: str
    ) -> ScheduleDispatchResult:
        """
        Dispatch the scheduled workload to devices.

        Handles three target_types:
        - campaign: delegates to enqueue_campaign_run_temporal (Temporal workflow)
        - template: resolves template steps then dispatches as fleet (TaskQueue)
        - org_scenario: resolves org scenario body then dispatches as fleet
        - fleet: dispatches inline_steps to matching devices (TaskQueue)
        """
        activity.heartbeat("dispatch_start")

        target_type = schedule_config["target_type"]
        stagger = schedule_config.get("stagger_devices", False)
        stagger_interval = int(schedule_config.get("stagger_interval_seconds", 60))

        # NOTE: random delay is applied by ScheduleRunWorkflow via workflow.sleep()
        # before this activity is called. Do NOT add a delay here — it would
        # double the intended jitter (once in the workflow, once in the activity).

        try:
            async with _tenant_scope_for_config(schedule_config):
                if target_type == "campaign":
                    result = await self._dispatch_campaign(
                        schedule_config, stagger, stagger_interval
                    )
                elif target_type == "template":
                    result = await self._dispatch_template(
                        schedule_config, stagger, stagger_interval
                    )
                elif target_type == "org_scenario":
                    result = await self._dispatch_org_scenario(
                        schedule_config, stagger, stagger_interval
                    )
                elif target_type == "fleet":
                    result = await self._dispatch_fleet(
                        schedule_config, stagger, stagger_interval
                    )
                else:
                    return ScheduleDispatchResult(
                        run_id=run_id,
                        error=f"Unknown target_type: {target_type!r}",
                    )

            return ScheduleDispatchResult(
                run_id=run_id,
                devices_dispatched=result.get("devices_dispatched", 0),
                task_ids=result.get("task_ids", []),
                workflow_ids=result.get("workflow_ids", []),
            )
        except Exception as exc:
            log.error("[schedule:%s] dispatch failed: %s", schedule_config["id"], exc)
            return ScheduleDispatchResult(run_id=run_id, error=str(exc))

    async def _dispatch_campaign(
        self,
        cfg: dict[str, Any],
        stagger: bool,
        stagger_interval: int,
    ) -> dict[str, Any]:
        """Dispatch a campaign via Temporal.

        NOTE: stagger/stagger_interval are not applied here — Temporal workflows
        start immediately and stagger is not supported for campaign dispatch.
        Stagger only applies to fleet/template dispatch (TaskQueue path).
        To stagger campaign devices, implement delay steps at the start of the
        scenario itself or use the workflow sleep mechanism.
        """
        target_id = cfg.get("target_id")
        if not target_id:
            raise ValueError("campaign target_type requires target_id")

        temporal_client = self._temporal_client
        if temporal_client is None:
            raise RuntimeError(
                f"Temporal is required for campaign dispatch (campaign_id={target_id!r}). "
                "Ensure temporal.enabled=true and the Temporal server is reachable."
            )

        from db import crud as legacy_repo
        from db.crud import campaign_entity as campaign_repo
        from db.crud.execution import get_execution
        from db.database import activity_session
        from services.campaign.dispatcher import CampaignDispatchError, dispatch_campaign
        from services.campaign.execution_runtime import (
            runtime_start_failure_message,
            start_execution_runtime,
        )

        async with activity_session() as db:
            campaign = await campaign_repo.get_campaign_entity(db, target_id)
            if campaign is None:
                raise RuntimeError("Campaign not found")

            org_id = str(cfg.get("org_id") or campaign.org_id or "")
            actor_user_id = str(
                cfg.get("user_id")
                or campaign.created_by
                or campaign.user_id
                or "system"
            )
            if not org_id:
                raise RuntimeError("Campaign has no organization")

            device_ids: list[str] | None = None
            device_group_ids: list[str] | None = None
            schedule_serials = [
                str(serial).strip()
                for serial in (cfg.get("device_serials") or [])
                if str(serial).strip()
            ]
            if schedule_serials:
                from db.crud.device import list_devices_by_serial_aliases

                devices = await list_devices_by_serial_aliases(db, schedule_serials)
                device_ids = [str(device.id) for device in devices]
                max_devices = cfg.get("max_devices")
                if max_devices:
                    device_ids = device_ids[: int(max_devices)]
            elif cfg.get("device_group_id"):
                device_group_ids = [str(cfg["device_group_id"])]
            elif campaign.target_group_id:
                device_group_ids = [str(campaign.target_group_id)]
            else:
                devices = await legacy_repo.list_campaign_devices(db, target_id)
                device_ids = [str(device.id) for device in devices]

            try:
                fan_out = await dispatch_campaign(
                    db,
                    campaign_id=target_id,
                    org_id=org_id,
                    actor_user_id=actor_user_id,
                    device_ids=device_ids,
                    device_group_ids=device_group_ids,
                    dispatch_strategy="parallel",
                    allow_partial=False,
                    require_online=True,
                )
            except CampaignDispatchError as exc:
                raise RuntimeError(str(exc)) from exc

            runtime_stats = await start_execution_runtime(
                db,
                fan_out=fan_out,
                campaign=campaign,
                org_id=org_id,
                actor_user_id=actor_user_id,
                temporal_client=temporal_client,
                temporal_config=self._temporal_config,
                manager=self._manager,
            )
            workflow_ids: list[str] = []
            execution_ids: list[str] = []
            for view in fan_out.executions:
                execution_ids.append(view.execution_id)
                execution = await get_execution(db, view.execution_id)
                meta = execution.meta if execution else {}
                workflow_id = (meta or {}).get("workflow_id")
                if workflow_id:
                    workflow_ids.append(str(workflow_id))
            await db.commit()

        started_count = int(runtime_stats.get("temporal", 0) or 0) + int(
            runtime_stats.get("fallback", 0) or 0
        )
        if started_count <= 0:
            raise RuntimeError(runtime_start_failure_message(fan_out, target_id))

        return {
            "devices_dispatched": started_count,
            "workflow_ids": workflow_ids,
            "execution_id": execution_ids[0] if execution_ids else None,
        }

    async def _dispatch_template(
        self,
        cfg: dict[str, Any],
        stagger: bool,
        stagger_interval: int,
    ) -> dict[str, Any]:
        """Resolve scenario template then dispatch as fleet."""
        from db.database import activity_session as AsyncSessionLocal
        from db.models.scenario_template import ScenarioTemplate
        from sqlalchemy import select

        target_id = cfg.get("target_id")
        if not target_id:
            raise ValueError("template target_type requires target_id")

        async with AsyncSessionLocal() as db:
            result_q = await db.execute(
                select(ScenarioTemplate).where(ScenarioTemplate.id == target_id)
            )
            template = result_q.scalar_one_or_none()

        if template is None:
            raise ValueError(f"ScenarioTemplate {target_id!r} not found")

        fleet_cfg = {**cfg, "inline_steps": template.steps, "inline_variables": template.variables or {}}
        return await self._dispatch_fleet(fleet_cfg, stagger, stagger_interval)

    async def _dispatch_org_scenario(
        self,
        cfg: dict[str, Any],
        stagger: bool,
        stagger_interval: int,
    ) -> dict[str, Any]:
        """Resolve org scenario body then dispatch as fleet."""
        from db.database import activity_session
        from services.scheduler import _resolve_org_scenario_fleet_config

        async with activity_session() as db:
            fleet_cfg = await _resolve_org_scenario_fleet_config(db, cfg)
        return await self._dispatch_fleet(fleet_cfg, stagger, stagger_interval)

    async def _dispatch_fleet(
        self,
        cfg: dict[str, Any],
        stagger: bool,
        stagger_interval: int,
    ) -> dict[str, Any]:
        """Dispatch inline steps to a filtered set of devices."""
        from db.database import activity_session as AsyncSessionLocal
        from db.crud.scenario_template import list_templates
        from services.campaign_dispatch import _build_scenario_registry
        from runtime.core import Task
        from tasks.scenario_task import make_scenario_task

        steps = cfg.get("inline_steps") or []
        if not steps:
            raise ValueError("fleet dispatch requires inline_steps")

        variables = cfg.get("inline_variables") or {}
        device_group_id = cfg.get("device_group_id")
        device_serials = cfg.get("device_serials") or []
        filter_state = cfg.get("filter_state", "READY")
        filter_model = cfg.get("filter_model")
        max_devices = cfg.get("max_devices")

        # Resolve devices — async to avoid event-loop conflicts with asyncpg.
        devices = await _resolve_fleet_devices(
            device_group_id=device_group_id,
            device_serials=device_serials,
            filter_state=filter_state,
            filter_model=filter_model,
            max_devices=max_devices,
            org_id=cfg.get("org_id"),
            manager=self._manager,
        )

        if not devices:
            raise ValueError("No READY devices matching filter")

        async with AsyncSessionLocal() as db:
            templates = await list_templates(db)

        registry = _build_scenario_registry([], templates)
        extra_registry = cfg.get("_scenario_registry")
        if isinstance(extra_registry, dict):
            for key in ("by_id", "by_campaign_name", "by_template_name"):
                values = extra_registry.get(key)
                if isinstance(values, dict):
                    registry.setdefault(key, {}).update(values)

        queue = self._queue
        if queue is None:
            raise RuntimeError("No task queue available")

        task_ids: list[str] = []
        campaign_vars: dict[str, Any] = {}
        user_id = cfg.get("user_id")
        if user_id:
            campaign_vars["__USER_ID__"] = str(user_id)
        for i, device in enumerate(devices):
            activity.heartbeat(f"dispatch_device:{i}:{device.serial}")
            delay = i * stagger_interval if stagger else 0
            payload = {
                "steps": steps,
                "variables": variables,
                "_campaign_vars": campaign_vars,
                "_scenario_registry": registry,
            }
            task = Task(
                fn=lambda dev: None,
                priority=5,
                target=device.serial,
                timeout=300,
                max_retries=1,
                name=f"schedule:{cfg['id']}:device:{device.serial}",
            )
            task.fn = _make_staggered_task(
                make_scenario_task(payload, cancel_event=task.cancel_event),
                delay_seconds=float(delay),
            )
            queue.put(task)
            task_ids.append(task.id)

        return {
            "devices_dispatched": len(devices),
            "task_ids": task_ids,
        }

    @activity.defn
    async def finalize_schedule_run(
        self,
        run_id: str,
        schedule_id: str,
        dispatch_result: ScheduleDispatchResult | dict[str, Any],
        cron_expression: str,
        timezone_name: str,
        scheduled_for: str | None = None,
    ) -> None:
        """
        Update ScheduleRun status + schedule metadata (last_run_at, next_run_at, run_count).

        Idempotent: safe to call multiple times.
        """
        from services.scheduler import finalize_schedule_run_record

        activity.heartbeat("finalize_run")
        # Capture finalization time once for the run's actual finish. Use the
        # scheduled fire time as the cursor for the next cron occurrence so a
        # slow campaign dispatch does not drift future runs.
        finished_at = datetime.now(timezone.utc)
        scheduled_at = _parse_scheduled_for(scheduled_for)
        if isinstance(dispatch_result, dict):
            normalized = ScheduleDispatchResult(
                run_id=str(dispatch_result.get("run_id", run_id)),
                devices_dispatched=int(dispatch_result.get("devices_dispatched", 0) or 0),
                task_ids=list(dispatch_result.get("task_ids", []) or []),
                workflow_ids=list(dispatch_result.get("workflow_ids", []) or []),
                error=dispatch_result.get("error"),
            )
        else:
            normalized = dispatch_result
        status = "failed" if normalized.error else "completed"

        async with _schedule_tenant_db(schedule_id) as (db, org_id):
            await finalize_schedule_run_record(
                db,
                run_id=run_id,
                schedule_id=schedule_id,
                status=status,
                finished_at=finished_at,
                dispatch_result={
                    "devices_dispatched": normalized.devices_dispatched,
                    "task_ids": normalized.task_ids,
                    "workflow_ids": normalized.workflow_ids,
                },
                cron_expression=cron_expression,
                timezone_name=timezone_name,
                scheduled_for=scheduled_at,
                organization_id=org_id,
                error_code="DISPATCH_FAILED" if normalized.error else None,
                error_message=normalized.error,
            )
            await db.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _resolve_fleet_devices(
    *,
    device_group_id: str | None,
    filter_state: str,
    filter_model: str | None,
    max_devices: int | None,
    org_id: str | None = None,
    device_serials: list[str] | None = None,
    manager=None,
):
    """Resolve devices from DeviceManager (async to avoid asyncpg event-loop conflicts).

    An explicit `device_serials` list wins over `device_group_id`: it replaces the
    candidate set, then the usual state/model/max filters still apply.
    """
    manager = manager if manager is not None else _manager_ref
    if manager is None:
        return []

    if device_serials:
        wanted = set(device_serials)
        devices = [
            c for c in manager.all_devices()
            if c.serial in wanted and c.state == filter_state
        ]
    elif device_group_id:
        from db.database import activity_session
        from db.crud.device_group import list_group_devices
        from tenancy.context import get_current_org_id, tenant_context

        try:
            async with activity_session() as db:
                scope_org = get_current_org_id() or org_id
                if scope_org:
                    with tenant_context(scope_org):
                        db_devices = await list_group_devices(db, device_group_id)
                else:
                    db_devices = await list_group_devices(db, device_group_id)
        except Exception:
            db_devices = []

        serials = {d.serial for d in db_devices}
        devices = [
            c for c in manager.all_devices()
            if c.serial in serials and c.state == filter_state
        ]
    else:
        devices = [
            c for c in manager.all_devices() if c.state == filter_state
        ]

    if filter_model:
        devices = [d for d in devices if d.model == filter_model]

    if max_devices and len(devices) > max_devices:
        devices = devices[:max_devices]

    return devices


def _make_staggered_task(fn, delay_seconds: float):
    """Wrap a task function with an initial sleep for device stagger.

    Uses time.sleep (blocking) intentionally: this wrapper is executed by the
    TaskQueue thread pool, NOT on the asyncio event loop. Using asyncio.sleep here
    would require the wrapper to be async, which is incompatible with the sync
    Task.fn contract.
    """
    if delay_seconds <= 0:
        return fn

    def _wrapper(device):
        time.sleep(delay_seconds)
        return fn(device)

    return _wrapper


def _compute_next_run(cron_expression: str, timezone_name: str, base: datetime) -> datetime | None:
    """Compute next_run_at using croniter. Returns None if croniter not available."""
    try:
        from croniter import croniter
        import pytz

        tz = pytz.timezone(timezone_name)
        base_local = base.astimezone(tz)
        cron = croniter(cron_expression, base_local)
        next_dt = cron.get_next(datetime)
        return next_dt.astimezone(timezone.utc)
    except Exception as exc:
        log.warning("Could not compute next_run_at: %s", exc)
        return None
