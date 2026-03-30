"""
temporal/schedule_activities.py — Temporal activities for schedule execution (DF-008).

Activities interact with DB and dispatch systems.
They are non-deterministic (I/O, randomness) so they live here, not in the workflow.
"""
from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timezone
from typing import Any

from temporalio import activity

from temporal.schedule_shared import ScheduleDispatchResult

log = logging.getLogger(__name__)

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

    @activity.defn
    async def load_schedule(self, schedule_id: str) -> dict[str, Any]:
        """Load schedule config from DB. Returns serializable dict."""
        from db.database import AsyncSessionLocal
        from db.crud.schedule import get_schedule

        activity.heartbeat("load_schedule")
        async with AsyncSessionLocal() as db:
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
                "device_group_id": schedule.device_group_id,
                "filter_state": schedule.filter_state,
                "filter_model": schedule.filter_model,
                "max_devices": schedule.max_devices,
                "cron_expression": schedule.cron_expression,
                "timezone": schedule.timezone,
                "random_delay_min": schedule.random_delay_min,
                "random_delay_max": schedule.random_delay_max,
                "stagger_devices": schedule.stagger_devices,
                "stagger_interval_seconds": schedule.stagger_interval_seconds,
                "is_enabled": schedule.is_enabled,
            }

    @activity.defn
    async def create_run_record(self, schedule_id: str) -> str:
        """Create a ScheduleRun record and return its ID."""
        from db.database import AsyncSessionLocal
        from db.crud.schedule import create_schedule_run

        activity.heartbeat("create_run_record")
        async with AsyncSessionLocal() as db:
            run = await create_schedule_run(db, schedule_id=schedule_id, status="pending")
            await db.commit()
            return run.id

    @activity.defn
    async def dispatch_schedule(
        self, schedule_config: dict[str, Any], run_id: str
    ) -> ScheduleDispatchResult:
        """
        Dispatch the scheduled workload to devices.

        Handles three target_types:
        - campaign: delegates to enqueue_campaign_run / enqueue_campaign_run_temporal
        - template: resolves template steps then dispatches as fleet
        - fleet: dispatches inline_steps to matching devices
        """
        activity.heartbeat("dispatch_start")

        target_type = schedule_config["target_type"]
        stagger = schedule_config.get("stagger_devices", False)
        stagger_interval = int(schedule_config.get("stagger_interval_seconds", 60))

        try:
            if target_type == "campaign":
                result = await self._dispatch_campaign(
                    schedule_config, stagger, stagger_interval
                )
            elif target_type == "template":
                result = await self._dispatch_template(
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
        target_id = cfg.get("target_id")
        if not target_id:
            raise ValueError("campaign target_type requires target_id")

        temporal_client = _temporal_client_ref
        if temporal_client is not None:
            from services.campaign_dispatch import enqueue_campaign_run_temporal
            result, _ = await enqueue_campaign_run_temporal(
                target_id, temporal_client, _temporal_config_ref
            )
        else:
            queue = _queue_ref
            if queue is None:
                raise RuntimeError("No task queue available")
            from services.campaign_dispatch import enqueue_campaign_run
            result, _ = await enqueue_campaign_run(target_id, queue)

        if stagger and result.get("task_ids"):
            _apply_stagger_to_tasks(result["task_ids"], stagger_interval, queue=_queue_ref)

        return {
            "devices_dispatched": len(result.get("device_serials", [])),
            "task_ids": result.get("task_ids", []),
            "workflow_ids": result.get("workflow_ids", []),
        }

    async def _dispatch_template(
        self,
        cfg: dict[str, Any],
        stagger: bool,
        stagger_interval: int,
    ) -> dict[str, Any]:
        """Resolve scenario template then dispatch as fleet."""
        from db.database import AsyncSessionLocal
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

    async def _dispatch_fleet(
        self,
        cfg: dict[str, Any],
        stagger: bool,
        stagger_interval: int,
    ) -> dict[str, Any]:
        """Dispatch inline steps to a filtered set of devices."""
        from db.database import AsyncSessionLocal
        from db.crud.scenario_template import list_templates
        from services.campaign_dispatch import _build_scenario_registry
        from runtime.core import Task
        from tasks.scenario_task import make_scenario_task

        steps = cfg.get("inline_steps") or []
        if not steps:
            raise ValueError("fleet dispatch requires inline_steps")

        variables = cfg.get("inline_variables") or {}
        device_group_id = cfg.get("device_group_id")
        filter_state = cfg.get("filter_state", "READY")
        filter_model = cfg.get("filter_model")
        max_devices = cfg.get("max_devices")

        # Resolve devices
        devices = _resolve_fleet_devices(
            device_group_id=device_group_id,
            filter_state=filter_state,
            filter_model=filter_model,
            max_devices=max_devices,
        )

        if not devices:
            raise ValueError("No READY devices matching filter")

        async with AsyncSessionLocal() as db:
            templates = await list_templates(db)

        registry = _build_scenario_registry([], templates)

        queue = _queue_ref
        if queue is None:
            raise RuntimeError("No task queue available")

        task_ids: list[str] = []
        for i, device in enumerate(devices):
            delay = i * stagger_interval if stagger else 0
            payload = {
                "steps": steps,
                "variables": variables,
                "_campaign_vars": {},
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
    ) -> None:
        """
        Update ScheduleRun status + schedule metadata (last_run_at, next_run_at, run_count).

        Idempotent: safe to call multiple times.
        """
        from db.database import AsyncSessionLocal
        from db.crud.schedule import update_schedule_run, update_schedule_after_run
        from datetime import timezone as tz

        activity.heartbeat("finalize_run")
        now = datetime.now(timezone.utc)
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

        async with AsyncSessionLocal() as db:
            await update_schedule_run(
                db,
                run_id,
                status=status,
                finished_at=now,
                devices_dispatched=normalized.devices_dispatched,
                task_ids=normalized.task_ids,
                error_message=normalized.error,
            )
            next_run = _compute_next_run(cron_expression, timezone_name, now)
            await update_schedule_after_run(
                db,
                schedule_id,
                last_run_at=now,
                next_run_at=next_run,
            )
            await db.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _resolve_fleet_devices(
    *,
    device_group_id: str | None,
    filter_state: str,
    filter_model: str | None,
    max_devices: int | None,
):
    """Resolve devices from DeviceManager (synchronous, in-process)."""
    manager = _manager_ref
    if manager is None:
        return []

    if device_group_id:
        # Filter by group membership — requires DB access, done synchronously via
        # asyncio.run inside worker thread context. Acceptable since activities run
        # in a thread pool.
        import asyncio
        from db.database import AsyncSessionLocal
        from db.crud.device_group import list_group_devices

        async def _get_group_devices():
            async with AsyncSessionLocal() as db:
                return await list_group_devices(db, device_group_id)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, _get_group_devices())
                    db_devices = future.result(timeout=10)
            else:
                db_devices = loop.run_until_complete(_get_group_devices())
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
    """Wrap a task function with an initial sleep for device stagger."""
    if delay_seconds <= 0:
        return fn

    def _wrapper(device):
        time.sleep(delay_seconds)
        return fn(device)

    return _wrapper


def _apply_stagger_to_tasks(task_ids: list[str], interval_seconds: int, queue) -> None:
    """
    Post-dispatch stagger: inject delays into already-queued tasks.
    Only applicable for TaskQueue mode (not Temporal workflows).
    """
    if queue is None or not task_ids:
        return
    for i, task_id in enumerate(task_ids):
        task = queue.get_task(task_id)
        if task is None:
            continue
        delay = i * interval_seconds
        if delay > 0:
            original_fn = task.fn
            task.fn = _make_staggered_task(original_fn, float(delay))


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
